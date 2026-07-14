import io
import requests
from datetime import date
from urllib.parse import urljoin

from job_finder.interfaces import BaseFetcher, BaseWebBoardFetcher

class AenaFetcher(BaseFetcher, BaseWebBoardFetcher):
    """
    Fetcher for Aena's corporate job board.
    Supports standard BaseFetcher and specialized BaseWebBoardFetcher interfaces.
    """
    
    BASE_URL = "https://empleo.aena.es/empleo/"
    LIST_URL = "https://empleo.aena.es/empleo/PFSrv?accion=inicio&SEDE=0"
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.8,en-US;q=0.5,en;q=0.3"
        }

    def fetch(self, target_date: date) -> io.BytesIO:
        """
        BaseFetcher compatibility method.
        Downloads the main job list HTML and wraps it in a binary BytesIO stream.
        """
        html_str = self.fetch_list()
        return io.BytesIO(html_str.encode("utf-8"))

    def fetch_list(self) -> str:
        """
        Downloads the main HTML list of job openings.
        """
        try:
            response = requests.get(self.LIST_URL, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            if response.encoding is None or response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            return response.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Aena job list: {e}")

    def fetch_detail(self, detail_url: str) -> str:
        """
        Downloads the HTML detail page of a specific job opening.
        """
        absolute_url = urljoin(self.BASE_URL, detail_url)
        try:
            response = requests.get(absolute_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            if response.encoding is None or response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            return response.text
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Aena job detail from {absolute_url}: {e}")

    def fetch_pdf(self, pdf_url: str) -> bytes:
        """
        Downloads the binary PDF content of a specific job opening's bases.
        """
        absolute_url = urljoin(self.BASE_URL, pdf_url)
        try:
            response = requests.get(absolute_url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()
            return response.content
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Aena PDF from {absolute_url}: {e}")
