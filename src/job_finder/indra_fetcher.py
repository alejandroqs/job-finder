import io
import re
from datetime import date
from urllib.parse import urljoin, urlparse

import requests

from job_finder.interfaces import BaseFetcher, BaseWebBoardFetcher


class IndraFetchError(RuntimeError):
    """A public Indra request failed at the HTTP boundary."""


class IndraFetcher(BaseFetcher, BaseWebBoardFetcher):
    """Fetch Indra Group search, pagination, and job-detail HTML."""

    BASE_URL = "https://careers.indragroup.com/"
    SEARCH_URL = "https://careers.indragroup.com/search/"
    LIST_URL = SEARCH_URL
    OFFICIAL_HOST = "careers.indragroup.com"
    DEFAULT_LOCALE = "es_ES"
    JOB_ID_PATTERN = re.compile(r"/(?:[^/]+/)?job/[^/]+/(\d+)/?$", re.IGNORECASE)

    def __init__(self, timeout: int = 15, locale: str = DEFAULT_LOCALE):
        self.timeout = timeout
        self.locale = locale
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3",
        }

    def fetch(self, target_date: date) -> io.BytesIO:
        """Return the blank full-catalogue search for web-board compatibility."""
        del target_date
        return io.BytesIO(self.fetch_list().encode("utf-8"))

    def fetch_list(self) -> str:
        """Fetch the default blank search using the configured locale."""
        return self._get(
            self.SEARCH_URL,
            params={"q": "", "locale": self.locale},
            operation="blank search",
        )

    def fetch_search(self, term: str) -> str:
        """Fetch one explicitly supplied search term without rewriting it."""
        return self._get(
            self.SEARCH_URL,
            params={"q": term, "locale": self.locale},
            operation=f"search query {term!r}",
        )

    def fetch_page(self, page_url: str) -> str:
        """Fetch one already-discovered official pagination URL."""
        return self._get(page_url, operation=f"pagination page {page_url}")

    def fetch_detail(self, detail_url: str) -> str:
        """Fetch one official Indra job detail page."""
        return self._get(
            detail_url,
            operation=f"job detail {detail_url}",
            expect_job_redirect=True,
        )

    def _get(
        self,
        url: str,
        params: dict | None = None,
        operation: str = "request",
        expect_job_redirect: bool = False,
    ) -> str:
        absolute_url = self._resolve_official_url(url)
        try:
            request_kwargs = {"headers": self.headers, "timeout": self.timeout}
            if params is not None:
                request_kwargs["params"] = params
            response = requests.get(absolute_url, **request_kwargs)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IndraFetchError(f"Indra {operation} failed at {absolute_url}: {exc}") from exc

        final_url = getattr(response, "url", absolute_url)
        try:
            resolved_final_url = self._resolve_official_url(final_url)
        except ValueError as exc:
            raise IndraFetchError(
                f"Indra {operation} redirected away from the official host: {final_url!r}"
            ) from exc
        if expect_job_redirect:
            requested_job_id = self._job_id(absolute_url)
            redirected_job_id = self._job_id(resolved_final_url)
            if requested_job_id and redirected_job_id != requested_job_id:
                raise IndraFetchError(
                    f"Indra {operation} redirected to a different job: "
                    f"requested ID {requested_job_id}, final URL {resolved_final_url!r}"
                )

        content = getattr(response, "content", None)
        if content is not None:
            return content.decode("utf-8", errors="replace")
        return response.text

    @classmethod
    def _job_id(cls, url: str) -> str:
        match = cls.JOB_ID_PATTERN.search(urlparse(url).path)
        return match.group(1) if match else ""

    @classmethod
    def _resolve_official_url(cls, url: str) -> str:
        try:
            resolved = urlparse(urljoin(cls.BASE_URL, str(url)))
        except ValueError:
            raise ValueError(f"Malformed Indra URL: {url!r}") from None

        if resolved.scheme.lower() not in {"http", "https"}:
            raise ValueError(f"Indra URL is not HTTP(S): {url!r}")
        if resolved.netloc.casefold() != cls.OFFICIAL_HOST:
            raise ValueError(f"Indra URL is not on the official Indra host: {url!r}")
        return resolved.geturl()
