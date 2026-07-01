import io
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Union, List, Optional
import pdfplumber

from job_finder.interfaces import BaseParser, BaseFetcher, BOPage
from job_finder.text_cleaner import clean_text
from job_finder.keyword_filter import strip_accents

class BOEParser(BaseParser):
    """Parses BOE sumario XML to identify Section II.B announcements and extract text using a Two-Tier Architecture."""

    def __init__(self, pdf_fetcher: Optional[BaseFetcher] = None):
        """
        Initialises the BOE Parser.

        Args:
            pdf_fetcher: Optional fetcher to download candidates' PDF documents.
        """
        self.pdf_fetcher = pdf_fetcher

    def parse(self, source: Union[Path, str, io.BytesIO]) -> List[BOPage]:
        """
        Parses a BOE daily sumario XML source (stream or file) and extracts Section II.B items.
        Applies Tier 1 XML Heuristics and fetches Tier 2 PDFs concurrently for qualifying items.

        Args:
            source: A file path or BytesIO stream of the BOE sumario XML.

        Returns:
            A list of BOPage objects containing the pages of the target bulletins' PDFs.
        """
        if isinstance(source, (Path, str)):
            with open(source, "rb") as f:
                xml_data = f.read()
        elif isinstance(source, io.BytesIO):
            xml_data = source.getvalue()
        else:
            xml_data = source.read() if hasattr(source, "read") else source

        try:
            xml_str = xml_data.decode("utf-8", errors="replace")
            # Sanitise raw/unescaped ampersands
            xml_str = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#[xX][a-fA-F0-9]+);)", "&amp;", xml_str)
            root = ET.fromstring(xml_str.encode("utf-8"))
        except Exception:
            return []

        # Find Section II.B: <seccion codigo="2B" ...>
        seccion_2b = root.find(".//seccion[@codigo='2B']")
        if seccion_2b is None:
            return []

        # Heuristic filters
        NEGATIVE_FILTERS = [
            "policia local", "bomberos", "guardia civil",
            "letrados", "jueces", "auxilio judicial",
            "cuerpo administrativo", "medicos", "enfermeros"
        ]

        candidates = []

        # Traverse each departamento in Section 2B
        for departamento in seccion_2b.findall(".//departamento"):
            dept_name = departamento.get("nombre", "Administración Pública (Desconocido)")
            
            # Build a parent map to find epigraphs
            parent_map = {c: p for p in departamento.iter() for c in p}
            
            for item in departamento.findall(".//item"):
                titulo_elem = item.find("titulo")
                if titulo_elem is None or not titulo_elem.text:
                    continue

                title_text = titulo_elem.text.strip()
                normalized_title = strip_accents(title_text.lower())

                # Tier 1 Heuristics: Negative filters (Safe Rejection)
                if any(neg in normalized_title for neg in NEGATIVE_FILTERS):
                    continue

                ident_elem = item.find("identificador")
                ident_text = ident_elem.text.strip() if ident_elem is not None and ident_elem.text else ""

                url_html_elem = item.find("url_html")
                html_url = url_html_elem.text.strip() if url_html_elem is not None and url_html_elem.text else ""

                url_pdf_elem = item.find("url_pdf")
                pdf_url = url_pdf_elem.text.strip() if url_pdf_elem is not None and url_pdf_elem.text else ""

                # Target URL is the HTML link, falling back to PDF link
                link_url = html_url or pdf_url

                # Extract epigraph/sub-epigraph if available
                epigrafe = parent_map.get(item)
                epigrafe_name = ""
                if epigrafe is not None and epigrafe.tag == "epigrafe":
                    epigrafe_name = epigrafe.get("nombre", "")

                section_info = "II.B. Oposiciones y concursos"
                if epigrafe_name:
                    section_info = f"{section_info} -> {epigrafe_name}"

                candidates.append({
                    "title": title_text,
                    "ident": ident_text,
                    "pdf_url": pdf_url,
                    "link_url": link_url,
                    "dept_name": dept_name,
                    "section_info": section_info
                })

        # Helper to parse a single candidate by falling back to title
        def parse_title_only(candidate) -> BOPage:
            full_text = candidate["title"]
            if candidate["ident"]:
                full_text = f"[{candidate['ident']}] {full_text}"
            cleaned_text = clean_text(full_text, lowercase=False)
            return BOPage(
                page_number=1,
                text=cleaned_text,
                section=candidate["section_info"],
                detected_organism=candidate["dept_name"],
                source="BOE",
                url=candidate["link_url"]
            )

        # Worker for Tier 2 Concurrent PDF fetching & deep-parsing
        def process_candidate(candidate) -> List[BOPage]:
            pdf_url = candidate["pdf_url"]
            if not pdf_url or not self.pdf_fetcher:
                return [parse_title_only(candidate)]

            try:
                # Fetch target binary PDF from BOE
                pdf_stream = self.pdf_fetcher.fetch_pdf(pdf_url)
                
                # Parse PDF page-by-page
                pages = []
                with pdfplumber.open(pdf_stream) as pdf:
                    for idx, page in enumerate(pdf.pages, 1):
                        page_text = page.extract_text() or ""
                        cleaned_text = clean_text(page_text, lowercase=False)
                        
                        full_text = cleaned_text.strip()
                        if candidate["ident"]:
                            full_text = f"[{candidate['ident']}] (PDF Pag {idx}) {full_text}"

                        if full_text.strip():
                            pages.append(BOPage(
                                page_number=idx,
                                text=full_text,
                                section=candidate["section_info"],
                                detected_organism=candidate["dept_name"],
                                source="BOE",
                                url=candidate["link_url"]
                            ))
                return pages if pages else [parse_title_only(candidate)]
            except Exception:
                # Robust Graceful Fallback to XML title on any HTTP or parsing exception
                return [parse_title_only(candidate)]

        parsed_pages: List[BOPage] = []
        
        # Tier 2 execution
        if self.pdf_fetcher and candidates:
            # Use ThreadPoolExecutor to download and parse candidate PDFs concurrently
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(process_candidate, candidates)
                
                page_counter = 1
                for result_list in results:
                    for bo_page in result_list:
                        # Normalize page_number to be sequential for output consistency
                        bo_page.page_number = page_counter
                        parsed_pages.append(bo_page)
                        page_counter += 1
        else:
            # Offline fallback (e.g., in unit tests without network or dry runs)
            page_counter = 1
            for c in candidates:
                bo_page = parse_title_only(c)
                bo_page.page_number = page_counter
                parsed_pages.append(bo_page)
                page_counter += 1

        return parsed_pages
