import io
from datetime import date
from urllib.parse import urljoin

import requests

from job_finder.interfaces import BaseFetcher, BaseWebBoardFetcher


class GeursaFetcher(BaseFetcher, BaseWebBoardFetcher):
    """Fetcher for the GEURSA employment-selection process list."""

    BASE_URL = "https://www.geursa.es/"
    LIST_URL = "https://www.geursa.es/procesos-de-seleccion/"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
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
        """Return the list page as UTF-8 bytes for BaseFetcher compatibility."""
        del target_date
        return io.BytesIO(self.fetch_list().encode("utf-8"))

    def fetch_list(self) -> str:
        """Download the GEURSA selection-process list HTML."""
        try:
            response = requests.get(
                self.LIST_URL,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to fetch GEURSA job list: {exc}") from exc

    def fetch_detail(self, detail_url: str) -> str:
        """Download a detail URL for interface compatibility.

        GEURSA list parsing is deliberately list-only and does not call this
        method for cards or attachments.
        """
        absolute_url = urljoin(self.BASE_URL, detail_url)
        try:
            response = requests.get(
                absolute_url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to fetch GEURSA detail from {absolute_url}: {exc}"
            ) from exc
