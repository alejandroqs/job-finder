import io
import re
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Union, List, Optional
from bs4 import BeautifulSoup

from job_finder.interfaces import BaseParser, BaseWebBoardParser, BaseWebBoardFetcher, BOPage
from job_finder.text_cleaner import clean_text

class AenaParser(BaseParser, BaseWebBoardParser):
    """
    Parser for Aena's corporate job board.
    Supports standard BaseParser and specialized BaseWebBoardParser interfaces.
    """

    def __init__(self, fetcher: Optional[BaseWebBoardFetcher] = None):
        """
        Initialises the AenaParser.
        
        Args:
            fetcher: Optional fetcher dependency to fetch detail pages.
        """
        self.fetcher = fetcher

    def parse_list(self, list_html: str) -> List[dict]:
        """
        Parses the main list HTML, extracting all active job openings.
        We do not filter by title keywords here to allow general title roles.
        """
        soup = BeautifulSoup(list_html, "html.parser")
        active_jobs = []
        ths = soup.find_all("div", class_="th")
        
        for th in ths:
            h3 = th.find("h3")
            if not h3:
                continue
            title = h3.get_text(strip=True)
            
            # Extract closing date - search for "Fecha fin" to avoid accent issues
            date_text = None
            span_fin = th.find(lambda tag: tag.name == "span" and "Fecha fin" in tag.get_text())
            if span_fin:
                sibling = span_fin.next_sibling
                if sibling:
                    date_text = sibling.strip()
                    
            closing_date = None
            if date_text:
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})", date_text)
                if m:
                    day, month, year = map(int, m.groups())
                    closing_date = datetime.date(year, month, day)
            
            # Find detail link: in the following div.td3 -> a.azul.botonAvisos
            detail_url = ""
            sibling = th.find_next_sibling()
            while sibling:
                if sibling.name == "div" and "td3" in sibling.get("class", []):
                    a = sibling.find("a", class_="botonAvisos")
                    if a and "href" in a.attrs:
                        detail_url = a["href"]
                        break
                if sibling.name == "span" and "brkfila" in sibling.get("class", []):
                    break
                sibling = sibling.find_next_sibling()
                
            if not detail_url:
                continue
                
            active_jobs.append({
                "title": title,
                "closing_date": closing_date,
                "url": detail_url
            })
            
        return active_jobs

    def parse_detail(self, detail_html: str) -> List[str]:
        """
        Parses the detail page HTML to find the bases PDF URL and any supplemental documents.
        Returns a list of all PDF URLs found.
        """
        soup = BeautifulSoup(detail_html, "html.parser")
        pdf_urls = []
        seen = set()
        for a in soup.find_all("a"):
            href = a.get("href", "")
            if href and ("documentos?get" in href or ("PFSrv" in href and "docId=" in href)):
                if href not in seen:
                    pdf_urls.append(href)
                    seen.add(href)
        return pdf_urls

    def parse(self, source: Union[Path, str, io.BytesIO], target_date: Optional[datetime.date] = None) -> List[BOPage]:
        """
        Parses an Aena list view HTML source and extracts active jobs.
        In Online Mode (fetcher present), parallelizes fetching detail page HTML and deep-parsing PDF text.
        In Offline Mode, returns list-level metadata.
        """
        if isinstance(source, (Path, str)):
            try:
                with open(source, "r", encoding="utf-8") as f:
                    list_html = f.read()
            except UnicodeDecodeError:
                with open(source, "r", encoding="iso-8859-1") as f:
                    list_html = f.read()
        elif isinstance(source, io.BytesIO):
            try:
                list_html = source.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                list_html = source.getvalue().decode("iso-8859-1")
        else:
            list_html = source.read() if hasattr(source, "read") else source
            if isinstance(list_html, bytes):
                try:
                    list_html = list_html.decode("utf-8")
                except UnicodeDecodeError:
                    list_html = list_html.decode("iso-8859-1")

        active_jobs = self.parse_list(list_html)

        # Apply target_date boundary logic if specified
        if target_date is not None:
            active_jobs = [
                job for job in active_jobs
                if job.get("closing_date") is None or target_date <= job["closing_date"]
            ]

        parsed_pages: List[BOPage] = []

        if self.fetcher and active_jobs:
            def process_job(job) -> List[BOPage]:
                pages_list = []
                temp_path = None
                try:
                    # 1. Fetch detail page
                    print(f"   ⏳ Deep-scanning Aena job: {job['title']}...")
                    detail_html = self.fetcher.fetch_detail(job["url"])
                    
                    # 2. Parse detail page to find PDF URL
                    pdf_urls = self.parse_detail(detail_html)
                    if not pdf_urls:
                        raise ValueError("No PDF links found on detail page.")
                    
                    print(f"      📄 Found {len(pdf_urls)} documents for {job['title']}. Downloading and parsing...")
                    
                    # 3. Download and process ALL PDFs
                    from job_finder.main import get_temp_path
                    import uuid
                    import pdfplumber

                    for pdf_url in pdf_urls:
                        try:
                            pdf_content = self.fetcher.fetch_pdf(pdf_url)
                            temp_filename = f"aena_temp_{uuid.uuid4().hex}.pdf"
                            temp_path = get_temp_path(temp_filename)
                            temp_path.write_bytes(pdf_content)
                            
                            with pdfplumber.open(temp_path) as pdf:
                                for idx, page in enumerate(pdf.pages, 1):
                                    page_text = page.extract_text() or ""
                                    cleaned_text = clean_text(page_text, lowercase=False)
                                    if cleaned_text.strip():
                                        # Prefix description with title
                                        full_text = f"CONVOCATORIA: {job['title']}\n\n{cleaned_text}"
                                        pages_list.append(BOPage(
                                            page_number=len(pages_list) + 1,
                                            text=full_text,
                                            section="Convocatorias Aena",
                                            detected_organism="Aena",
                                            source="AENA",
                                            url=job["url"]
                                        ))
                        except Exception as e:
                            print(f"⚠️ Warning: Failed to deep scan PDF {pdf_url} for '{job['title']}': {e}")
                        finally:
                            if temp_path and temp_path.exists():
                                try:
                                    temp_path.unlink(missing_ok=True)
                                except Exception:
                                    pass

                    if not pages_list:
                        raise ValueError("No PDFs contained extractable text.")
                except Exception as e:
                    print(f"⚠️ Warning: Failed to deep scan PDFs for '{job['title']}': {e}")
                    fallback_text = f"CONVOCATORIA: {job['title']}\nFecha fin inscripción: {job['closing_date'].strftime('%d/%m/%Y') if job.get('closing_date') else 'Desconocida'}"
                    pages_list = [BOPage(
                        page_number=1,
                        text=clean_text(fallback_text, lowercase=False),
                        section="Convocatorias Aena",
                        detected_organism="Aena",
                        source="AENA",
                        url=job["url"]
                    )]
                return pages_list

            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(process_job, active_jobs)
                for res_list in results:
                    parsed_pages.extend(res_list)
        else:
            # Offline Mode: return standard list-level details
            page_counter = 1
            for job in active_jobs:
                text_block = f"CONVOCATORIA: {job['title']}\nFecha fin inscripción: {job['closing_date'].strftime('%d/%m/%Y') if job.get('closing_date') else 'Desconocida'}"
                parsed_pages.append(BOPage(
                    page_number=page_counter,
                    text=clean_text(text_block, lowercase=False),
                    section="Convocatorias Aena",
                    detected_organism="Aena",
                    source="AENA",
                    url=job["url"]
                ))
                page_counter += 1

        return parsed_pages
