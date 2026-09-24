"""Bounded read-only fetcher for the SODETEGC employment page."""

from urllib.parse import urljoin, urlsplit

import requests


class SODETEGCFetchError(RuntimeError):
    """Raised when the employment page cannot be fetched safely."""


class SODETEGCFetcher:
    """Fetch only the fixed SODETEGC employment page with strict bounds."""

    URL = "https://www.sodetegc.org/conocenos/informacion-administrativa/empleo/"
    ALLOWED_HOSTS = frozenset({"sodetegc.org", "www.sodetegc.org"})
    PATH = "/conocenos/informacion-administrativa/empleo"
    MAX_BYTES = 2 * 1024 * 1024
    MAX_REDIRECTS = 2
    TIMEOUT = (5, 15)
    REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
    HEADERS = {
        "User-Agent": "job-finder employment-page monitor",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
    }

    @classmethod
    def _validated_redirect(cls, current_url: str, location: str) -> str:
        if not location:
            raise SODETEGCFetchError("Redirect response has no Location header.")

        destination = urljoin(current_url, location)
        try:
            parts = urlsplit(destination)
            port = parts.port
        except ValueError as exc:
            raise SODETEGCFetchError("Redirect destination is malformed.") from exc

        if (
            parts.scheme.lower() != "https"
            or (parts.hostname or "").lower() not in cls.ALLOWED_HOSTS
            or parts.username is not None
            or parts.password is not None
            or port not in {None, 443}
            or parts.path.rstrip("/") != cls.PATH
            or parts.query
            or parts.fragment
        ):
            raise SODETEGCFetchError(
                "Redirect destination is outside the official employment page."
            )
        return destination

    def fetch(self) -> str:
        """Return the current employment-page HTML decoded as strict UTF-8."""
        current_url = self.URL
        redirect_hops = 0

        while True:
            try:
                response = requests.get(
                    current_url,
                    headers=self.HEADERS,
                    timeout=self.TIMEOUT,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.Timeout as exc:
                raise SODETEGCFetchError("Employment-page request timed out.") from exc
            except requests.RequestException as exc:
                raise SODETEGCFetchError(
                    f"Employment-page request failed ({type(exc).__name__})."
                ) from exc

            try:
                if response.status_code in self.REDIRECT_STATUSES:
                    if redirect_hops >= self.MAX_REDIRECTS:
                        raise SODETEGCFetchError(
                            "Employment-page redirect limit exceeded."
                        )
                    current_url = self._validated_redirect(
                        current_url, response.headers.get("Location", "")
                    )
                    redirect_hops += 1
                    continue

                if not 200 <= response.status_code < 300:
                    raise SODETEGCFetchError(
                        f"Employment-page returned HTTP {response.status_code}."
                    )

                media_type = response.headers.get("Content-Type", "")
                media_type = media_type.split(";", 1)[0].strip().lower()
                if media_type not in {"text/html", "application/xhtml+xml"}:
                    raise SODETEGCFetchError(
                        f"Employment-page returned non-HTML content ({media_type or 'missing Content-Type'})."
                    )

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > self.MAX_BYTES:
                            raise SODETEGCFetchError(
                                "Employment-page response exceeds the 2 MiB limit."
                            )
                    except ValueError as exc:
                        raise SODETEGCFetchError(
                            "Employment-page has an invalid Content-Length header."
                        ) from exc

                chunks = []
                byte_count = 0
                try:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        byte_count += len(chunk)
                        if byte_count > self.MAX_BYTES:
                            raise SODETEGCFetchError(
                                "Employment-page response exceeds the 2 MiB limit."
                            )
                        chunks.append(chunk)
                except requests.RequestException as exc:
                    raise SODETEGCFetchError(
                        f"Employment-page body read failed ({type(exc).__name__})."
                    ) from exc

                body = b"".join(chunks)
                if not body:
                    raise SODETEGCFetchError("Employment-page response is empty.")
                try:
                    return body.decode("utf-8-sig", errors="strict")
                except UnicodeDecodeError as exc:
                    raise SODETEGCFetchError(
                        "Employment-page response is not valid UTF-8."
                    ) from exc
            finally:
                response.close()
