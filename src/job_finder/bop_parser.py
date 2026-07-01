import io
import re
import pdfplumber
from pathlib import Path
from typing import Union, List, Optional
from job_finder.interfaces import BaseParser, BOPage
from job_finder.text_cleaner import clean_text

# Regex to detect major sections (e.g., "III. ADMINISTRACIÓN LOCAL", "IV. ADMINISTRACIÓN DE JUSTICIA")
SECTION_PATTERN = re.compile(
    r"^\s*([IVXLCDM]+)\.?\s+(ADMINISTRACI[OÓ]N\s+[A-ZÁÉÍÓÚÑ\s]+|DISPOSICIONES|ANUNCIOS)",
    re.IGNORECASE | re.MULTILINE
)

# Regex to detect issuing organisms (e.g., "ILUSTRE AYUNTAMIENTO DE SANTA BRÍGIDA", "EXCMO. CABILDO INSULAR DE GRAN CANARIA")
ORGANISM_PATTERN = re.compile(
    r"^\s*(?:EXCMO\.|ILUSTRE|M\.I\.|R\.I\.)?\s*(?:AYUNTAMIENTO|CABILDO|CONSORCIO)\s+(?:INSULAR\s+)?(?:DE\s+)?[A-ZÁÉÍÓÚÑ\s\-]{4,}\b",
    re.MULTILINE
)

class BOPParser(BaseParser):
    """Parses BOP PDF page-by-page, identifying Administración Local pages and organisms."""
    
    def parse(self, source: Union[Path, str, io.BytesIO]) -> List[BOPage]:
        """
        Extracts and cleans text from PDF page-by-page.
        
        Args:
            source: A file path or BytesIO stream of the PDF.
            
        Returns:
            A list of BOPage objects belonging to "III. ADMINISTRACIÓN LOCAL".
        """
        parsed_pages: List[BOPage] = []
        
        # Sticky parsing states
        current_section = ""
        current_organism = "Administración Local (Desconocido)"
        
        # Open PDF using pdfplumber (page-by-page to prevent memory spikes)
        with pdfplumber.open(source) as pdf:
            for page in pdf.pages:
                raw_text = page.extract_text()
                if not raw_text:
                    continue
                
                # Check for section changes in the raw text of this page
                # Section headers are usually on their own lines or at the start of paragraphs
                lines = raw_text.splitlines()
                
                # Check if this page contains section headers
                for line in lines:
                    stripped_line = line.strip()
                    section_match = SECTION_PATTERN.match(stripped_line)
                    if section_match:
                        roman_num = section_match.group(1).upper()
                        sec_name = section_match.group(2).upper()
                        current_section = f"{roman_num}. {sec_name}"
                
                # If we are not currently in the Administración Local section, skip this page
                # The section usually starts with "III. ADMINISTRACIÓN LOCAL"
                is_local_admin = "III." in current_section or "ADMINISTRACIÓN LOCAL" in current_section
                
                if not is_local_admin:
                    continue
                
                # Find organism headers on this page
                # Organisms in the BOP are printed as prominent uppercase lines
                for line in lines:
                    stripped_line = line.strip()
                    # Skip section headers
                    if SECTION_PATTERN.match(stripped_line):
                        continue
                        
                    organism_match = ORGANISM_PATTERN.match(stripped_line)
                    if organism_match:
                        # Clean up multiple spaces and set as the current sticky organism
                        cleaned_org = re.sub(r"\s+", " ", organism_match.group(0).strip())
                        # Standardize casing to Title Case or keep UPPERCASE for clarity
                        current_organism = cleaned_org
                
                # Clean the page's text (preserving original case for display)
                cleaned_page_text = clean_text(raw_text, lowercase=False)
                
                if cleaned_page_text.strip():
                    parsed_pages.append(BOPage(
                        page_number=page.page_number,
                        text=cleaned_page_text,
                        section=current_section,
                        detected_organism=current_organism
                    ))
                    
        return parsed_pages
