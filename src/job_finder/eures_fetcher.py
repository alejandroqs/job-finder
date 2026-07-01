import sys
from typing import Union
from job_finder.interfaces import BaseEUFetcher

class EURESFetcher(BaseEUFetcher):
    """
    Fetches job vacancies from the European Job Mobility Portal (EURES).
    Uses Playwright headlessly to bypass anti-scraping protections, intercept
    session authentication, and query the internal EURES XHR API.
    """

    PORTAL_URL = "https://europa.eu/eures/portal/jv-se/search"
    API_URL = "https://ec.europa.eu/eures/eures-apps/jv-se/api/v1.0/vacancy/search"

    def __init__(self, portal_url: str = PORTAL_URL, api_url: str = API_URL):
        self.portal_url = portal_url
        self.api_url = api_url

    def fetch_raw(self) -> str:
        """
        Emulates browser, navigates to EURES portal, and executes a native
        authenticated XHR API call from the page context.
        
        Returns:
            The raw JSON response string from the EURES API, or empty string on failure/missing dep.
        """
        # Step 1: Lazy import playwright to avoid dependency overhead for non-EURES runs
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("⚠️ Warning: 'playwright' is not installed. Run 'pip install playwright' and 'playwright install' to enable live EURES scans.", file=sys.stderr)
            return ""

        print("🌐 Starting headless browser to bypass EURES anti-scraping...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                
                captured_json = []
                
                def handle_response(response):
                    if "jv-search/search" in response.url and response.status == 200:
                        try:
                            captured_json.append(response.text())
                        except Exception:
                            pass
                            
                page.on("response", handle_response)
                
                print("🌐 Navigating to EURES job mobility portal...")
                target_url = "https://europa.eu/eures/portal/jv-se/search?page=1&resultsPerPage=50&orderBy=BEST_MATCH&previousPageType=findJob&lang=en"
                page.goto(target_url, timeout=45000, wait_until="load")
                
                # Wait up to 10 seconds for the XHR response to be captured
                for _ in range(20):
                    if captured_json:
                        break
                    page.wait_for_timeout(500)
                
                browser.close()
                
                if captured_json:
                    return captured_json[0]
                else:
                    raise Exception("Failed to intercept EURES search XHR response.")
                
        except Exception as e:
            print(f"⚠️ EURES Live fetch failed gracefully: {e}", file=sys.stderr)
            print("ℹ️ Continuing with remainder of source scans.", file=sys.stderr)
            return ""
