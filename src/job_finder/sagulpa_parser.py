import io
import re
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Union, List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from job_finder.interfaces import BaseParser, BaseWebBoardParser, BaseWebBoardFetcher, BOPage
from job_finder.text_cleaner import clean_text

class SagulpaParser(BaseParser, BaseWebBoardParser):
    """
    Parser for Sagulpa's corporate job board.
    Supports standard BaseParser and specialized BaseWebBoardParser interfaces.
    """

    def __init__(self, fetcher: Optional[BaseWebBoardFetcher] = None):
        """
        Initialises the SagulpaParser.
        
        Args:
            fetcher: Optional fetcher dependency to fetch detail pages.
        """
        self.fetcher = fetcher
        self.base_url = "https://www.sagulpa.com/"
        self.date_pattern = re.compile(r"Fecha de publicación:\s*(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

    def parse_list(self, list_html: str) -> List[dict]:
        """
        Parses the main list HTML, filtering out closed/inactive processes.
        Only keeps active jobs containing an <h2> title tag and not matching cerrado/suspendido keywords.
        
        Args:
            list_html: The raw HTML content of the list view.
            
        Returns:
            A list of dicts representing active job openings.
        """
        soup = BeautifulSoup(list_html, "html.parser")
        active_jobs = []
        
        # Find all job items inside the list (normally within ul.fa-ul)
        job_lists = soup.find_all("ul", class_="fa-ul")
        for ul in job_lists:
            lis = ul.find_all("li")
            for li in lis:
                h2 = li.find("h2")
                if not h2:
                    # Ignore auxiliary lists/links like "PRESENTAR CANDIDATURA"
                    continue
                
                title_text = h2.get_text(strip=True)
                normalized_title = title_text.lower()
                
                # Check for closed/suspended/inactive keywords in the title text
                closed_keywords = ["cerrado", "suspendido", "parado", "cerrar"]
                if any(kw in normalized_title for kw in closed_keywords):
                    continue
                
                # Extract detail URL starting with './ofertas-empleo/' or containing '/ofertas-empleo/'
                detail_url = ""
                links = li.find_all("a")
                for a in links:
                    href = a.get("href", "")
                    if "./ofertas-empleo/" in href or "/ofertas-empleo/" in href:
                        detail_url = urljoin(self.base_url, href)
                        break
                
                if not detail_url:
                    # Fallback to any first link inside the li
                    for a in links:
                        href = a.get("href", "")
                        if href and not href.startswith("javascript:") and "politica-privacidad" not in href:
                            detail_url = urljoin(self.base_url, href)
                            break
                
                # Extract publication date
                li_text = li.get_text()
                date_match = self.date_pattern.search(li_text)
                if date_match:
                    day, month, year = map(int, date_match.groups())
                    job_date = datetime.date(year, month, day)
                else:
                    job_date = datetime.date.today()
                    
                active_jobs.append({
                    "title": title_text,
                    "url": detail_url,
                    "date": job_date
                })
                
        return active_jobs

    def parse_detail(self, detail_html: str) -> str:
        """
        Parses the detail page HTML to extract the full description text.
        Uses single newline separator to keep WYSIWYG tags cohesive.
        
        Args:
            detail_html: The raw HTML content of the detail page.
            
        Returns:
            The description text extracted from the page.
        """
        soup = BeautifulSoup(detail_html, "html.parser")
        
        # Target the main description column
        container = soup.find(class_="margen_menu_lateral_columna")
        if not container:
            # Fallback to body or entire page if specific container is missing
            container = soup.find("body") or soup
            
        # Extract text using a single newline separator to maintain cohesive blocks for KeywordFilter
        return container.get_text(separator="\n")

    def parse(self, source: Union[Path, str, io.BytesIO], target_date: Optional[datetime.date] = None) -> List[BOPage]:
        """
        Parses a Sagulpa HTML source (stream or file) and extracts matching active jobs.
        In Online Mode (fetcher present), parallelizes fetching detail page HTML.
        In Offline Mode, returns list-level metadata.
        
        Args:
            source: A file path or BytesIO stream of the list view HTML.
            target_date: Optional date to filter jobs strictly by publication date.
            
        Returns:
            A list of BOPage objects containing the processed details.
        """
        if isinstance(source, (Path, str)):
            with open(source, "r", encoding="utf-8", errors="replace") as f:
                list_html = f.read()
        elif isinstance(source, io.BytesIO):
            list_html = source.getvalue().decode("utf-8", errors="replace")
        else:
            list_html = source.read() if hasattr(source, "read") else source
            if isinstance(list_html, bytes):
                list_html = list_html.decode("utf-8", errors="replace")

        active_jobs = self.parse_list(list_html)
        
        # Filter by publication date if specified
        if target_date is not None:
            active_jobs = [job for job in active_jobs if job["date"] == target_date]
            
        parsed_pages: List[BOPage] = []

        
        # Tier 2 execution
        if self.fetcher and active_jobs:
            def process_job(job) -> Optional[BOPage]:
                try:
                    detail_html = self.fetcher.fetch_detail(job["url"])
                    raw_desc = self.parse_detail(detail_html)
                    cleaned_desc = clean_text(raw_desc, lowercase=False)
                    
                    # Prefix the description with the title and date for a complete text block
                    full_text = f"{job['title']}\nFecha de publicación: {job['date'].strftime('%d/%m/%Y')}\n\n{cleaned_desc}"
                    
                    return BOPage(
                        page_number=1,  # will be normalized in parent loop
                        text=full_text,
                        section="Ofertas de Empleo",
                        detected_organism="SAGULPA",
                        source="SAGULPA",
                        url=job["url"]
                    )
                except Exception:
                    # Fallback to basic list metadata in case of details fetching error
                    fallback_text = f"{job['title']}\nFecha de publicación: {job['date'].strftime('%d/%m/%Y')}"
                    return BOPage(
                        page_number=1,
                        text=clean_text(fallback_text, lowercase=False),
                        section="Ofertas de Empleo",
                        detected_organism="SAGULPA",
                        source="SAGULPA",
                        url=job["url"]
                    )

            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(process_job, active_jobs)
                
                page_counter = 1
                for bo_page in results:
                    if bo_page:
                        bo_page.page_number = page_counter
                        parsed_pages.append(bo_page)
                        page_counter += 1
        else:
            # Offline Mode: return standard list-level details
            page_counter = 1
            for job in active_jobs:
                text_block = f"{job['title']}\nFecha de publicación: {job['date'].strftime('%d/%m/%Y')}"
                parsed_pages.append(BOPage(
                    page_number=page_counter,
                    text=clean_text(text_block, lowercase=False),
                    section="Ofertas de Empleo",
                    detected_organism="SAGULPA",
                    source="SAGULPA",
                    url=job["url"]
                ))
                page_counter += 1
                
        return parsed_pages
