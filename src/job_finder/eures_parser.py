import json
import re
import io
import datetime
from pathlib import Path
from typing import List, Union, Optional
from bs4 import BeautifulSoup
from job_finder.interfaces import BaseEUParser, BOPage

class EURESParser(BaseEUParser):
    """
    Parses EURES job vacancy JSON data.
    Sanitizes HTML description blocks and normalizes payloads into BOPage models.
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


    def parse_raw(self, raw_data: Union[str, bytes], target_date: Optional[datetime.date] = None) -> List[BOPage]:
        """
        Parses EURES XHR JSON payload into normalized BOPage models.
        
        Args:
            raw_data: JSON string or bytes block.
            target_date: Optional target date to filter listings.
            
        Returns:
            A list of BOPage objects.
        """
        pages = []
        if not raw_data:
            return pages
            
        # Decode bytes if needed
        if isinstance(raw_data, bytes):
            try:
                json_str = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                json_str = raw_data.decode("latin-1")
        else:
            json_str = raw_data
            
        try:
            payload = json.loads(json_str)
        except Exception as e:
            raise ValueError(f"Failed to parse EURES JSON content: {e}")

        # Locate vacancy records (EURES API lists items in 'vacancies' array)
        vacancies = payload.get("vacancies", [])
        if not isinstance(vacancies, list):
            # Check for alternative key names like 'vacancyList'
            vacancies = payload.get("vacancyList", [])
            
        if not isinstance(vacancies, list):
            # If still not found, check if top-level is list
            if isinstance(payload, list):
                vacancies = payload
            else:
                vacancies = []

        for idx, vac in enumerate(vacancies, 1):
            title = vac.get("vacancyTitle", vac.get("title", "Job Vacancy")).strip()
            employer = vac.get("employerName", vac.get("employer", "EURES Employer")).strip()
            location = vac.get("location", "Europe").strip()
            apply_url = vac.get("applyUrl", vac.get("url", "https://europa.eu/eures/portal/jv-se/search")).strip()
            
            raw_desc = vac.get("description", vac.get("shortDescription", ""))
            
            # Clean HTML description block using BeautifulSoup if contains tags
            if "<" in raw_desc and ">" in raw_desc:
                try:
                    soup = BeautifulSoup(raw_desc, "html.parser")
                    # Join paragraphs with newline to preserve structure
                    description = soup.get_text(separator="\n").strip()
                except Exception:
                    # Fallback standard regex cleaning if BS fails
                    description = re.sub(r"<[^>]+>", "", raw_desc).strip()
            else:
                description = raw_desc.strip()
                
            # Compile paragraph for matching
            compiled_text = (
                f"Title: {title}\n"
                f"Employer/Agency: {employer}\n"
                f"Location: {location}\n"
                f"Description: {description}"
            )
            
            page = BOPage(
                page_number=idx,
                text=compiled_text,
                detected_organism=employer,
                source="EURES",
                url=apply_url
            )
            pages.append(page)
            
        return pages
