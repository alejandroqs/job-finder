import io
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, TypedDict, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from job_finder.interfaces import BOPage, BaseParser, BaseWebBoardParser
from job_finder.text_cleaner import clean_text


class GeursaRecord(TypedDict):
    """Stable list metadata extracted from one active GEURSA card."""

    title: str
    description: str
    deadline_text: str
    attachment_captions: List[str]
    url: str


@dataclass(frozen=True)
class SectionContext:
    owner: Tag
    heading_position: int
    boundary_position: int
    positions: dict[int, int]


class GeursaParser(BaseParser, BaseWebBoardParser):
    """Parse GEURSA cards from the active-process accordion section."""

    LIST_URL = "https://www.geursa.es/procesos-de-seleccion/"
    ACTIVE_SECTION = "Convocatorias en vigor"
    FINALIZED_SECTION = "Convocatorias finalizadas"
    HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
    CARD_SELECTOR = ".x-acc-item"
    TITLE_SELECTOR = ".x-acc-header-text"
    CONTENT_SELECTOR = ".x-acc-content"
    BASES_PATTERN = re.compile(r"(?<![a-z])bases?(?![a-z])", re.IGNORECASE)
    ATTACHMENT_CAPTION_PATTERN = re.compile(
        r"^(?:bases?|anexo\b|listad[oa]\b|baremaci[oó]n\b|"
        r"resoluci[oó]n\b|entrevista\b|subsanaci[oó]n\b)",
        re.IGNORECASE,
    )

    def __init__(self, list_url: str = LIST_URL):
        self.list_url = list_url

    @staticmethod
    def _normalise(value: str) -> str:
        collapsed = " ".join(value.split())
        return re.sub(r"\s+([,.;:!?])", r"\1", collapsed)

    @classmethod
    def _heading_label(cls, heading: Tag) -> str:
        return cls._normalise(heading.get_text(" ", strip=True)).rstrip(":").casefold()

    @classmethod
    def _is_card(cls, element: Tag) -> bool:
        return cls.CARD_SELECTOR[1:] in (element.get("class") or [])

    @classmethod
    def _nearest_card(cls, element: Tag) -> Optional[Tag]:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if cls._is_card(current):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _belongs_to_card(cls, element: Tag, card: Tag) -> bool:
        return cls._nearest_card(element) is card

    @classmethod
    def _owned_descendants(cls, card: Tag, selector: str) -> Iterable[Tag]:
        return (
            element
            for element in card.select(selector)
            if cls._belongs_to_card(element, card)
        )

    @classmethod
    def _find_owned_descendant(cls, card: Tag, selector: str) -> Optional[Tag]:
        return next(iter(cls._owned_descendants(card, selector)), None)

    @classmethod
    def _is_inside_card(cls, element: Tag) -> bool:
        return cls._nearest_card(element) is not None

    @classmethod
    def _find_active_heading(cls, soup: BeautifulSoup) -> Optional[Tag]:
        wanted = cls._normalise(cls.ACTIVE_SECTION).casefold()
        for heading in soup.find_all("h4"):
            if not cls._is_inside_card(heading) and cls._heading_label(heading) == wanted:
                return heading
        return None

    @staticmethod
    def _is_descendant(element: Tag, ancestor: Tag) -> bool:
        return element is ancestor or ancestor in element.parents

    @classmethod
    def _find_owner(
        cls,
        heading: Tag,
        soup: BeautifulSoup,
    ) -> Tag:
        """Find the nearest semantic owner, including an empty one.

        A semantic container is a section boundary even when it contains no
        accordion cards.  Falling back to the document in that case would
        make a supported-but-empty active section consume cards from a later
        unrelated section.
        """
        fallback = soup.body or soup
        for ancestor in heading.parents:
            if not isinstance(ancestor, Tag):
                continue
            is_semantic_owner = ancestor.name in {"section", "article", "main"}
            is_region = ancestor.get("role") == "region"
            if not (is_semantic_owner or is_region):
                continue
            return ancestor
        return fallback

    @classmethod
    def _section_context(cls, soup: BeautifulSoup, heading: Tag) -> SectionContext:
        tags = soup.find_all(True)
        positions = {id(tag): position for position, tag in enumerate(tags)}
        heading_position = positions[id(heading)]
        owner = cls._find_owner(soup=soup, heading=heading)

        boundary_position = len(tags)
        heading_level = int(heading.name[1])
        for candidate in soup.find_all(cls.HEADING_TAGS):
            candidate_position = positions[id(candidate)]
            if candidate_position <= heading_position:
                continue
            if owner is not soup and not cls._is_descendant(candidate, owner):
                continue
            if cls._is_inside_card(candidate):
                continue
            candidate_level = int(candidate.name[1])
            if candidate_level <= heading_level:
                boundary_position = candidate_position
                break

        return SectionContext(
            owner=owner,
            heading_position=heading_position,
            boundary_position=boundary_position,
            positions=positions,
        )

    @classmethod
    def _cards_in_context(
        cls, soup: BeautifulSoup, context: SectionContext
    ) -> List[Tag]:
        cards: List[Tag] = []
        for card in soup.select(cls.CARD_SELECTOR):
            card_position = context.positions[id(card)]
            if not context.heading_position < card_position < context.boundary_position:
                continue
            if context.owner is not soup and not cls._is_descendant(card, context.owner):
                continue
            cards.append(card)
        return cards

    @classmethod
    def _section_cards(cls, soup: BeautifulSoup, heading: Tag) -> List[Tag]:
        return cls._cards_in_context(soup, cls._section_context(soup, heading))

    @classmethod
    def has_supported_structure(cls, list_html: str) -> bool:
        """Return whether HTML has an active GEURSA accordion structure."""
        soup = BeautifulSoup(list_html, "html.parser")
        heading = cls._find_active_heading(soup)
        return heading is not None and bool(cls._section_cards(soup, heading))

    @classmethod
    def has_supported_layout(cls, list_html: str) -> bool:
        """Compatibility alias for callers describing layout recognition."""
        return cls.has_supported_structure(list_html)

    @classmethod
    def _controlled_content(
        cls,
        card: Tag,
        soup: BeautifulSoup,
        section_context: SectionContext,
    ) -> Optional[Tag]:
        """Find valid card-local or active-section-controlled content.

        GEURSA sometimes keeps a controlled panel outside the card that
        references it.  Such a panel is valid only inside the active section
        bounds and when it is not owned by another accordion card.
        """
        local_content = cls._find_owned_descendant(card, cls.CONTENT_SELECTOR)
        if local_content is not None:
            return local_content

        for button in cls._owned_descendants(card, "[aria-controls]"):
            for control_id in re.split(r"\s+", button.get("aria-controls", "").strip()):
                if not control_id:
                    continue
                panel = soup.find(id=control_id.lstrip("#"))
                if not isinstance(panel, Tag):
                    continue
                candidate = panel
                if cls.CONTENT_SELECTOR[1:] not in (candidate.get("class") or []):
                    candidate = panel.select_one(cls.CONTENT_SELECTOR)
                if candidate is None:
                    continue

                candidate_position = section_context.positions.get(id(candidate))
                if candidate_position is None:
                    continue
                if not section_context.heading_position < candidate_position < section_context.boundary_position:
                    continue
                if (
                    section_context.owner is not soup
                    and not cls._is_descendant(candidate, section_context.owner)
                ):
                    continue
                if cls._is_referenced_by_other_card(panel, candidate, card, soup):
                    continue
                owning_card = cls._nearest_card(candidate)
                if owning_card is not None and owning_card is not card:
                    continue
                return candidate

        return None

    @classmethod
    def _is_referenced_by_other_card(
        cls, panel: Tag, candidate: Tag, card: Tag, soup: BeautifulSoup
    ) -> bool:
        """Return whether another accordion card claims the same panel."""
        panel_ids = {
            value.lstrip("#")
            for value in (panel.get("id"), candidate.get("id"))
            if value
        }
        if not panel_ids:
            return False

        for other_card in soup.select(cls.CARD_SELECTOR):
            if other_card is card:
                continue
            for button in cls._owned_descendants(other_card, "[aria-controls]"):
                controls = {
                    value.lstrip("#")
                    for value in re.split(r"\s+", button.get("aria-controls", "").strip())
                    if value
                }
                if panel_ids.intersection(controls):
                    return True
        return False

    @classmethod
    def _link_label(cls, anchor: Tag) -> str:
        return cls._normalise(anchor.get_text(" ", strip=True))

    @classmethod
    def _is_bases_link(cls, anchor: Tag) -> bool:
        values = (
            cls._link_label(anchor),
            anchor.get("title", ""),
            anchor.get("aria-label", ""),
            anchor.get("href", ""),
        )
        return any(cls.BASES_PATTERN.search(value) for value in values)

    def _resolve_url(self, href: str) -> str:
        href = href.strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            return ""
        resolved = urljoin(self.list_url, href)
        if urlparse(resolved).scheme not in {"http", "https"}:
            return ""
        return resolved

    @classmethod
    def _belongs_to_card_or_selected_content(
        cls, element: Tag, card: Tag, content: Optional[Tag]
    ) -> bool:
        nearest_card = cls._nearest_card(element)
        if nearest_card is not None:
            return nearest_card is card
        return content is not None and cls._is_descendant(element, content)

    def _extract_bases_url(self, card: Tag, content: Optional[Tag]) -> str:
        scopes: List[Tag] = []
        if content is not None:
            scopes.append(content)
        scopes.append(card)

        anchors: List[Tag] = []
        seen_anchor_ids = set()
        for scope in scopes:
            for anchor in scope.find_all("a", href=True):
                if not self._belongs_to_card_or_selected_content(anchor, card, content):
                    continue
                if id(anchor) not in seen_anchor_ids:
                    anchors.append(anchor)
                    seen_anchor_ids.add(id(anchor))

        for exact in (True, False):
            for anchor in anchors:
                if not self._is_bases_link(anchor):
                    continue
                if exact and self._link_label(anchor).casefold() != "bases":
                    continue
                resolved = self._resolve_url(anchor["href"])
                if resolved:
                    return resolved
        return self.list_url

    @classmethod
    def _extract_body_text(
        cls, content: Optional[Tag]
    ) -> tuple[str, List[str]]:
        if content is None:
            return "", []

        copy = BeautifulSoup(str(content), "html.parser")
        for nested_card in copy.select(cls.CARD_SELECTOR):
            nested_card.decompose()

        attachment_captions: List[str] = []
        for anchor in copy.find_all("a"):
            caption = cls._link_label(anchor)
            if caption:
                attachment_captions.append(caption)
            anchor.decompose()

        for block in list(copy.find_all(("p", "li"))):
            block_text = cls._normalise(block.get_text(" ", strip=True))
            if block_text and cls.ATTACHMENT_CAPTION_PATTERN.match(block_text):
                block.decompose()

        return cls._normalise(copy.get_text(" ", strip=True)), attachment_captions

    def _diagnose(self, message: str) -> None:
        print(f"      ⚠️ GEURSA: {message}")

    def _active_section(
        self, soup: BeautifulSoup
    ) -> tuple[Optional[List[Tag]], Optional[SectionContext]]:
        heading = self._find_active_heading(soup)
        if heading is None:
            self._diagnose(
                "active heading 'Convocatorias en vigor' not found; unsupported layout."
            )
            return None, None

        context = self._section_context(soup, heading)
        cards = self._cards_in_context(soup, context)
        if not cards:
            self._diagnose(
                "active section 'Convocatorias en vigor' is supported but empty: "
                "no .x-acc-item cards found."
            )
        return cards, context

    def _build_record(
        self,
        card: Tag,
        card_number: int,
        soup: BeautifulSoup,
        section_context: SectionContext,
    ) -> Optional[GeursaRecord]:
        title_element = self._find_owned_descendant(card, self.TITLE_SELECTOR)
        title = self._normalise(title_element.get_text(" ", strip=True)) if title_element else ""
        if not title:
            self._diagnose(
                f"card {card_number} has no title in .x-acc-header-text; skipped."
            )
            return None

        content = self._controlled_content(card, soup, section_context)
        if content is None:
            has_controls = any(
                button.get("aria-controls", "").strip()
                for button in self._owned_descendants(card, "[aria-controls]")
            )
            if has_controls:
                self._diagnose(
                    f"card {card_number} ({title}) has no valid .x-acc-content panel "
                    "within the active section; retaining title-only metadata."
                )
            else:
                self._diagnose(
                    f"card {card_number} ({title}) has no .x-acc-content panel; "
                    "retaining title-only metadata."
                )
        description, attachment_captions = self._extract_body_text(content)
        return {
            "title": title,
            "description": description,
            "deadline_text": description,
            "attachment_captions": attachment_captions,
            "url": self._extract_bases_url(card, content),
        }

    @staticmethod
    def _deduplicate_records(records: Iterable[GeursaRecord]) -> List[GeursaRecord]:
        unique_records: List[GeursaRecord] = []
        seen_records = set()
        for record in records:
            record_key = (
                record["title"],
                record["description"],
                record["deadline_text"],
                record["url"],
            )
            if record_key in seen_records:
                continue
            seen_records.add(record_key)
            unique_records.append(record)
        return unique_records

    def parse_list(
        self, list_html: str, target_date: Optional[date] = None
    ) -> List[GeursaRecord]:
        """Extract every card under the active section, ignoring target_date."""
        del target_date
        soup = BeautifulSoup(list_html, "html.parser")
        cards, section_context = self._active_section(soup)
        if cards is None or section_context is None:
            return []

        records: List[GeursaRecord] = []
        for card_number, card in enumerate(cards, start=1):
            record = self._build_record(card, card_number, soup, section_context)
            if record is not None:
                records.append(record)
        return self._deduplicate_records(records)

    def parse_detail(self, detail_html: str) -> str:
        """Extract text for interface compatibility; list parsing never calls it."""
        soup = BeautifulSoup(detail_html, "html.parser")
        container = soup.find("body") or soup
        return clean_text(container.get_text(separator="\n"), lowercase=False)

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
        """Parse one BOPage per active GEURSA card.

        ``target_date`` is accepted for the shared interface but intentionally
        does not alter the live section-based selection rule.
        """
        list_html = self._read_source(source)
        records = self.parse_list(list_html, target_date=target_date)
        pages: List[BOPage] = []

        for page_number, record in enumerate(records, start=1):
            text = clean_text(
                " ".join(
                    part
                    for part in (record["title"], record["description"])
                    if part
                ),
                lowercase=False,
            )
            pages.append(
                BOPage(
                    page_number=page_number,
                    text=text,
                    section=self.ACTIVE_SECTION,
                    detected_organism="GEURSA",
                    source="GEURSA",
                    url=record["url"],
                )
            )
        return pages
