import io
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, TypedDict, Union
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

from job_finder.interfaces import (
    BOPage,
    BaseParser,
    BaseWebBoardParser,
)
from job_finder.text_cleaner import clean_text


class GuaguasRecord(TypedDict):
    """Normalized metadata extracted from one Guaguas employment card."""

    title: str
    position: str
    vacancies: str
    start_date: date
    end_date: date
    closing_date: date
    publication_date: Optional[date]
    date: date
    url: str


class GuaguasParser(BaseParser, BaseWebBoardParser):
    """Deterministically parse Guaguas employment cards from the list page."""

    LIST_URL = "https://www.guaguas.com/empresa/trabaja-con-nosotros"
    CONTAINER_SELECTOR = ".contenido_seccion.carnets"
    ALTERNATE_CONTAINER_SELECTOR = ".contenido-seccion.carnets"
    SECTION_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
    BASES_SECTION = "bases reguladoras"
    NOTICES_SECTION = "avisos"
    BASES_LINK_PATTERN = re.compile(r"(?<![a-z])bases?(?![a-z])", re.IGNORECASE)
    DATE_PATTERN = re.compile(
        r"(?<!\d)(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{4})(?!\d)"
    )

    def __init__(self, list_url: str = LIST_URL):
        self.list_url = list_url

    @staticmethod
    def _normalise(value: str) -> str:
        return " ".join(value.split())

    @classmethod
    def _select_container(cls, soup: BeautifulSoup) -> Optional[Tag]:
        selectors = f"{cls.CONTAINER_SELECTOR}, {cls.ALTERNATE_CONTAINER_SELECTOR}"
        return soup.select_one(selectors)

    @classmethod
    def has_supported_container(cls, list_html: str) -> bool:
        """Return whether HTML contains a parser-supported Guaguas container."""
        return cls._select_container(BeautifulSoup(list_html, "html.parser")) is not None

    @classmethod
    def _section_label(cls, heading: Tag) -> str:
        return cls._normalise(heading.get_text(" ", strip=True)).rstrip(":").casefold()

    @classmethod
    def _find_section_heading(cls, body: Tag, section_name: str) -> Optional[Tag]:
        wanted = cls._normalise(section_name).rstrip(":").casefold()
        for heading in body.find_all(cls.SECTION_HEADING_TAGS):
            if cls._section_label(heading) == wanted:
                return heading
        return None

    @classmethod
    def _main_metadata_items(cls, panel: Tag) -> Iterable[Tag]:
        """Yield card metadata items before the structural Avisos boundary."""
        body = panel.select_one(".panel-body") or panel
        notice_heading = cls._find_section_heading(body, cls.NOTICES_SECTION)

        for item in body.find_all("li"):
            previous_headings = item.find_all_previous(cls.SECTION_HEADING_TAGS)
            if notice_heading and any(
                previous is notice_heading for previous in previous_headings
            ):
                break
            yield item

    @classmethod
    def _label_value(cls, panel: Tag, label: str) -> str:
        """Return a labelled value from the main application metadata only."""
        wanted = cls._normalise(label).rstrip(":").casefold()
        for item in cls._main_metadata_items(panel):
            strong = item.find("strong")
            if not strong:
                continue
            item_label = cls._normalise(strong.get_text(" ", strip=True)).rstrip(":").casefold()
            if item_label != wanted:
                continue
            full_value = cls._normalise(item.get_text(" ", strip=True))
            strong_value = cls._normalise(strong.get_text(" ", strip=True))
            return full_value[len(strong_value):].lstrip(" :")
        return ""

    @classmethod
    def _section_elements(cls, body: Tag, heading: Tag) -> Iterable[Tag]:
        """Yield elements in one card section without crossing its boundaries."""
        heading_level = int(heading.name[1])
        for element in heading.next_elements:
            if body not in element.parents:
                break
            if isinstance(element, Tag) and element.name in cls.SECTION_HEADING_TAGS:
                if cls._section_label(element) == cls.NOTICES_SECTION:
                    break
                if int(element.name[1]) <= heading_level:
                    break
            if isinstance(element, Tag):
                yield element

    @classmethod
    def _parse_dates(cls, raw_value: str) -> Optional[List[date]]:
        matches = cls.DATE_PATTERN.findall(raw_value)
        if len(matches) != 2:
            return None
        try:
            return [date(int(year), int(month), int(day)) for day, month, year in matches]
        except ValueError:
            return None

    @classmethod
    def _parse_single_date(cls, raw_value: str) -> Optional[date]:
        match = cls.DATE_PATTERN.search(raw_value)
        if not match:
            return None
        try:
            day, month, year = (int(value) for value in match.groups())
            return date(year, month, day)
        except ValueError:
            return None

    @classmethod
    def _slugify(cls, value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value)
        without_accents = "".join(
            character for character in decomposed if unicodedata.category(character) != "Mn"
        )
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents.casefold()).strip("-")
        return slug or "convocatoria"

    def _resolve_url(self, href: str, base_href: str = "") -> str:
        document_base = urljoin(self.list_url, base_href) if base_href else self.list_url
        return urljoin(document_base, href)

    def _fallback_url(self, title: str, start_date: date, end_date: date) -> str:
        identity = f"{self._slugify(title)}-{start_date.isoformat()}-{end_date.isoformat()}"
        return f"{self.list_url}#guaguas-{quote(identity, safe='-')}"

    @classmethod
    def _is_bases_link(cls, anchor: Tag) -> bool:
        """Return whether an attachment identifies itself as bases material."""
        candidates = (
            anchor.get_text(" ", strip=True),
            anchor.get("href", ""),
            anchor.get("title", ""),
            anchor.get("aria-label", ""),
        )
        return any(cls.BASES_LINK_PATTERN.search(value) for value in candidates)

    def _extract_bases_href(self, panel: Tag, base_href: str) -> str:
        body = panel.select_one(".panel-body") or panel
        bases_heading = self._find_section_heading(body, self.BASES_SECTION)
        if bases_heading is None:
            return ""

        for element in self._section_elements(body, bases_heading):
            if (
                element.name == "a"
                and element.get("href")
                and self._is_bases_link(element)
            ):
                return self._resolve_url(element["href"].strip(), base_href)
        return ""

    def _diagnose(self, message: str) -> None:
        print(f"      ⚠️ Guaguas: {message}")

    def _extract_panels(self, soup: BeautifulSoup) -> Optional[List[Tag]]:
        container = self._select_container(soup)
        if container is None:
            self._diagnose(
                "employment container not found (expected .contenido_seccion.carnets "
                "or .contenido-seccion.carnets)."
            )
            return None

        panels = container.select(":scope > .panel") or container.select(".panel")
        if not panels:
            self._diagnose("employment container is empty: no .panel cards found.")
            return []
        return panels

    def _validate_interval(
        self,
        panel: Tag,
        panel_number: int,
        title: str,
        reference_date: date,
    ) -> Optional[Tuple[date, date]]:
        raw_interval = self._label_value(panel, "Convocatoria")
        interval = self._parse_dates(raw_interval)
        if interval is None:
            self._diagnose(
                f"card {panel_number} ({title}) has a missing or invalid Convocatoria interval; skipped."
            )
            return None

        start_date, end_date = interval
        if start_date > end_date:
            self._diagnose(
                f"card {panel_number} ({title}) has an inverted Convocatoria interval; skipped."
            )
            return None
        if not start_date <= reference_date <= end_date:
            return None
        return start_date, end_date

    def _build_record(
        self,
        panel: Tag,
        panel_number: int,
        reference_date: date,
        base_href: str,
    ) -> Optional[GuaguasRecord]:
        title_element = panel.select_one(".panel-title")
        title = self._normalise(title_element.get_text(" ", strip=True)) if title_element else ""
        position = self._label_value(panel, "Puesto")
        title = title or position
        if not title:
            self._diagnose(f"card {panel_number} has no title or Puesto field; skipped.")
            return None

        interval = self._validate_interval(panel, panel_number, title, reference_date)
        if interval is None:
            return None
        start_date, end_date = interval

        vacancies = self._label_value(panel, "Vacantes")
        footer = panel.select_one(".panel-footer")
        footer_text = self._normalise(footer.get_text(" ", strip=True)) if footer else ""
        publication_date = self._parse_single_date(footer_text)
        if footer_text and publication_date is None:
            self._diagnose(f"card {panel_number} ({title}) has an invalid panel-footer date.")

        bases_url = self._extract_bases_href(panel, base_href)
        return {
            "title": title,
            "position": position,
            "vacancies": vacancies,
            "start_date": start_date,
            "end_date": end_date,
            "closing_date": end_date,
            "publication_date": publication_date,
            "date": publication_date or start_date,
            "url": bases_url or self._fallback_url(title, start_date, end_date),
        }

    @staticmethod
    def _deduplicate_records(records: Iterable[GuaguasRecord]) -> List[GuaguasRecord]:
        unique_records: List[GuaguasRecord] = []
        seen_records = set()
        for record in records:
            record_key = (
                record["title"],
                record["position"],
                record["vacancies"],
                record["start_date"],
                record["end_date"],
                record["publication_date"],
                record["url"],
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            unique_records.append(record)
        return unique_records

    def parse_list(
        self, list_html: str, target_date: Optional[date] = None
    ) -> List[GuaguasRecord]:
        """Extract cards whose inclusive application interval contains the reference date."""
        soup = BeautifulSoup(list_html, "html.parser")
        panels = self._extract_panels(soup)
        if not panels:
            return []

        reference_date = target_date or date.today()
        base_tag = soup.find("base", href=True)
        base_href = base_tag.get("href", "").strip() if base_tag else ""
        records: List[GuaguasRecord] = []

        for panel_number, panel in enumerate(panels, start=1):
            record = self._build_record(panel, panel_number, reference_date, base_href)
            if record is not None:
                records.append(record)

        return self._deduplicate_records(records)

    def parse_detail(self, detail_html: str) -> str:
        """Extract text for interface compatibility; list parsing does not call it."""
        soup = BeautifulSoup(detail_html, "html.parser")
        container = soup.find("body") or soup
        return clean_text(container.get_text(separator="\n"), lowercase=False)

    def _read_source(self, source: Union[Path, str, io.BytesIO]) -> str:
        if isinstance(source, (Path, str)):
            with open(source, "rb") as source_file:
                raw_source = source_file.read()
        elif isinstance(source, io.BytesIO):
            raw_source = source.getvalue()
        else:
            raw_source = source.read() if hasattr(source, "read") else source
        if isinstance(raw_source, bytes):
            return raw_source.decode("utf-8", errors="replace")
        return str(raw_source)

    def parse(self, source: Union[Path, str, io.BytesIO], target_date: Optional[date] = None) -> List[BOPage]:
        """Parse list metadata into one normalized BOPage per admitted card."""
        list_html = self._read_source(source)
        records = self.parse_list(list_html, target_date=target_date)
        pages: List[BOPage] = []

        for page_number, record in enumerate(records, start=1):
            text_parts = [record["title"]]
            if record["position"]:
                text_parts.append(f"Puesto: {record['position']}")
            if record["vacancies"]:
                text_parts.append(f"Vacantes: {record['vacancies']}")
            text_parts.append(
                "Convocatoria: del "
                f"{record['start_date'].strftime('%d/%m/%Y')} al "
                f"{record['end_date'].strftime('%d/%m/%Y')}"
            )
            if record["publication_date"]:
                text_parts.append(
                    f"Publicado el {record['publication_date'].strftime('%d/%m/%Y')}"
                )

            pages.append(
                BOPage(
                    page_number=page_number,
                    text=clean_text("; ".join(text_parts), lowercase=False),
                    section="Ofertas de Empleo",
                    detected_organism="Guaguas Municipales",
                    source="GUAGUAS",
                    url=record["url"],
                )
            )

        return pages
