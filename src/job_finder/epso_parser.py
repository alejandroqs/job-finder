import csv
import io
import datetime
from pathlib import Path
from typing import List, Union, Optional
from job_finder.interfaces import BaseEUParser, BOPage

class EPSOParser(BaseEUParser):
    """
    Parses EPSO job vacancy CSV data.
    Normalizes CSV rows into standard BOPage objects.
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
        Parses raw CSV bytes or string into a list of BOPage models.
        
        Args:
            raw_data: Raw CSV string or bytes block.
            target_date: Optional date to filter out expired postings.
            
        Returns:
            A list of BOPage objects.
        """
        pages = []
        if not raw_data:
            return pages
            
        # Standardize on string format
        if isinstance(raw_data, bytes):
            # Read as utf-8 or utf-8-sig to strip potential UTF-8 BOMs
            try:
                csv_text = raw_data.decode("utf-8-sig")
            except UnicodeDecodeError:
                csv_text = raw_data.decode("latin-1")
        else:
            csv_text = raw_data
            
        # Parse CSV
        f = io.StringIO(csv_text.strip())
        reader = csv.DictReader(f)
        
        # Dynamically map fields robustly
        fieldnames = reader.fieldnames or []
        normalized = {}
        for original_field in fieldnames:
            field = original_field.strip().lower()
            if "institution" in field or "agency" in field:
                normalized["agency"] = original_field
            elif field == "title":
                normalized["title"] = original_field
            elif "location" in field:
                normalized["location"] = original_field
            elif "contract" in field:
                normalized["contract"] = original_field
            elif field == "grade":
                normalized["grade"] = original_field
            elif "deadline" in field:
                normalized["deadline"] = original_field
            elif "link" in field or "url" in field:
                normalized["url"] = original_field

        required_keys = ["agency", "title", "location", "contract", "grade", "deadline"]
        missing_keys = [k for k in required_keys if k not in normalized]
        if missing_keys:
            raise ValueError(
                f"CSV headers must contain fields mapping to {required_keys}. "
                f"Missing mapping for: {missing_keys}. "
                f"Headers found: {fieldnames}"
            )
            
        for idx, row in enumerate(reader, 1):
            agency = row.get(normalized["agency"], "").strip()
            title = row.get(normalized["title"], "").strip()
            location = row.get(normalized["location"], "").strip()
            contract = row.get(normalized["contract"], "").strip()
            grade = row.get(normalized["grade"], "").strip()
            deadline = row.get(normalized["deadline"], "").strip()
            
            # Extract URL if present, otherwise fallback
            url = "https://epso.europa.eu/en/job-opportunities/open-for-application"
            if "url" in normalized:
                custom_url = row.get(normalized["url"], "").strip()
                if custom_url:
                    url = custom_url
            
            # Apply date deadline filtering if specified
            if target_date and deadline:
                try:
                    # Get date part (YYYY-MM-DD)
                    date_str = deadline.split()[0]
                    deadline_date = datetime.date.fromisoformat(date_str)
                    if deadline_date < target_date:
                        continue
                except Exception:
                    pass
            
            # Normalization mapping logic:
            # Construct a descriptive, unified description paragraph
            description_text = (
                f"Position: {title}\n"
                f"Institution/Agency: {agency}\n"
                f"Location: {location}\n"
                f"Type of Contract: {contract} ({grade})\n"
                f"Deadline for Applications: {deadline}"
            )
            
            page = BOPage(
                page_number=idx,
                text=description_text,
                detected_organism=agency,
                source="EPSO",
                url=url
            )
            pages.append(page)
            
        return pages
