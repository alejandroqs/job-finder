import io
import datetime
import requests
from datetime import date
from job_finder.interfaces import BaseFetcher

class BOEFetchError(Exception):
    """Base exception for BOE fetching errors."""
    pass

class BOENotPublishedError(BOEFetchError):
    """Raised when a BOE was not published on the target date (e.g., weekends, holidays)."""
    pass

class BOEFetcher(BaseFetcher):
    """Downloads BOE sumarios from the official BOE Open Data API."""

    API_URL_TEMPLATE = "https://www.boe.es/datosabiertos/api/boe/sumario/{date_str}"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/xml",
        }

    def fetch(self, target_date: date) -> io.BytesIO:
        """
        Downloads the BOE sumario XML for a specific date.

        Args:
            target_date: The date to download the sumario for.

        Returns:
            A byte stream (BytesIO) containing the XML content.

        Raises:
            BOENotPublishedError: If the sumario is not found (404).
            BOEFetchError: If any other error occurs during the download.
        """
        date_str = target_date.strftime("%Y%m%d")
        url = self.API_URL_TEMPLATE.format(date_str=date_str)

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            
            if response.status_code == 404:
                raise BOENotPublishedError(
                    f"Boletín Oficial del Estado for {target_date.strftime('%Y-%m-%d')} not found (404). "
                    f"It might be a weekend, a holiday, or not yet published. URL: {url}"
                )
            
            response.raise_for_status()
            
            return io.BytesIO(response.content)

        except BOENotPublishedError:
            raise
        except requests.RequestException as e:
            raise BOEFetchError(f"HTTP request failed: {e}") from e

    def fetch_latest(self) -> tuple[io.BytesIO, date]:
        """
        Fetches the latest available BOE bulletin by probing backwards day-by-day.
        It probes up to 7 days from today.

        Returns:
            A tuple of (BytesIO stream of the XML, date of the bulletin).

        Raises:
            BOEFetchError: If no bulletin could be downloaded in the last 7 days.
        """
        probe_date = date.today()
        for _ in range(7):
            try:
                xml_stream = self.fetch(probe_date)
                return xml_stream, probe_date
            except BOENotPublishedError:
                # Correctly handles month boundary and leap years through datetime arithmetic
                probe_date -= datetime.timedelta(days=1)

        raise BOEFetchError(
            "Could not locate a BOE bulletin in the last 7 days. "
            "All probes returned 404."
        )

    def fetch_pdf(self, pdf_url: str) -> io.BytesIO:
        """
        Downloads a PDF from a specific URL.

        Args:
            pdf_url: The URL of the PDF to download.

        Returns:
            A byte stream (BytesIO) containing the PDF content.

        Raises:
            BOEFetchError: If the download fails.
        """
        try:
            response = requests.get(
                pdf_url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return io.BytesIO(response.content)
        except requests.RequestException as e:
            raise BOEFetchError(f"Failed to download PDF from {pdf_url}: {e}") from e

