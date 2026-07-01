import io
import re
import datetime
import requests
from datetime import date
from job_finder.interfaces import BaseFetcher

class BOPFetchError(Exception):
    """Base exception for BOP fetching errors."""
    pass

class BOPNotPublishedError(BOPFetchError):
    """Raised when a BOP was not published on the target date (e.g., weekends, holidays)."""
    pass

class BOPFetcher(BaseFetcher):
    """Downloads BOP daily gazettes from www.boplaspalmas.net."""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

    def get_download_url(self, target_date: date) -> str:
        """
        Constructs the BOP download URL based on the date.
        Format: http://www.boplaspalmas.net/boletines/{YEAR}/{D-M-YY}/{D-M-YY}.pdf
        Day and Month have no leading zeros. Year is 4-digit in directory, 2-digit in file/folder.
        """
        day = target_date.day
        month = target_date.month
        year = target_date.year
        short_year = year % 100
        
        # Build date string like "20-5-26" or "1-4-26"
        date_str = f"{day}-{month}-{short_year:02d}"
        
        return f"http://www.boplaspalmas.net/boletines/{year}/{date_str}/{date_str}.pdf"

    def _download_pdf(self, url: str) -> io.BytesIO:
        """Helper to stream-download a PDF file from a URL."""
        # Enable stream=True to prevent loading entire response in memory before validation
        response = requests.get(
            url, 
            headers=self.headers, 
            stream=True, 
            timeout=self.timeout
        )
        
        if response.status_code == 404:
            raise BOPNotPublishedError(f"URL not found (404): {url}")
            
        response.raise_for_status()
        
        # Read response into memory stream in chunks
        pdf_buffer = io.BytesIO()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                pdf_buffer.write(chunk)
        
        pdf_buffer.seek(0)
        return pdf_buffer

    def fetch(self, target_date: date) -> io.BytesIO:
        """
        Downloads the BOP PDF for a specific date using streaming.
        
        Args:
            target_date: The date to download the bulletin for.
            
        Returns:
            A byte stream (BytesIO) containing the PDF content.
            
        Raises:
            BOPNotPublishedError: If the bulletin is not found (404).
            BOPFetchError: If any other error occurs during the download.
        """
        url = self.get_download_url(target_date)
        try:
            return self._download_pdf(url)
        except BOPNotPublishedError as e:
            # Re-raise with date-specific error message
            raise BOPNotPublishedError(
                f"Boletín Oficial for {target_date.strftime('%Y-%m-%d')} not found (404). "
                f"It might be a weekend, a holiday, or not yet published. URL: {url}"
            ) from e
        except requests.RequestException as e:
            raise BOPFetchError(f"HTTP request failed: {e}") from e

    def fetch_latest(self) -> tuple[io.BytesIO, date]:
        """
        Fetches the latest available BOP bulletin.
        First, scrapes the main bulletin index to find the most recent published PDF link.
        If scraping fails, probes backwards day-by-day up to 7 days from today.
        
        Returns:
            A tuple of (BytesIO stream of the PDF, date of the bulletin).
            
        Raises:
            BOPFetchError: If no bulletin could be downloaded.
        """
        # 1. Attempt to scrape latest bulletin link from main1.php
        try:
            index_url = "http://www.boplaspalmas.net/nbop2/main1.php"
            response = requests.get(index_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            
            # Scrape PDF links matching: boletines/{YEAR}/{day}-{month}-{shortyear}/{day}-{month}-{shortyear}.pdf
            # Group 1: Year, Group 2: Day, Group 3: Month, Group 4: short year
            pattern = re.compile(
                r"boletines/(\d{4})/(\d+)-(\d+)-(\d+)/\2-\3-\4\.pdf", 
                re.IGNORECASE
            )
            matches = pattern.findall(response.text)
            
            if matches:
                latest_match = None
                latest_date = None
                
                for match in matches:
                    year_str, day_str, month_str, short_year_str = match
                    try:
                        d = int(day_str)
                        m = int(month_str)
                        y = int(year_str)
                        parsed_date = date(y, m, d)
                        
                        if latest_date is None or parsed_date > latest_date:
                            latest_date = parsed_date
                            latest_match = match
                    except ValueError:
                        continue
                
                if latest_date and latest_match:
                    year_str, day_str, month_str, short_year_str = latest_match
                    date_str = f"{day_str}-{month_str}-{short_year_str}"
                    pdf_url = f"http://www.boplaspalmas.net/boletines/{year_str}/{date_str}/{date_str}.pdf"
                    
                    pdf_stream = self._download_pdf(pdf_url)
                    return pdf_stream, latest_date
        except Exception:
            # Fall back to day-by-day probing on scrape failure
            pass

        # 2. Hybrid Fallback: Probing day-by-day going backwards
        probe_date = date.today()
        for _ in range(7):
            try:
                pdf_stream = self.fetch(probe_date)
                return pdf_stream, probe_date
            except BOPNotPublishedError:
                probe_date -= datetime.timedelta(days=1)
                
        raise BOPFetchError(
            "Could not automatically locate the latest bulletin. "
            "Scraping the index failed, and probing the last 7 days returned 404s."
        )

