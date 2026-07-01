import datetime
import io
import re
from pathlib import Path
from typing import List, Union, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from job_finder.interfaces import BaseEUParser, BOPage

class EULISAParser(BaseEUParser):
    """
    Parses active job listings from the eu-LISA HTML careers board.
    Extracts table rows and resolves relative reference URLs.
    """

    def parse(self, source: Union[str, Path, io.BytesIO], target_date: Optional[datetime.date] = None) -> List[BOPage]:
        """Unified parser method fully compatible with BaseParser interface."""
        if isinstance(source, (str, Path)):
            with open(source, "rb") as f:
                content = f.read()
        elif hasattr(source, "read"):
            content = source.read()
        else:
            content = source
        return self.parse_raw(content, target_date=target_date)


    BASE_URL = "https://www.eulisa.europa.eu/"

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    def parse_raw(self, raw_data: Union[str, bytes], target_date: Optional[datetime.date] = None) -> List[BOPage]:
        """
        Parses raw eu-LISA careers HTML page into normalized BOPage models.
        
        Args:
            raw_data: HTML string or bytes block.
            target_date: Optional target date to filter listings.
            
        Returns:
            A list of BOPage objects.
        """
        pages = []
        if not raw_data:
            return pages
            
        if isinstance(raw_data, bytes):
            try:
                html_text = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                html_text = raw_data.decode("latin-1")
        else:
            html_text = raw_data
            
        soup = BeautifulSoup(html_text, "html.parser")
        
        # Strategy 1: Look for table rows representing vacancies
        rows = soup.find_all("tr")
        
        idx = 1
        for row in rows:
            # Skip table headers
            if row.find("th"):
                continue
                
            # Find the primary vacancy link in the row
            link = row.find("a")
            if not link or not link.get("href"):
                continue
                
            title = link.get_text().strip()
            href = link.get("href")
            
            # Skip noise like general header/footer links
            if any(term in href.lower() for term in ["home", "login", "register", "contact", "about", "privacy"]):
                continue
                
            absolute_url = urljoin(self.base_url, href)
            
            # Extract other column details in this row to build metadata
            cells = row.find_all("td")
            cell_texts = [cell.get_text().strip() for cell in cells]
            
            # Apply date deadline filtering if specified
            if target_date and cell_texts:
                deadline_str = None
                for text in cell_texts:
                    if "/" in text and len(text.split("/")) == 3:
                        deadline_str = text
                        break
                if deadline_str:
                    try:
                        parts = [p.strip() for p in deadline_str.split("/")]
                        if len(parts) == 3:
                            deadline_date = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
                            if deadline_date < target_date:
                                continue
                    except Exception:
                        pass
            
            # Compile description text
            if cell_texts:
                meta_str = " | ".join(cell_texts)
            else:
                meta_str = title
                
            compiled_text = (
                f"Title: {title}\n"
                f"Reference/Details: {meta_str}\n"
                f"Source Portal: eu-LISA Careers"
            )
            
            page = BOPage(
                page_number=idx,
                text=compiled_text,
                detected_organism="eu-LISA",
                source="EULISA",
                url=absolute_url
            )
            pages.append(page)
            idx += 1
            
        # Collect existing URLs to avoid duplicate listings from table links
        url_set = {p.url for p in pages}
        
        # Strategy 2: SharePoint List Blocks / Inline link scanning
        links = soup.find_all("a")
        for link in links:
            href = link.get("href")
            if not href:
                continue
                
            # Skip links residing inside table rows, as they are managed by Strategy 1
            if link.find_parent("tr"):
                continue
                
            absolute_url = urljoin(self.base_url, href)
            if absolute_url in url_set:
                continue
                
            # Check if URL matches vacancy directories or direct e-recruitment portal
            is_vacancy_link = any(
                term in href.lower() or term in absolute_url.lower()
                for term in ["vacancy", "vacancies", "job", "/jobs/", "recruitment.eulisa.europa.eu"]
            )
            if not is_vacancy_link:
                continue
                
            title = link.get_text().strip()
            if len(title) < 5 or any(term in href.lower() for term in ["home", "login", "register", "contact", "about", "privacy"]):
                continue
                
            # Scan parent list item to extract deadline metadata if available
            parent_li = link.find_parent("li")
            deadline_date = None
            meta_details = ""
            if parent_li:
                parent_text = parent_li.get_text()
                meta_details = parent_text.strip().replace("\n", " ")
                
                # Check for standard European DD/MM/YYYY date pattern
                date_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", parent_text)
                if date_match:
                    try:
                        d, m, y = date_match.groups()
                        deadline_date = datetime.date(int(y), int(m), int(d))
                    except Exception:
                        pass
                else:
                    # Check for ISO YYYY-MM-DD
                    date_match_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", parent_text)
                    if date_match_iso:
                        try:
                            y, m, d = date_match_iso.groups()
                            deadline_date = datetime.date(int(y), int(m), int(d))
                        except Exception:
                            pass
                            
            if target_date and deadline_date:
                if deadline_date < target_date:
                    continue
                    
            compiled_text = f"Title: {title}\n"
            if meta_details:
                compiled_text += f"Details: {meta_details}\n"
            compiled_text += "Source Portal: eu-LISA Careers"
            
            page = BOPage(
                page_number=idx,
                text=compiled_text,
                detected_organism="eu-LISA",
                source="EULISA",
                url=absolute_url
            )
            pages.append(page)
            url_set.add(absolute_url)
            idx += 1
            
        return pages
