import io
from datetime import date

import requests

from job_finder.interfaces import BaseFetcher


class GSCFetcher(BaseFetcher):
    """Fetch the GSC selection-process list as UTF-8 HTML."""

    LIST_URL = "https://www.gsccanarias.com/gsc/ofertas-de-empleo/"

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
        """Return the current list as UTF-8 bytes for BaseFetcher compatibility."""
        del target_date
        return io.BytesIO(self.fetch_list().encode("utf-8"))

    def fetch_list(self) -> str:
        """Download the current GSC selection-process list."""
        try:
            response = requests.get(
                self.LIST_URL,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to fetch GSC job list: {exc}") from exc
