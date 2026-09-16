"""Bounded, public-only HTTP fetching for the FULP employment board."""

import io
import re
import time
from datetime import date
from typing import Callable, Optional
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import requests

from job_finder.interfaces import BaseFetcher, BaseWebBoardFetcher


class FulpFetchError(RuntimeError):
    """A FULP request failed or returned an unsafe response."""


class FulpBudgetExceeded(FulpFetchError):
    """The current FULP scan cannot schedule another HTTP attempt."""


class FulpFetcher(BaseFetcher, BaseWebBoardFetcher):
    """Fetch the public FULP list and detail pages with bounded I/O.

    The scheduling budget is deliberately separate from the request timeout.
    A request already in flight may finish after the scheduling deadline; no
    subsequent request is started once the deadline or attempt budget is met.
    """

    BASE_URL = "https://www.fulp.es/"
    LIST_URL = "https://www.fulp.es/ofertas"
    OFFICIAL_HOST = "www.fulp.es"
    LIST_PATH = "/ofertas"
    DETAIL_PATH_PATTERN = re.compile(
        r"^/ofertas/(?P<id>\d+)/(?P<slug>[^/?#]+)$", re.IGNORECASE
    )
    REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
    TRACKING_PARAMETERS = frozenset(
        {
            "fbclid",
            "gclid",
            "msclkid",
            "ref",
            "source",
            "utm_campaign",
            "utm_content",
            "utm_medium",
            "utm_source",
            "utm_term",
        }
    )

    def __init__(
        self,
        timeout: Optional[float] = None,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_attempts: int = 200,
        scheduling_budget_seconds: float = 180.0,
        max_redirects: int = 3,
        clock: Optional[Callable[[], float]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        request_get: Optional[Callable[..., object]] = None,
        session: Optional[object] = None,
        max_http_attempts: Optional[int] = None,
        budget_seconds: Optional[float] = None,
    ) -> None:
        if timeout is not None:
            connect_timeout = timeout
            read_timeout = timeout
        if max_http_attempts is not None:
            max_attempts = max_http_attempts
        if budget_seconds is not None:
            scheduling_budget_seconds = budget_seconds

        if max_attempts < 1:
            raise ValueError("FULP max_attempts must be at least 1")
        if scheduling_budget_seconds <= 0:
            raise ValueError("FULP scheduling_budget_seconds must be positive")
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("FULP connect/read timeouts must be positive")
        if max_redirects < 0:
            raise ValueError("FULP max_redirects cannot be negative")

        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_attempts = int(max_attempts)
        self.scheduling_budget_seconds = float(scheduling_budget_seconds)
        self.max_redirects = int(max_redirects)
        self._clock = clock or monotonic or time.monotonic
        self._request_get = request_get
        self.session = session
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
        }
        self.attempts = 0
        self.scan_started_at = 0.0
        self.last_response_url = ""
        self.begin_scan()

    @classmethod
    def _normalise_id(cls, value: object) -> str:
        text = str(value).strip()
        if not text.isdigit():
            return ""
        return str(int(text))

    @classmethod
    def detail_id(cls, url: str) -> str:
        """Return the canonical numeric ID from a validated detail URL."""
        normalised = cls.normalise_public_url(url, expected="detail")
        match = cls.DETAIL_PATH_PATTERN.fullmatch(urlparse(normalised).path)
        return cls._normalise_id(match.group("id")) if match else ""

    @classmethod
    def normalise_public_url(
        cls,
        url: object,
        *,
        expected: Optional[str] = None,
        expected_id: Optional[str] = None,
    ) -> str:
        """Validate and canonically format a public FULP list/detail URL.

        Relative values are resolved against the trusted public origin. An
        HTTP URL on the exact official host is upgraded locally and is never
        requested over HTTP. Unknown query parameters remain part of the URL;
        only explicitly recognised tracking parameters are removed.
        """
        raw = str(url)
        if not raw.strip():
            raise ValueError("FULP URL is empty")
        if any(ord(character) < 32 or ord(character) == 127 for character in raw):
            raise ValueError("FULP URL contains control characters")
        if "\\" in raw:
            raise ValueError("FULP URL contains a backslash")

        try:
            parsed_input = urlparse(raw)
            resolved = urlparse(urljoin(cls.BASE_URL, raw))
        except ValueError as exc:
            raise ValueError(f"Malformed FULP URL: {raw!r}") from exc

        if parsed_input.username is not None or parsed_input.password is not None:
            raise ValueError("FULP URL credentials are not allowed")
        if resolved.username is not None or resolved.password is not None:
            raise ValueError("FULP URL credentials are not allowed")

        scheme = resolved.scheme.casefold()
        if scheme not in {"http", "https"}:
            raise ValueError("FULP URL must use HTTP(S)")

        try:
            host = resolved.hostname.casefold() if resolved.hostname else ""
            port = resolved.port
        except ValueError as exc:
            raise ValueError(f"Malformed FULP URL port: {raw!r}") from exc
        if host != cls.OFFICIAL_HOST:
            raise ValueError("FULP URL is not on the official public host")

        if scheme == "http":
            if port not in (None, 80):
                raise ValueError("FULP HTTP URL has an unexpected port")
            scheme = "https"
        elif port not in (None, 443):
            raise ValueError("FULP HTTPS URL has an unexpected port")

        decoded_path = unquote(resolved.path or "")
        if not decoded_path or any(
            ord(character) < 32 or ord(character) == 127 or character == "\\"
            for character in decoded_path
        ):
            raise ValueError("FULP URL path is malformed")
        if "//" in decoded_path or any(
            segment in {".", ".."} for segment in decoded_path.split("/")
        ):
            raise ValueError("FULP URL path traversal is not allowed")

        path = decoded_path.rstrip("/") or "/"
        detail_match = cls.DETAIL_PATH_PATTERN.fullmatch(path)
        is_list = path == cls.LIST_PATH
        is_detail = detail_match is not None
        if expected == "list" and not is_list:
            raise ValueError("FULP URL is not the public offers listing")
        if expected == "detail" and not is_detail:
            raise ValueError("FULP URL is not a public offer detail path")
        if expected not in (None, "list", "detail"):
            raise ValueError(f"Unknown FULP URL kind: {expected!r}")
        if expected is None and not (is_list or is_detail):
            raise ValueError("FULP URL is not a supported list/detail path")

        if expected_id is not None:
            if not is_detail:
                raise ValueError("FULP expected ID requires a detail URL")
            actual_id = cls._normalise_id(detail_match.group("id"))
            wanted_id = cls._normalise_id(expected_id)
            if not wanted_id or actual_id != wanted_id:
                raise ValueError(
                    f"FULP detail ID {actual_id or '<missing>'} disagrees with "
                    f"expected ID {expected_id!r}"
                )

        try:
            query_pairs = parse_qsl(resolved.query, keep_blank_values=True)
        except ValueError as exc:
            raise ValueError(f"Malformed FULP URL query: {raw!r}") from exc
        query_pairs = [
            (key, value)
            for key, value in query_pairs
            if key.casefold() not in cls.TRACKING_PARAMETERS
        ]
        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunparse((scheme, cls.OFFICIAL_HOST, path, "", query, ""))

    @classmethod
    def validate_url(
        cls,
        url: object,
        *,
        expected: Optional[str] = None,
        expected_id: Optional[str] = None,
    ) -> str:
        """Public alias for source-local URL validation."""
        return cls.normalise_public_url(url, expected=expected, expected_id=expected_id)

    @classmethod
    def _resolve_official_url(cls, url: object, expected: Optional[str] = None) -> str:
        """Compatibility helper used by tests and source-local parsing."""
        return cls.normalise_public_url(url, expected=expected)

    def begin_scan(self) -> None:
        """Reset attempt/deadline state for one logical online scan."""
        self.attempts = 0
        self.scan_started_at = self._clock()
        self.last_response_url = ""

    reset_budget = begin_scan

    def remaining_budget(self) -> float:
        return self.scheduling_budget_seconds - (self._clock() - self.scan_started_at)

    def _before_attempt(self, url: str, operation: str) -> float:
        remaining = self.remaining_budget()
        if self.attempts >= self.max_attempts:
            raise FulpBudgetExceeded(
                f"FULP {operation} stopped before {url}: HTTP attempt budget "
                f"exhausted ({self.attempts}/{self.max_attempts})"
            )
        if remaining <= 0:
            raise FulpBudgetExceeded(
                f"FULP {operation} stopped before {url}: scheduling budget exhausted "
                f"after {self.scheduling_budget_seconds:.3f}s"
            )
        self.attempts += 1
        return remaining

    def _timeout_for(self, remaining: float) -> tuple[float, float]:
        return min(self.connect_timeout, remaining), min(self.read_timeout, remaining)

    def _request(self, url: str, timeout: tuple[float, float]) -> object:
        if self._request_get is not None:
            return self._request_get(
                url,
                headers=self.headers,
                timeout=timeout,
                allow_redirects=False,
            )
        if self.session is not None:
            return self.session.get(
                url,
                headers=self.headers,
                timeout=timeout,
                allow_redirects=False,
            )
        return requests.get(
            url,
            headers=self.headers,
            timeout=timeout,
            allow_redirects=False,
        )

    @staticmethod
    def _response_location(response: object) -> str:
        headers = getattr(response, "headers", {}) or {}
        if hasattr(headers, "get"):
            value = headers.get("Location")
            if value is None:
                value = headers.get("location")
            return str(value).strip() if value is not None else ""
        return ""

    @staticmethod
    def _response_text(response: object) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        if content is not None and isinstance(content, str):
            return content
        return str(getattr(response, "text", ""))

    def _logical_fetch(
        self,
        url: str,
        *,
        kind: str,
        expected_id: Optional[str] = None,
        operation: str,
    ) -> str:
        current_url = self.normalise_public_url(
            url,
            expected=kind,
            expected_id=expected_id,
        )
        redirect_hops = 0

        while True:
            remaining = self._before_attempt(current_url, operation)
            try:
                response = self._request(current_url, self._timeout_for(remaining))
            except requests.RequestException as exc:
                raise FulpFetchError(
                    f"FULP {operation} failed at {current_url}: {exc}"
                ) from exc

            status_code = getattr(response, "status_code", 200)
            if status_code in self.REDIRECT_STATUSES:
                if redirect_hops >= self.max_redirects:
                    raise FulpFetchError(
                        f"FULP {operation} exceeded the {self.max_redirects}-redirect limit "
                        f"at {current_url}"
                    )
                location = self._response_location(response)
                if not location:
                    raise FulpFetchError(
                        f"FULP {operation} returned redirect status {status_code} "
                        "without a Location header"
                    )
                try:
                    # Validation happens before the next request is scheduled.
                    current_url = self.normalise_public_url(
                        urljoin(self.BASE_URL, location),
                        expected=kind,
                        expected_id=expected_id,
                    )
                except ValueError as exc:
                    raise FulpFetchError(
                        f"FULP {operation} rejected redirect target {location!r}: {exc}"
                    ) from exc
                redirect_hops += 1
                continue

            try:
                raise_for_status = getattr(response, "raise_for_status", None)
                if raise_for_status is not None:
                    raise_for_status()
            except requests.RequestException as exc:
                raise FulpFetchError(
                    f"FULP {operation} failed at {current_url}: {exc}"
                ) from exc

            response_url = getattr(response, "url", None)
            if response_url:
                try:
                    final_url = self.normalise_public_url(
                        response_url,
                        expected=kind,
                        expected_id=expected_id,
                    )
                except ValueError as exc:
                    raise FulpFetchError(
                        f"FULP {operation} response URL is unsafe: {response_url!r}: {exc}"
                    ) from exc
            else:
                final_url = current_url
            self.last_response_url = final_url
            return self._response_text(response)

    def fetch(self, target_date: date) -> io.BytesIO:
        """Return the current list as UTF-8 bytes for BaseFetcher compatibility."""
        del target_date
        return io.BytesIO(self.fetch_list().encode("utf-8"))

    def fetch_list(self) -> str:
        """Fetch the current unfiltered public FULP listing once."""
        return self._logical_fetch(
            self.LIST_URL,
            kind="list",
            operation="offers listing",
        )

    def fetch_detail(self, detail_url: str) -> str:
        """Fetch one validated public FULP detail page."""
        try:
            validated_url = self.normalise_public_url(detail_url, expected="detail")
            offer_id = self.detail_id(validated_url)
        except ValueError as exc:
            raise ValueError(f"Invalid FULP detail URL: {detail_url!r}: {exc}") from exc
        return self._logical_fetch(
            validated_url,
            kind="detail",
            expected_id=offer_id,
            operation=f"offer detail {offer_id}",
        )
