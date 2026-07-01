import httpx
from job_finder.interfaces import BaseEUFetcher

class EULISAFetcher(BaseEUFetcher):
    """
    Fetches the active job vacancy list from the eu-LISA agency careers board.
    """
    
    CAREERS_URL = "https://www.eulisa.europa.eu/jobs/vacancies"
    
    def __init__(self, url: str = CAREERS_URL):
        self.url = url

    def fetch_raw(self) -> str:
        """
        Connects and downloads the careers portal HTML content.
        
        Returns:
            The raw HTML content string of the page.
        """
        response = httpx.get(self.url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        return response.text
