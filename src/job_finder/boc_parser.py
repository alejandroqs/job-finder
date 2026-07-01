import io
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union, List
from job_finder.interfaces import BaseParser, BOPage
from job_finder.text_cleaner import clean_text

class BOCParser(BaseParser):
    """Parses BOC RSS feed XML to identify relevant announcements and extract text."""

    def __init__(self):
        self.h5_pattern = re.compile(r"<h5>(.*?)</h5>", re.IGNORECASE | re.DOTALL)
        self.h3_pattern = re.compile(r"<h3>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
        self.p_pattern = re.compile(r"<p>(.*?)</p>", re.IGNORECASE | re.DOTALL)

    def _strip_html_tags(self, text: str) -> str:
        """Removes HTML tags and normalizes whitespace."""
        cleaned = re.sub(r"<[^>]+>", "", text)
        return " ".join(cleaned.split())

    def _is_target_section(self, section: str, subsection: str) -> bool:
        """
        Determines if a section and subsection match target criteria:
        1. Section II. Autoridades y Personal -> Subsection Oposiciones y concursos (II.B)
        2. Section III. Otras Resoluciones
        3. Section V. Anuncios -> Subsection Administración Local
        """
        sec_lower = section.lower()
        sub_lower = subsection.lower()

        # Target 1: II. Autoridades y Personal -> Oposiciones y concursos (II.B)
        if "ii." in sec_lower and "autoridades" in sec_lower and "personal" in sec_lower:
            return "oposiciones" in sub_lower or "concursos" in sub_lower

        # Target 2: III. Otras Resoluciones (e.g. Universities)
        if "iii." in sec_lower and "otras" in sec_lower and "resoluciones" in sec_lower:
            return True

        # Target 3: V. Anuncios -> Administración Local
        if "v." in sec_lower and "anuncios" in sec_lower:
            return "administracion local" in sub_lower or "administración local" in sub_lower

        return False

    def parse(self, source: Union[Path, str, io.BytesIO]) -> List[BOPage]:
        """
        Parses a BOC RSS XML source (stream or file) and extracts matching articles.

        Args:
            source: A file path or BytesIO stream of the RSS XML.

        Returns:
            A list of BOPage objects containing the matching items.
        """
        if isinstance(source, (Path, str)):
            with open(source, "rb") as f:
                xml_data = f.read()
        elif isinstance(source, io.BytesIO):
            xml_data = source.getvalue()
        else:
            xml_data = source.read() if hasattr(source, "read") else source

        parsed_pages: List[BOPage] = []

        try:
            xml_str = xml_data.decode("utf-8", errors="replace")
            # Sanitise raw ampersands
            import re
            xml_str = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#[xX][a-fA-F0-9]+);)", "&amp;", xml_str)
            root = ET.fromstring(xml_str.encode("utf-8"))
        except Exception:
            # Return empty if XML parsing fails (e.g. empty or corrupted content)
            return []

        # Target all items in the RSS
        # Support both flat and channel-nested items
        items = root.findall(".//item")
        
        page_counter = 1
        for item in items:
            link_elem = item.find("link")
            link_url = link_elem.text.strip() if link_elem is not None and link_elem.text else ""

            desc_elem = item.find("description")
            if desc_elem is None or not desc_elem.text:
                continue

            # Decode XML entities (description is HTML-escaped)
            desc_html = html.unescape(desc_elem.text)

            # Extract <h5> (hierarchy) and check sections
            h5_match = self.h5_pattern.search(desc_html)
            if not h5_match:
                continue

            h5_content = self._strip_html_tags(h5_match.group(1))
            segments = [s.strip() for s in h5_content.split(" - ")]

            section = segments[0] if len(segments) > 0 else ""
            subsection = segments[1] if len(segments) > 1 else ""
            organism = segments[-1] if len(segments) > 0 else "Administración Local (Desconocido)"

            if not self._is_target_section(section, subsection):
                continue

            # Extract <h3> (title/content)
            h3_match = self.h3_pattern.search(desc_html)
            h3_text = self._strip_html_tags(h3_match.group(1)) if h3_match else ""

            # Standardize title or fallback to feed title if h3 is missing
            item_title = h3_text if h3_text else (item.find("title").text or "")

            # Compile text elements for keyword matching
            text_elements = [item_title]

            # Extract paragraphs if any
            p_matches = self.p_pattern.findall(desc_html)
            for p in p_matches:
                p_text = self._strip_html_tags(p)
                if p_text and not p_text.startswith("CVE:"):
                    text_elements.append(p_text)

            full_text = "\n\n".join(text_elements)
            cleaned_text = clean_text(full_text, lowercase=False)

            if cleaned_text.strip():
                parsed_pages.append(BOPage(
                    page_number=page_counter,
                    text=cleaned_text,
                    section=f"{section} -> {subsection}",
                    detected_organism=organism,
                    source="BOC",
                    url=link_url
                ))
                page_counter += 1

        return parsed_pages
