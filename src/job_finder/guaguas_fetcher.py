import io
from datetime import date
from urllib.parse import urljoin

import requests

from job_finder.interfaces import BaseFetcher, BaseWebBoardFetcher


class GuaguasFetcher(BaseFetcher, BaseWebBoardFetcher):
    """Fetcher for the Guaguas Municipales employment list."""

    BASE_URL = "https://www.guaguas.com/"
    LIST_URL = "https://www.guaguas.com/empresa/trabaja-con-nosotros"

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
        """Return the employment list as a binary stream for BaseFetcher compatibility."""
        del target_date
        return io.BytesIO(self.fetch_list().encode("utf-8"))

    def fetch_list(self) -> str:
        """Download the Guaguas employment list HTML."""
        try:
            response = requests.get(
                self.LIST_URL,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to fetch Guaguas job list: {exc}") from exc

    def fetch_detail(self, detail_url: str) -> str:
        """Download a detail URL for interface compatibility.

        The Guaguas parser does not call this method for each card because the list
        already contains the fields needed by the monitor.
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
                f"Failed to fetch Guaguas detail from {absolute_url}: {exc}"
            ) from exc
