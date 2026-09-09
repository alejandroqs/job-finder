import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Comment, Tag

from job_finder.interfaces import BOPage, BaseParser
from job_finder.text_cleaner import clean_text


@dataclass(frozen=True)
class GSCRecord:
    """Normalized metadata extracted from one GSC selection card."""

    title: str
    publication_date: date
    inferred_end_date: date
    url: str


class GSCParser(BaseParser):
    """Parse current GSC records from the bounded selection-list holder."""

    LIST_URL = "https://www.gsccanarias.com/gsc/ofertas-de-empleo/"
    SECTION_ID = "seleccion"
    HOLDER_SELECTOR = ".projects_holder.portfolio_main_holder"
    TITLE_SELECTOR = "h5.portfolio_title.entry_title"
    SECTION_LABEL = "Procesos de seleccion"
    ORGANISM = "Gestión de Servicios para la Salud y Seguridad en Canarias"
    DATE_PATTERN = re.compile(
        r"^\s*(?P<day>\d{2})(?P<separator>[/\-])(?P<month>\d{2})"
        r"(?P=separator)(?P<year>\d{4})(?=\s|$)"
    )
    ADMINISTRATIVE_PATTERNS = (
        re.compile(r"\bresultados?\b"),
        re.compile(r"\b(?:listad[oa]?|relacion|lista)\s+(?:provisional|definitiv[oa]?)\b"),
        re.compile(
            r"\b(?:listad[oa]?|relacion|lista)\s+de\s+"
            r"(?:aspirantes?|admitid[oa]s?|admision)\b"
        ),
        re.compile(
            r"\b(?:correccion(?:es)?|rectificacion(?:es)?|errata(?:s)?)\b"
        ),
        re.compile(r"\bsubsanacion(?:es)?\b"),
        re.compile(
            r"\b(?:convocatoria|citacion|llamamiento)\b.*"
            r"\b(?:fase|prueba|examen|ejercicio|conocimientos)\b"
        ),
        re.compile(
            r"\b(?:anula|anulado|anulada|anulacion|anulaciones|"
            r"cancela|cancelado|cancelada|cancelacion|cancelaciones)\b"
        ),
    )

    def __init__(self, list_url: str = LIST_URL):
        self.list_url = list_url

    @staticmethod
    def _normalise(value: str) -> str:
        collapsed = " ".join(value.split())
        return re.sub(r"\s+([,.;:!?])", r"\1", collapsed)

    @staticmethod
    def _strip_accents(value: str) -> str:
        decomposed = unicodedata.normalize("NFD", value)
        return "".join(
            character
            for character in decomposed
            if unicodedata.category(character) != "Mn"
        )

    @classmethod
    def _nearest_article(cls, element: Tag) -> Optional[Tag]:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if current.name == "article":
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _owned_descendants(cls, article: Tag, selector: str) -> Iterable[Tag]:
        return (
            element
            for element in article.select(selector)
            if cls._nearest_article(element) is article
        )

    @classmethod
    def _selection_section(cls, soup: BeautifulSoup) -> Optional[Tag]:
        section = soup.find(id=cls.SECTION_ID)
        return section if isinstance(section, Tag) else None

    @classmethod
    def _selection_holders(cls, section: Tag) -> List[Tag]:
        holders = []
        for holder in section.select(cls.HOLDER_SELECTOR):
            owner = holder.find_parent(id=cls.SECTION_ID)
            if owner is section:
                holders.append(holder)
        return holders

    @classmethod
    def has_supported_structure(cls, list_html: str) -> bool:
        """Return whether HTML contains the bounded GSC selection holder."""
        soup = BeautifulSoup(list_html, "html.parser")
        section = cls._selection_section(soup)
        return section is not None and bool(cls._selection_holders(section))

    @classmethod
    def _title_anchor(cls, article: Tag) -> Optional[Tag]:
        headings = list(cls._owned_descendants(article, cls.TITLE_SELECTOR))
        if len(headings) != 1:
            return None

        anchors = [
            anchor
            for anchor in headings[0].find_all("a")
            if cls._nearest_article(anchor) is article
        ]
        return anchors[0] if len(anchors) == 1 else None

    @classmethod
    def _publication_date(cls, title: str) -> Optional[date]:
        match = cls.DATE_PATTERN.match(title)
        if match is None:
            return None

        try:
            return date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        except ValueError:
            return None

    @classmethod
    def _is_administrative_notice(cls, title: str) -> bool:
        normalized_title = cls._strip_accents(title).casefold()
        return any(pattern.search(normalized_title) for pattern in cls.ADMINISTRATIVE_PATTERNS)

    @classmethod
    def _owned_text(cls, element: Tag, article: Tag) -> str:
        owned_text = []
        for text_node in element.find_all(string=True):
            if isinstance(text_node, Comment):
                continue
            parent = text_node.parent
            if isinstance(parent, Tag) and cls._nearest_article(parent) is article:
                owned_text.append(str(text_node))
        return cls._normalise(" ".join(owned_text))

    def _resolve_title_url(self, anchor: Tag) -> str:
        href = str(anchor.get("href", "")).strip()
        if not href or href.startswith("#"):
            return ""

        try:
            raw_url = urlparse(href)
            if raw_url.scheme and raw_url.scheme.lower() not in {"http", "https"}:
                return ""

            resolved_url = urljoin(self.list_url, href)
            resolved = urlparse(resolved_url)
        except ValueError:
            return ""

        if resolved.scheme.lower() not in {"http", "https"} or not resolved.netloc:
            return ""
        return resolved_url

    def _diagnose(self, message: str) -> None:
        print(f"      ⚠️ GSC: {message}")

    def _build_record(
        self,
        article: Tag,
        card_number: int,
        reference_date: date,
    ) -> Optional[GSCRecord]:
        title_anchor = self._title_anchor(article)
        if title_anchor is None:
            self._diagnose(
                f"card {card_number} has no unambiguous owned title anchor; skipped."
            )
            return None

        title = self._owned_text(title_anchor, article)
        if not title:
            self._diagnose(f"card {card_number} has an empty owned title; skipped.")
            return None

        publication_date = self._publication_date(title)
        if publication_date is None:
            self._diagnose(
                f"card {card_number} ({title}) has a missing, invalid, or unsupported "
                "leading publication date; skipped."
            )
            return None

        if self._is_administrative_notice(title):
            self._diagnose(
                f"card {card_number} ({title}) is an administrative or cancelled notice; "
                "skipped."
            )
            return None

        inferred_end_date = publication_date + timedelta(days=7)
        if not publication_date <= reference_date <= inferred_end_date:
            self._diagnose(
                f"card {card_number} ({title}) is outside the inferred monitoring window "
                f"{publication_date:%d/%m/%Y} to {inferred_end_date:%d/%m/%Y}; skipped."
            )
            return None

        resolved_url = self._resolve_title_url(title_anchor)
        if not resolved_url:
            resolved_url = self.list_url
            self._diagnose(
                f"card {card_number} ({title}) has no usable title URL; using the GSC "
                "list URL as fallback."
            )

        return GSCRecord(
            title=title,
            publication_date=publication_date,
            inferred_end_date=inferred_end_date,
            url=resolved_url,
        )

    @staticmethod
    def _deduplicate_records(records: Iterable[GSCRecord]) -> List[GSCRecord]:
        unique_records: List[GSCRecord] = []
        seen_records = set()
        for record in records:
            record_key = (
                record.title,
                record.publication_date,
                record.url,
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            unique_records.append(record)
        return unique_records

    def parse_list(
        self, list_html: str, target_date: Optional[date] = None
    ) -> List[GSCRecord]:
        """Extract included GSC records from the bounded selection holder."""
        soup = BeautifulSoup(list_html, "html.parser")
        section = self._selection_section(soup)
        if section is None:
            self._diagnose("selection section #seleccion not found; unsupported layout.")
            return []

        holders = self._selection_holders(section)
        if not holders:
            self._diagnose(
                "selection section has no owned selection holder "
                ".projects_holder.portfolio_main_holder; unsupported layout."
            )
            return []

        holder = holders[0]
        articles = holder.find_all("article", recursive=False)
        if not articles:
            self._diagnose(
                "selection holder is supported but empty: no direct article cards found."
            )
            return []

        reference_date = target_date if target_date is not None else date.today()
        records = [
            record
            for card_number, article in enumerate(articles, start=1)
            if (record := self._build_record(article, card_number, reference_date)) is not None
        ]
        return self._deduplicate_records(records)

    @staticmethod
    def _read_source(source: Union[Path, str, io.BytesIO]) -> str:
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

    def parse(
        self,
        source: Union[Path, str, io.BytesIO],
        target_date: Optional[date] = None,
    ) -> List[BOPage]:
        """Parse one BOPage per included GSC selection-process record."""
        list_html = self._read_source(source)
        records = self.parse_list(list_html, target_date=target_date)
        pages: List[BOPage] = []

        for page_number, record in enumerate(records, start=1):
            text = " ".join(
                (
                    record.title,
                    f"Fecha de publicación: {record.publication_date:%d/%m/%Y}",
                    "Fin de ventana de seguimiento inferida: "
                    f"{record.inferred_end_date:%d/%m/%Y} "
                    "(publicación + 7 días; no es un plazo oficial de solicitud)",
                )
            )
            pages.append(
                BOPage(
                    page_number=page_number,
                    text=clean_text(text, lowercase=False),
                    section=self.SECTION_LABEL,
                    detected_organism=self.ORGANISM,
                    source="GSC",
                    url=record.url,
                )
            )
        return pages
