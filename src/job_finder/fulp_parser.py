"""Pure HTML parsing and bounded online orchestration for FULP offers."""

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional, Union
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Comment, Tag

from job_finder.fulp_fetcher import (
    FulpBudgetExceeded,
    FulpFetchError,
    FulpFetcher,
)
from job_finder.interfaces import BOPage, BaseParser, BaseWebBoardParser
from job_finder.text_cleaner import clean_text


class FulpParseError(ValueError):
    """The supplied HTML is not a supported FULP response."""


class FulpIdentityError(FulpParseError):
    """A FULP record contains conflicting or insufficient public identities."""


@dataclass
class FulpRecord:
    """Evidence retained from one FULP listing or detail record."""

    offer_id: str
    title: str
    url: str
    offer_type: str = ""
    type_normalized: str = "UNKNOWN"
    employer_raw: str = ""
    employer: str = "Empresa no identificada"
    location_raw: str = ""
    publication_date: Optional[date] = None
    publication_raw: str = ""
    contract: str = ""
    working_time: str = ""
    vacancies: str = ""
    summary_values: list[str] = field(default_factory=list)
    description: str = ""
    tasks: str = ""
    profile: str = ""
    requirements: str = ""
    deadline_date: Optional[date] = None
    deadline_raw: str = ""
    availability_status: str = "UNKNOWN"
    availability_evidence: str = ""
    listing_description: str = ""

    @property
    def id(self) -> str:
        return self.offer_id

    @property
    def location(self) -> str:
        return self.location_raw

    @property
    def canonical_url(self) -> str:
        return self.url

    def __getitem__(self, key: str) -> Any:
        """Offer a small mapping-compatible surface for web-board callers."""
        return getattr(self, key)


class FulpParser(BaseParser, BaseWebBoardParser):
    """Parse the observed public FULP list/detail HTML contract."""

    LIST_URL = FulpFetcher.LIST_URL
    SOURCE = "FULP"
    ORGANISM = "FULP"
    PANEL_SELECTOR = ".panel_ofertas"
    CARD_SELECTOR = ".row.oferta"
    DETAIL_ROOT_SELECTOR = ".Content-Oferta"
    TITLE_SELECTOR = "h2.titulo"
    TYPE_SELECTOR = "h5"
    SUMMARY_SELECTOR = ".container-details"
    SECTION_SELECTORS = {
        "description": ".Descripcion",
        "tasks": ".Tareas",
        "profile": ".Perfil",
        "requirements": ".Requisitos",
    }
    LISTING_TOTAL_PATTERN = re.compile(
        r"(?<!\d)(?P<count>\d+)\s+RESULTADOS\s+ENCONTRADOS\b",
        re.IGNORECASE,
    )
    DATE_PATTERN = re.compile(
        r"(?<!\d)(?:(?P<day>\d{1,2})\s*[/-]\s*(?P<month>\d{1,2})\s*[/-]\s*(?P<year>\d{4})"
        r"|(?P<word_day>\d{1,2})\s+de\s+(?P<word_month>[a-záéíóúüñ]+)\s+de\s+(?P<word_year>\d{4})"
        r"|(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2}))(?!\d)",
        re.IGNORECASE,
    )
    DATE_LIKE_PATTERN = re.compile(
        r"(?<!\d)\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?(?!\d)"
        r"|(?<!\d)\d{1,2}\s+de\s+[a-záéíóúüñ]+\s+de\s+\d{2,4}(?!\d)",
        re.IGNORECASE,
    )
    MONTHS = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "setiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }
    APPLICATION_CONTEXT = re.compile(
        r"(?:plazo|solicitudes?|candidaturas?|inscripci[oó]n|inscribirse|"
        r"presentaci[oó]n|application|deadline|fecha\s+l[ií]mite)",
        re.IGNORECASE,
    )
    DEADLINE_CONTEXT = re.compile(
        r"(?:hasta|finaliza|finaliz[oó]|termina|termin[oó]|vence|venci[oó]|"
        r"cierra|cerr[oó]|l[ií]mite|antes\s+del?|deadline|"
        r"fecha\s+l[ií]mite|cierre)",
        re.IGNORECASE,
    )
    NON_APPLICATION_CONTEXT = re.compile(
        r"(?:plazo\s+de\s+(?:ejecuci[oó]n|entrega|duraci[oó]n|realizaci[oó]n)|"
        r"fecha\s+l[ií]mite\s+(?:para\s+)?(?:entregar|ejecutar)|"
        r"(?:duraci[oó]n|cronograma)\s+(?:del?|de\s+la)\s+"
        r"(?:proyecto|contrato))",
        re.IGNORECASE,
    )
    NEGATED_DEADLINE_CONTEXT = re.compile(
        r"\b(?:sin|no|nunca)\s+(?:se\s+)?(?:establec(?:e|ido)|existe|hay)?\s*"
        r"(?:un\s+|ning[uú]n\s+)?(?:plazo|fecha\s+l[ií]mite|deadline|cierre)\b",
        re.IGNORECASE,
    )
    NEGATED_STATUS_CONTEXT = re.compile(
        r"\b(?:(?:a[uú]n|todav[ií]a)\s+)?(?:no|nunca)\s+"
        r"(?:(?:est[aá]|esta|se\s+(?:encuentra|ha)|ha(?:\s+sido)?|fue|"
        r"ser[aá]|deber[ií]a\s+estar)\s+)?$",
        re.IGNORECASE,
    )
    APPLICATION_ACTION_PATTERN = re.compile(
        r"\b(?:inscrib(?:irme|irse|ete|irte)|aplicar|apply|compartir|share|"
        r"imprimir|print|contactar|ayuda|help)\b",
        re.IGNORECASE,
    )
    PUBLICATION_CONTEXT = re.compile(
        r"(?:publicad[oa]|publicaci[oó]n|fecha\s+de\s+publicaci[oó]n)",
        re.IGNORECASE,
    )
    CLOSED_PATTERN = re.compile(
        r"\b(?:cerrad[oa]s?|cancelad[oa]s?|anulad[oa]s?|finalizad[oa]s?)\b",
        re.IGNORECASE,
    )
    CLOSED_STATUS_CONTEXT = re.compile(
        r"\b(?:oferta(?:\s+de\s+empleo)?|proceso(?:\s+de\s+selecci[oó]n)?|"
        r"convocatoria|plazo(?:\s+de\s+(?:solicitud(?:es)?|inscripci[oó]n|"
        r"presentaci[oó]n))?|inscripci[oó]n(?:es)?)\b",
        re.IGNORECASE,
    )
    CLOSED_STATUS_WORD_PATTERN = re.compile(
        r"\b(?:cerrad[oa]s?|cancelad[oa]s?|anulad[oa]s?|finalizad[oa]s?)\b",
        re.IGNORECASE,
    )
    LOCATION_PATTERN = re.compile(
        r"\b(?:las\s+palmas(?:\s+de\s+gran\s+canaria)?|gran\s+canaria|"
        r"santa\s+cruz\s+de\s+tenerife|tenerife|lanzarote|fuerteventura|"
        r"la\s+palma|canarias)\b",
        re.IGNORECASE,
    )
    VACANCY_PATTERN = re.compile(
        r"\b(?:plazas?|vacantes?|puestos?)\s*:?\s*(\d+)\b", re.IGNORECASE
    )
    DETAIL_TYPE_PATTERNS = (
        ("INSERta_UNIVERSITARIO", re.compile(r"\bprograma\s+inserta\s+universitari", re.IGNORECASE)),
        ("INSERta_FP_SUPERIOR", re.compile(r"\bprograma\s+inserta\s+fp\s+superior\b", re.IGNORECASE)),
        ("UNIVERSITY_INTERNSHIP", re.compile(r"\bpr[aá]cticas?\s+universitari", re.IGNORECASE)),
        ("ORDINARY_EMPLOYMENT", re.compile(r"\boferta\s+(?:de\s+)?empleo\b", re.IGNORECASE)),
    )
    IGNORED_TAGS = frozenset(
        {"script", "style", "noscript", "template", "button", "input", "select", "option", "textarea"}
    )
    IGNORED_CLASS_PATTERN = re.compile(
        r"(?:share|compart|print|imprim|inscrib|aplic|application|apply|"
        r"contact|cookie|social|privacy|polit|footer|help|ayuda)",
        re.IGNORECASE,
    )
    CONTINUATION_SELECTOR = (
        "a[rel~='next'], a[aria-label*='iguiente' i], a[aria-label*='next' i], "
        ".pagination a[href], .pager a[href], a[href*='pagina' i], a[href*='page=' i]"
    )

    def __init__(self, fetcher: Optional[object] = None, list_url: str = LIST_URL) -> None:
        self.fetcher = fetcher
        self.list_url = FulpFetcher.normalise_public_url(list_url, expected="list")
        self.diagnostics: list[str] = []
        self.last_discovery: dict[str, Any] = {}
        self.last_scan: dict[str, Any] = {}

    @staticmethod
    def _normalise(value: object) -> str:
        text = " ".join(str(value or "").split())
        return re.sub(r"\s+([,.;:!?])", r"\1", text).strip()

    @staticmethod
    def _strip_accents(value: str) -> str:
        decomposed = unicodedata.normalize("NFD", value)
        return "".join(
            character
            for character in decomposed
            if unicodedata.category(character) != "Mn"
        )

    def _diagnose(self, message: str) -> None:
        self.diagnostics.append(message)
        print(f"      ⚠️ FULP: {message}")

    @classmethod
    def _is_card(cls, element: object) -> bool:
        return isinstance(element, Tag) and "oferta" in (element.get("class") or []) and "row" in (
            element.get("class") or []
        )

    @classmethod
    def _nearest_card(cls, element: object) -> Optional[Tag]:
        current = element if isinstance(element, Tag) else None
        while isinstance(current, Tag):
            if cls._is_card(current):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _is_root(cls, element: object) -> bool:
        return isinstance(element, Tag) and cls.DETAIL_ROOT_SELECTOR[1:] in (element.get("class") or [])

    @classmethod
    def _nearest_root(cls, element: object) -> Optional[Tag]:
        current = element if isinstance(element, Tag) else None
        while isinstance(current, Tag):
            if cls._is_root(current):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _owned_descendants(cls, owner: Tag, selector: str, kind: str) -> list[Tag]:
        owned: list[Tag] = []
        for element in owner.select(selector):
            nearest = cls._nearest_card(element) if kind == "card" else cls._nearest_root(element)
            if nearest is not owner:
                continue
            if kind == "card" and any(
                cls._is_card(descendant) and cls._nearest_card(descendant) is not owner
                for descendant in element.find_all(True)
            ):
                continue
            owned.append(element)
        return owned

    @classmethod
    def _is_application_control(cls, element: Tag) -> bool:
        if element.name in {"button", "input"}:
            return True
        if element.name != "a":
            return False
        label = cls._normalise(element.get_text(" ", strip=True))
        href = str(element.get("href", ""))
        try:
            FulpFetcher.normalise_public_url(
                urljoin(FulpFetcher.BASE_URL, href),
                expected="detail",
            )
        except (TypeError, ValueError):
            pass
        else:
            return False
        attributes = " ".join(
            (
                href,
                str(element.get("aria-label", "")),
                str(element.get("title", "")),
                str(element.get("id", "")),
                " ".join(element.get("class", []) or []),
            )
        )
        return bool(
            cls.IGNORED_CLASS_PATTERN.search(attributes)
            or cls.APPLICATION_ACTION_PATTERN.search(label)
        )

    @classmethod
    def _ignored_text_node(cls, node: object) -> bool:
        if isinstance(node, Comment):
            return True
        parent = node.parent if isinstance(node, (Comment,)) else getattr(node, "parent", None)
        current = parent if isinstance(parent, Tag) else None
        while isinstance(current, Tag):
            if current.name in cls.IGNORED_TAGS:
                return True
            if cls._is_application_control(current):
                return True
            marker = f"{current.get('id', '')} {' '.join(current.get('class', []) or [])}"
            if cls.IGNORED_CLASS_PATTERN.search(marker):
                return True
            current = current.parent if isinstance(current.parent, Tag) else None
        return False

    @classmethod
    def _owned_text(cls, element: Tag, owner: Tag, kind: str) -> str:
        values: list[str] = []
        for text_node in element.find_all(string=True):
            if cls._ignored_text_node(text_node):
                continue
            parent = text_node.parent
            if not isinstance(parent, Tag):
                continue
            nearest = cls._nearest_card(parent) if kind == "card" else cls._nearest_root(parent)
            if nearest is owner:
                value = str(text_node).strip()
                if value:
                    values.append(value)
        return cls._normalise(" ".join(values))

    @classmethod
    def _top_level_cards(cls, panel: Tag) -> list[Tag]:
        return [
            card
            for card in panel.select(cls.CARD_SELECTOR)
            if not any(cls._is_card(parent) for parent in card.parents)
        ]

    @classmethod
    def _top_level_roots(cls, soup: BeautifulSoup) -> list[Tag]:
        roots = soup.select(cls.DETAIL_ROOT_SELECTOR)
        return [
            root
            for root in roots
            if not any(
                other is not root
                and any(parent is other for parent in root.parents)
                for other in roots
            )
        ]

    @classmethod
    def _listing_panels(cls, soup: BeautifulSoup) -> list[Tag]:
        return [panel for panel in soup.select(cls.PANEL_SELECTOR) if isinstance(panel, Tag)]

    @classmethod
    def _listing_total_values(cls, soup: BeautifulSoup) -> tuple[list[int], bool]:
        values: list[int] = []
        malformed = False
        for heading in soup.find_all(("h4", "h5", "h6")):
            text = cls._normalise(heading.get_text(" ", strip=True))
            match = cls.LISTING_TOTAL_PATTERN.search(text)
            if match:
                values.append(int(match.group("count")))
            elif "RESULTADOS" in cls._strip_accents(text).upper():
                malformed = True
        return values, malformed

    @classmethod
    def has_supported_list_structure(cls, list_html: str) -> bool:
        soup = BeautifulSoup(list_html, "html.parser")
        panels = cls._listing_panels(soup)
        if not panels:
            return False
        total_values, _ = cls._listing_total_values(soup)
        return any(cls._top_level_cards(panel) for panel in panels) or bool(total_values)

    @classmethod
    def has_supported_detail_structure(cls, detail_html: str) -> bool:
        soup = BeautifulSoup(detail_html, "html.parser")
        roots = cls._top_level_roots(soup)
        if len(roots) != 1:
            return False
        root = roots[0]
        titles = cls._owned_descendants(root, cls.TITLE_SELECTOR, "root")
        if not titles or not cls._owned_text(titles[0], root, "root"):
            return False
        return bool(cls._detail_identity_urls(soup, root))

    @classmethod
    def has_supported_structure(cls, html: str) -> bool:
        return cls.has_supported_detail_structure(html) or cls.has_supported_list_structure(html)

    @classmethod
    def _detail_identity_urls(cls, soup: BeautifulSoup, root: Tag) -> list[tuple[str, str]]:
        """Return valid canonical/og identities without following HTML links."""
        candidates: list[tuple[str, str]] = []
        head = soup.head if isinstance(soup.head, Tag) else None
        if head is not None:
            links = head.find_all("link", href=True)
            metas = head.find_all("meta")
        else:
            links = [
                link
                for link in soup.find_all("link", href=True)
                if cls._nearest_root(link) is root
            ]
            metas = [
                meta
                for meta in soup.find_all("meta")
                if cls._nearest_root(meta) is root
            ]
        for link in links:
            rel = {str(value).casefold() for value in (link.get("rel") or [])}
            if "canonical" not in rel:
                continue
            try:
                candidates.append(
                    ("canonical", FulpFetcher.normalise_public_url(link["href"], expected="detail"))
                )
            except (TypeError, ValueError):
                continue
        for meta in metas:
            property_name = str(meta.get("property", meta.get("name", ""))).casefold()
            if property_name != "og:url" or not meta.get("content"):
                continue
            try:
                candidates.append(
                    ("og:url", FulpFetcher.normalise_public_url(meta["content"], expected="detail"))
                )
            except (TypeError, ValueError):
                continue
        # Some reduced snapshots place canonical metadata inside the owning
        # root. It is accepted only when it belongs to this root.
        for link in cls._owned_descendants(root, "link[rel~='canonical']", "root"):
            try:
                candidates.append(
                    ("canonical", FulpFetcher.normalise_public_url(link["href"], expected="detail"))
                )
            except (TypeError, ValueError):
                continue
        return list(dict.fromkeys(candidates))

    @classmethod
    def _extract_public_id(cls, url: str) -> str:
        return FulpFetcher.detail_id(url)

    @classmethod
    def _normalise_type(cls, value: str) -> str:
        for normalized, pattern in cls.DETAIL_TYPE_PATTERNS:
            if pattern.search(value):
                return normalized.upper()
        return "UNKNOWN"

    @classmethod
    def _type_equivalence_key(cls, value: str) -> str:
        normalized = cls._normalise_type(value)
        return normalized if normalized != "UNKNOWN" else cls._strip_accents(value).casefold()

    @classmethod
    def _parse_date_match(cls, match: re.Match[str]) -> Optional[date]:
        try:
            if match.group("day"):
                return date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            if match.group("word_day"):
                month = cls.MONTHS.get(cls._strip_accents(match.group("word_month")).casefold())
                if month is None:
                    return None
                return date(int(match.group("word_year")), month, int(match.group("word_day")))
            return date(
                int(match.group("iso_year")),
                int(match.group("iso_month")),
                int(match.group("iso_day")),
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _first_date(cls, value: str) -> Optional[date]:
        for match in cls.DATE_PATTERN.finditer(value):
            parsed = cls._parse_date_match(match)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _clause_bounds(text: str, position: int) -> tuple[int, int]:
        boundaries = ".;!?\n"
        start = max((text.rfind(boundary, 0, position) for boundary in boundaries), default=-1) + 1
        ends = [text.find(boundary, position) for boundary in boundaries]
        ends = [end for end in ends if end >= 0]
        return start, min(ends, default=len(text))

    @classmethod
    def _date_clause(cls, text: str, match: re.Match[str]) -> str:
        start, end = cls._clause_bounds(text, match.start())
        return cls._normalise(text[start:end])

    @classmethod
    def _is_publication_date(cls, text: str, match: re.Match[str]) -> bool:
        prefix = text[max(0, match.start() - 70) : match.start()]
        return re.search(
            r"(?:publicad[oa]|publicaci[oó]n|fecha\s+de\s+publicaci[oó]n)\s*:\s*$",
            prefix,
            re.IGNORECASE,
        ) is not None

    @classmethod
    def _is_closed_offer_status(cls, text: str, match: re.Match[str]) -> bool:
        start, end = cls._clause_bounds(text, match.start())
        clause = text[start:end]
        status_offset = match.start() - start
        before_status = clause[:status_offset]
        if re.search(
            r"\b(?:no|nunca)\s+(?:(?:est[aá]|esta|se\s+(?:encuentra|ha)|"
            r"ha(?:\s+sido)?|fue|ser[aá]|deber[ií]a\s+estar)\s+)?$",
            before_status,
            re.IGNORECASE,
        ):
            return False
        if cls.NON_APPLICATION_CONTEXT.search(clause):
            return False
        if cls.CLOSED_STATUS_CONTEXT.search(clause) is not None:
            return True
        return re.search(
            r"\b(?:solicitudes?|candidaturas?|inscripciones?)\s+"
            r"(?:(?:est[aá]n?|han\s+sido|fueron)\s+)?$",
            before_status,
            re.IGNORECASE,
        ) is not None

    @classmethod
    def _availability_text(cls, values: Iterable[str]) -> str:
        """Join semantic fields without making their words one clause."""
        return "\n".join(
            cls._normalise(value)
            for value in values
            if cls._normalise(value)
        )

    @classmethod
    def _availability(
        cls,
        text: str,
        reference_date: date,
    ) -> tuple[str, Optional[date], str, str]:
        # Newlines represent owned HTML fields.  Collapsing them would make a
        # status word in a qualification appear to describe the offer type.
        normalized = re.sub(r"[^\S\n]+", " ", str(text or ""))
        normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized).strip()
        closed_match = None
        for candidate in cls.CLOSED_PATTERN.finditer(normalized):
            if not cls._is_closed_offer_status(normalized, candidate):
                continue
            closed_match = candidate
            break
        if closed_match:
            evidence = cls._normalise(
                normalized[max(0, closed_match.start() - 80) : closed_match.end() + 80]
            )
            return "CLOSED", None, "", evidence

        deadline_dates: list[tuple[date, str]] = []
        invalid_deadline = False
        for match in cls.DATE_PATTERN.finditer(normalized):
            clause = cls._date_clause(normalized, match)
            if cls._is_publication_date(normalized, match):
                continue
            if cls.NON_APPLICATION_CONTEXT.search(clause):
                continue
            if cls.NEGATED_DEADLINE_CONTEXT.search(clause):
                invalid_deadline = True
                continue
            app_context = cls.APPLICATION_CONTEXT.search(clause)
            interval_context = re.search(
                r"\b(?:del|desde|entre)\b[\s\S]*\b(?:hasta|al)\b",
                clause,
                re.IGNORECASE,
            )
            deadline_context = cls.DEADLINE_CONTEXT.search(clause) or interval_context
            if not app_context or not deadline_context:
                continue
            clause_start, _ = cls._clause_bounds(normalized, match.start())
            before_date = normalized[clause_start : match.start()]
            after_date = normalized[match.end() : cls._clause_bounds(normalized, match.start())[1]]
            is_range_start = (
                re.search(r"\b(?:del|desde|entre)\s*$", before_date, re.IGNORECASE)
                and re.search(r"\b(?:hasta|al)\b", after_date, re.IGNORECASE)
            )
            if is_range_start:
                continue
            parsed = cls._parse_date_match(match)
            if parsed is None:
                invalid_deadline = True
                continue
            deadline_dates.append((parsed, clause))

        if not deadline_dates and not invalid_deadline:
            for match in cls.DATE_LIKE_PATTERN.finditer(normalized):
                clause = cls._date_clause(normalized, match)
                if cls._is_publication_date(normalized, match):
                    continue
                if cls.NON_APPLICATION_CONTEXT.search(clause):
                    continue
                if (
                    cls.APPLICATION_CONTEXT.search(clause)
                    and (
                        cls.DEADLINE_CONTEXT.search(clause)
                        or re.search(
                            r"\b(?:del|desde|entre)\b[\s\S]*\b(?:hasta|al)\b",
                            clause,
                            re.IGNORECASE,
                        )
                    )
                ):
                    invalid_deadline = True
                    break

        if deadline_dates and invalid_deadline:
            return (
                "UNKNOWN",
                None,
                "",
                "Application-deadline evidence included both valid and invalid or "
                "unsupported dates.",
            )
        if deadline_dates:
            unique_dates = {item[0] for item in deadline_dates}
            if len(unique_dates) > 1:
                return (
                    "UNKNOWN",
                    None,
                    "",
                    "Conflicting application-deadline dates were found: "
                    + "; ".join(item[1] for item in deadline_dates),
                )
            deadline, raw_context = deadline_dates[0]
            if deadline < reference_date:
                return "EXPIRED", deadline, raw_context, raw_context
            return "OPEN", deadline, raw_context, raw_context

        if invalid_deadline:
            return (
                "UNKNOWN",
                None,
                "",
                "An application deadline was expressed with an invalid or unsupported date.",
            )
        return "UNKNOWN", None, "", ""

    @classmethod
    def _recognised_location(cls, values: Iterable[str]) -> str:
        for value in values:
            match = cls.LOCATION_PATTERN.fullmatch(cls._normalise(value))
            if match:
                return cls._normalise(match.group(0))
        return ""

    @classmethod
    def _label_value(cls, element: Tag, owner: Tag, kind: str) -> tuple[str, str]:
        """Extract an explicitly labelled summary value, never by list index."""
        full = cls._owned_text(element, owner, kind)
        if not full:
            return "", ""
        label = ""
        strong = element.find(("strong", "b", "label", "dt"))
        if isinstance(strong, Tag):
            label = cls._normalise(strong.get_text(" ", strip=True)).rstrip(":")
        else:
            match = re.match(r"^([^:]{2,50}):\s*(.+)$", full)
            if match:
                label = cls._normalise(match.group(1))
        if not label:
            return "", ""
        label_key = cls._strip_accents(label).casefold()
        value = full
        if ":" in value:
            value = value.split(":", 1)[1].strip()
        elif isinstance(strong, Tag):
            strong_text = cls._normalise(strong.get_text(" ", strip=True)).rstrip(":")
            value = value[len(strong_text) :].lstrip(" :")
        return label_key, cls._normalise(value)

    @classmethod
    def _detail_root(cls, soup: BeautifulSoup) -> Tag:
        roots = cls._top_level_roots(soup)
        if not roots:
            raise FulpParseError("FULP detail root .Content-Oferta is missing")
        if len(roots) > 1:
            raise FulpParseError("FULP detail contains multiple top-level .Content-Oferta roots")
        return roots[0]

    @classmethod
    def _owned_section_text(cls, root: Tag, selector: str) -> str:
        candidates = cls._owned_descendants(root, selector, "root")
        sections = [
            section
            for section in candidates
            if not any(
                other is not section
                and any(parent is other for parent in section.parents)
                for other in candidates
            )
        ]
        values = []
        for section in sections:
            text = cls._owned_text(section, root, "root")
            if text and text not in values:
                values.append(text)
        return cls._normalise(" ".join(values))

    @classmethod
    def _summary_values(cls, root: Tag) -> list[str]:
        summaries = cls._owned_descendants(root, cls.SUMMARY_SELECTOR, "root")
        if not summaries:
            return []
        summary = summaries[0]
        values: list[str] = []
        for item in summary.find_all("li"):
            if any(
                isinstance(parent, Tag) and parent.name == "li" and parent is not summary
                for parent in item.parents
            ):
                continue
            value = cls._owned_text(item, root, "root")
            if value and value not in values:
                values.append(value)
        return values

    @classmethod
    def _metadata_from_summary(
        cls,
        root: Tag,
        summary_values: list[str],
    ) -> dict[str, str]:
        metadata = {
            "employer": "",
            "location": "",
            "contract": "",
            "working_time": "",
            "vacancies": "",
            "publication": "",
        }
        summaries = cls._owned_descendants(root, cls.SUMMARY_SELECTOR, "root")
        if summaries:
            for item in summaries[0].find_all("li"):
                if any(
                    isinstance(parent, Tag) and parent.name == "li" and parent is not summaries[0]
                    for parent in item.parents
                ):
                    continue
                label, value = cls._label_value(item, root, "root")
                if not value:
                    continue
                if label in {"empresa", "entidad", "company", "empleador", "empleadora"}:
                    metadata["employer"] = value
                elif label in {"ubicacion", "localizacion", "localidad", "location", "lugar", "provincia"}:
                    metadata["location"] = value
                elif "contrato" in label or label == "contract":
                    metadata["contract"] = value
                elif "jornada" in label or "horario" in label or label in {"modalidad", "work time"}:
                    metadata["working_time"] = value
                elif label in {"plazas", "vacantes", "puestos", "vacancies"}:
                    metadata["vacancies"] = value
                elif "public" in label or "publication" in label:
                    metadata["publication"] = value

        selector_map = {
            "employer": ".empresa, .employer, [data-field='empresa']",
            "location": ".ubicacion, .localidad, .location, [data-field='ubicacion']",
            "contract": ".contrato, [data-field='contrato']",
            "working_time": ".jornada, .horario, [data-field='jornada']",
            "vacancies": ".plazas, .vacantes, [data-field='vacantes']",
            "publication": ".fecha, .publicacion, [data-field='publicacion']",
        }
        for key, selector in selector_map.items():
            if metadata[key]:
                continue
            for element in cls._owned_descendants(root, selector, "root"):
                value = cls._owned_text(element, root, "root")
                if value:
                    metadata[key] = value
                    break

        if not metadata["location"]:
            metadata["location"] = cls._recognised_location(summary_values)
        return metadata

    @classmethod
    def _listing_badges(cls, card: Tag) -> list[str]:
        values: list[str] = []
        for badge in cls._owned_descendants(card, "span.etiqueta", "card"):
            text = cls._owned_text(badge, card, "card")
            if text and text not in values:
                values.append(text)
        return values

    @classmethod
    def _listing_type_badges(cls, card: Tag) -> list[str]:
        values: list[str] = []
        for badge in cls._owned_descendants(card, "span.etiqueta.tipo", "card"):
            text = cls._owned_text(badge, card, "card")
            if text and text not in values:
                values.append(text)
        return values

    @classmethod
    def _detail_type(cls, root: Tag) -> str:
        values: list[str] = []
        for heading in cls._owned_descendants(root, cls.TYPE_SELECTOR, "root"):
            value = cls._owned_text(heading, root, "root")
            if value and value not in values:
                values.append(value)
        if not values:
            return ""
        keys = {cls._type_equivalence_key(value) for value in values}
        if len(keys) > 1:
            raise FulpParseError(
                "FULP detail contains conflicting owned offer types: " + "; ".join(values)
            )
        return values[0]

    @classmethod
    def _listing_type(
        cls,
        badges: list[str],
        type_badges: Optional[list[str]] = None,
    ) -> tuple[str, str, bool]:
        type_values = list(type_badges if type_badges is not None else badges)
        if not type_values:
            return "", "UNKNOWN", False
        keys = {cls._type_equivalence_key(value) for value in type_values}
        return type_values[0], cls._normalise_type(type_values[0]), len(keys) > 1

    @classmethod
    def _candidate_listing_urls(cls, card: Tag) -> list[str]:
        anchors: list[Tag] = []
        parent = card.parent if isinstance(card.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "a" and parent.get("href"):
            anchors.append(parent)
        anchors.extend(cls._owned_descendants(card, "a[href]", "card"))
        urls: list[str] = []
        for anchor in anchors:
            try:
                url = FulpFetcher.normalise_public_url(
                    urljoin(FulpFetcher.BASE_URL, str(anchor.get("href", ""))),
                    expected="detail",
                )
            except (TypeError, ValueError):
                continue
            if url not in urls:
                urls.append(url)
        return urls

    def _build_listing_record(
        self,
        card: Tag,
        card_number: int,
        reference_date: date,
    ) -> Optional[FulpRecord]:
        urls = self._candidate_listing_urls(card)
        if not urls:
            self._diagnose(f"listing card {card_number} has no valid public detail URL; skipped.")
            return None
        ids = {self._extract_public_id(url) for url in urls}
        if len(ids) != 1:
            self._diagnose(
                f"listing card {card_number} has conflicting numeric identities {sorted(ids)}; skipped."
            )
            return None
        offer_id = next(iter(ids))

        title_elements = self._owned_descendants(card, "h3", "card")
        title = self._owned_text(title_elements[0], card, "card") if title_elements else ""
        if not title:
            self._diagnose(f"listing card {card_number} has no owned h3 title; skipped.")
            return None

        badges = self._listing_badges(card)
        offer_type, type_normalized, type_conflict = self._listing_type(
            badges,
            self._listing_type_badges(card),
        )
        if type_conflict:
            self._diagnose(
                f"listing card {card_number} ({title}) has conflicting owned offer types; skipped."
            )
            return None

        date_elements = self._owned_descendants(card, "p.fecha", "card")
        publication_raw = self._owned_text(date_elements[0], card, "card") if date_elements else ""
        publication_date = self._first_date(publication_raw)
        if publication_raw and publication_date is None:
            self._diagnose(
                f"listing card {card_number} ({title}) has unsupported publication date wording; retained as metadata."
            )

        employer_elements = self._owned_descendants(card, "p.empresa", "card")
        employer_raw = (
            self._owned_text(employer_elements[0], card, "card") if employer_elements else ""
        )
        description_elements = self._owned_descendants(card, "p.descripcion", "card")
        listing_description = self._normalise(
            " ".join(self._owned_text(element, card, "card") for element in description_elements)
        )
        location_elements = self._owned_descendants(
            card, ".ubicacion, .localidad, .location", "card"
        )
        location = (
            self._owned_text(location_elements[0], card, "card") if location_elements else ""
        )
        contract = next(
            (value for value in badges if re.search(r"\bcontrat", value, re.IGNORECASE)), ""
        )
        working_time = next(
            (
                value
                for value in badges
                if re.search(r"\b(?:jornada|tiempo|media jornada|completa)\b", value, re.IGNORECASE)
            ),
            "",
        )
        vacancies_match = self.VACANCY_PATTERN.search(" ".join(badges) + " " + listing_description)
        vacancies = vacancies_match.group(0) if vacancies_match else ""

        owned_text = self._availability_text(
            (
                title,
                offer_type,
                f"Fecha de publicación: {publication_raw}" if publication_raw else "",
                employer_raw,
                location,
                contract,
                working_time,
                vacancies,
                listing_description,
            )
        )
        status, deadline_date, deadline_raw, evidence = self._availability(
            owned_text, reference_date
        )
        if status in {"CLOSED", "EXPIRED"}:
            self._diagnose(
                f"listing card {card_number} ({title}) is {status.casefold()}; "
                "it will not be fetched for details."
            )
        if evidence and status == "UNKNOWN":
            self._diagnose(f"listing card {card_number} ({title}) availability is uncertain: {evidence}")

        return FulpRecord(
            offer_id=offer_id,
            title=title,
            url=urls[0],
            offer_type=offer_type,
            type_normalized=type_normalized,
            employer_raw=employer_raw,
            employer=employer_raw or "Empresa no identificada",
            location_raw=location,
            publication_date=publication_date,
            publication_raw=publication_raw,
            contract=contract,
            working_time=working_time,
            vacancies=vacancies,
            listing_description=listing_description,
            deadline_date=deadline_date,
            deadline_raw=deadline_raw,
            availability_status=status,
            availability_evidence=evidence,
        )

    def _continuation_evidence(self, soup: BeautifulSoup) -> list[str]:
        evidence: list[str] = []
        for element in soup.select(self.CONTINUATION_SELECTOR):
            text = self._normalise(element.get_text(" ", strip=True))
            href = self._normalise(element.get("href", ""))
            marker = text or href
            if marker and marker not in evidence:
                evidence.append(marker)
        return evidence

    def _parse_listing(
        self,
        list_html: str,
        reference_date: date,
    ) -> list[FulpRecord]:
        soup = BeautifulSoup(list_html, "html.parser")
        panels = self._listing_panels(soup)
        if not panels:
            self._diagnose("listing is not a supported FULP response: .panel_ofertas is missing.")
            self.last_discovery = {
                "supported": False,
                "state": "INCOMPLETE",
                "advertised_total": None,
                "discovered_unique_ids": 0,
            }
            return []

        total_values, malformed_total = self._listing_total_values(soup)
        advertised_total: Optional[int]
        if len(set(total_values)) == 1:
            advertised_total = total_values[0]
        elif len(set(total_values)) > 1:
            advertised_total = None
            self._diagnose(
                f"listing contains contradictory advertised totals: {sorted(set(total_values))}."
            )
        else:
            advertised_total = None
        if malformed_total:
            self._diagnose("listing advertised total is malformed or unsupported.")

        cards: list[Tag] = []
        for panel in panels:
            for card in self._top_level_cards(panel):
                if not any(existing is card for existing in cards):
                    cards.append(card)

        if not cards:
            if advertised_total == 0:
                self._diagnose("supported FULP listing is genuinely empty (advertised total 0).")
            else:
                self._diagnose("supported FULP listing has no owned offer cards.")

        raw_records: list[FulpRecord] = []
        malformed_records = 0
        for card_number, card in enumerate(cards, start=1):
            record = self._build_listing_record(card, card_number, reference_date)
            if record is None:
                malformed_records += 1
            else:
                raw_records.append(record)

        unique_by_id: dict[str, FulpRecord] = {}
        duplicate_records = 0
        for record in raw_records:
            if record.offer_id in unique_by_id:
                duplicate_records += 1
                self._diagnose(
                    f"duplicate listing identity {record.offer_id} ({record.title}) was "
                    "retained only in first-seen order."
                )
                continue
            unique_by_id[record.offer_id] = record

        unavailable_records = sum(
            record.availability_status in {"CLOSED", "EXPIRED"}
            for record in unique_by_id.values()
        )
        included_records = [
            record
            for record in unique_by_id.values()
            if record.availability_status not in {"CLOSED", "EXPIRED"}
        ]

        continuation = self._continuation_evidence(soup)
        if continuation:
            self._diagnose(
                "unsupported listing continuation evidence was present and was not followed: "
                + ", ".join(continuation)
            )

        state = "RECONCILED_FOR_RESPONSE"
        if advertised_total is None:
            state = "UNVERIFIED"
        if (
            malformed_total
            or malformed_records
            or duplicate_records
            or continuation
            or (advertised_total is not None and advertised_total != len(unique_by_id))
        ):
            state = "INCOMPLETE"
        if advertised_total is not None and advertised_total != len(unique_by_id):
            self._diagnose(
                "advertised total does not match discovered unique numeric IDs "
                f"({advertised_total} versus {len(unique_by_id)}); discovery is incomplete."
            )
        elif advertised_total is None:
            self._diagnose(
                "listing has no reconciled advertised total; discovery completeness is unverified."
            )
        elif not malformed_records and not continuation:
            self._diagnose(
                "advertised total matches discovered unique IDs for this response only; "
                "this is not a permanent completeness guarantee."
            )

        self.last_discovery = {
            "supported": True,
            "state": state,
            "advertised_total": advertised_total,
            "discovered_unique_ids": len(unique_by_id),
            "malformed_records": malformed_records,
            "duplicate_records": duplicate_records,
            "continuation_evidence": continuation,
            "unavailable_records": unavailable_records,
            "included_records": len(included_records),
            "reference_date": reference_date,
        }
        return included_records

    def parse_list(
        self,
        list_html: str,
        target_date: Optional[date] = None,
    ) -> list[FulpRecord]:
        """Parse one listing response without making any network request."""
        self.diagnostics.clear()
        reference_date = target_date or date.today()
        if target_date is not None:
            self._diagnose(
                "target_date is used only for explicit application deadlines; current FULP "
                "HTML cannot reconstruct historical availability."
            )
        return self._parse_listing(str(list_html), reference_date)

    def _parse_detail_record(
        self,
        detail_html: str,
        *,
        fallback_url: str = "",
        expected_id: str = "",
        response_url: str = "",
        require_snapshot_identity: bool = False,
        reference_date: Optional[date] = None,
    ) -> FulpRecord:
        soup = BeautifulSoup(detail_html, "html.parser")
        root = self._detail_root(soup)
        title_elements = self._owned_descendants(root, self.TITLE_SELECTOR, "root")
        title = self._owned_text(title_elements[0], root, "root") if title_elements else ""
        if not title:
            raise FulpParseError("FULP detail title h2.titulo is missing")

        identity_candidates = self._detail_identity_urls(soup, root)
        valid_identities: list[tuple[str, str, str]] = []
        for source, url in identity_candidates:
            valid_identities.append((source, url, self._extract_public_id(url)))
        identity_ids = {identity[2] for identity in valid_identities if identity[2]}
        if len(identity_ids) > 1:
            raise FulpIdentityError(
                f"FULP detail {title} contains conflicting canonical identities: "
                + ", ".join(sorted(identity_ids))
            )

        fallback_clean = ""
        if fallback_url:
            try:
                fallback_clean = FulpFetcher.normalise_public_url(
                    fallback_url,
                    expected="detail",
                )
            except ValueError as exc:
                raise FulpIdentityError(f"FULP detail fallback URL is invalid: {exc}") from exc
        response_clean = ""
        if response_url:
            try:
                response_clean = FulpFetcher.normalise_public_url(
                    response_url,
                    expected="detail",
                )
            except ValueError as exc:
                raise FulpIdentityError(f"FULP validated response URL is invalid: {exc}") from exc

        expected_clean = FulpFetcher._normalise_id(expected_id) if expected_id else ""
        fallback_id = self._extract_public_id(fallback_clean) if fallback_clean else ""
        response_id = self._extract_public_id(response_clean) if response_clean else ""
        if expected_clean and fallback_id and expected_clean != fallback_id:
            raise FulpIdentityError(
                f"FULP requested ID {expected_clean} disagrees with listing URL ID {fallback_id}"
            )
        for identity_id in identity_ids | ({response_id} if response_id else set()):
            if expected_clean and identity_id != expected_clean:
                raise FulpIdentityError(
                    f"FULP detail identity {identity_id} disagrees with requested ID {expected_clean}"
                )
            if fallback_id and identity_id != fallback_id:
                raise FulpIdentityError(
                    f"FULP detail identity {identity_id} disagrees with listing ID {fallback_id}"
                )

        canonical_url = next(
            (url for source, url, _ in valid_identities if source == "canonical"), ""
        )
        og_url = next((url for source, url, _ in valid_identities if source == "og:url"), "")
        if canonical_url:
            selected_url = canonical_url
        elif og_url:
            selected_url = og_url
        elif response_clean:
            selected_url = response_clean
        elif fallback_clean:
            selected_url = fallback_clean
        else:
            selected_url = ""
        if require_snapshot_identity and not (canonical_url or og_url):
            raise FulpIdentityError(
                f"FULP offline detail {title!r} has no reliable canonical or og:url identity"
            )
        if not selected_url:
            raise FulpIdentityError(f"FULP detail {title!r} has no reliable public identity")

        offer_type = self._detail_type(root)
        type_normalized = self._normalise_type(offer_type)
        summary_values = self._summary_values(root)
        metadata = self._metadata_from_summary(root, summary_values)
        description = self._owned_section_text(root, self.SECTION_SELECTORS["description"])
        tasks = self._owned_section_text(root, self.SECTION_SELECTORS["tasks"])
        profile = self._owned_section_text(root, self.SECTION_SELECTORS["profile"])
        requirements = self._owned_section_text(root, self.SECTION_SELECTORS["requirements"])

        publication_raw = metadata["publication"]
        publication_date = self._first_date(publication_raw) if publication_raw else None
        if publication_raw and publication_date is None:
            self._diagnose(
                f"detail {title} has unsupported publication metadata; retained as raw text."
            )
        reference = reference_date or date.today()
        availability_text = self._availability_text(
            (
                title,
                offer_type,
                *summary_values,
                description,
                tasks,
                profile,
                requirements,
            )
        )
        status, deadline_date, deadline_raw, evidence = self._availability(
            availability_text, reference
        )
        if evidence and status == "UNKNOWN":
            self._diagnose(f"detail {title} availability is uncertain: {evidence}")

        vacancy = metadata["vacancies"]
        if not vacancy:
            vacancy_match = self.VACANCY_PATTERN.search(" ".join(summary_values))
            vacancy = vacancy_match.group(0) if vacancy_match else ""

        return FulpRecord(
            offer_id=self._extract_public_id(selected_url),
            title=title,
            url=selected_url,
            offer_type=offer_type,
            type_normalized=type_normalized,
            employer_raw=metadata["employer"],
            employer=metadata["employer"] or "Empresa no identificada",
            location_raw=metadata["location"],
            publication_date=publication_date,
            publication_raw=publication_raw,
            contract=metadata["contract"],
            working_time=metadata["working_time"],
            vacancies=vacancy,
            summary_values=summary_values,
            description=description,
            tasks=tasks,
            profile=profile,
            requirements=requirements,
            deadline_date=deadline_date,
            deadline_raw=deadline_raw,
            availability_status=status,
            availability_evidence=evidence,
        )

    @classmethod
    def _record_text(cls, record: FulpRecord, *, listing_only: bool = False) -> str:
        parts: list[str] = [record.title]
        if record.offer_type:
            parts.append(f"Tipo de oferta: {record.offer_type}")
        if listing_only:
            parts.append(
                "EVIDENCIA LIMITADA: este registro procede únicamente del listado FULP; "
                "no se han recuperado los detalles de la oferta."
            )

        # Keep bounded, source-backed sections early for the AI window.  The
        # remainder is appended below, so truncating an optional long block
        # never discards extracted evidence or duplicates its prefix.
        deferred_sections: list[tuple[str, str]] = []
        for label, value, limit in (
            ("Requisitos", record.requirements, 600),
            ("Descripción de la oferta", record.description, 600),
            ("Tareas a realizar", record.tasks, 900),
            ("Perfil buscado", record.profile, 600),
        ):
            if not value:
                continue
            early, continuation = cls._allocate_section(value, limit)
            if early:
                parts.append(f"{label}: {early}")
            if continuation:
                deferred_sections.append((f"{label} (continuación)", continuation))

        if record.employer:
            parts.append(f"Empresa: {record.employer}")
        if record.location_raw:
            parts.append(f"Ubicación: {record.location_raw}")
        if record.contract:
            parts.append(f"Contrato: {record.contract}")
        if record.working_time:
            parts.append(f"Jornada: {record.working_time}")
        if record.vacancies:
            parts.append(f"Vacantes: {record.vacancies}")
        if record.publication_date:
            parts.append(f"Fecha de publicación: {record.publication_date:%d/%m/%Y}")
        elif record.publication_raw:
            parts.append(f"Fecha de publicación: {record.publication_raw}")
        if record.deadline_raw:
            parts.append(f"Plazo de solicitud: {record.deadline_raw}")
        elif record.deadline_date:
            parts.append(f"Plazo de solicitud: {record.deadline_date:%d/%m/%Y}")

        if record.summary_values:
            parts.append("Resumen de oferta: " + "; ".join(record.summary_values))
        if record.listing_description and not record.description:
            parts.append(f"Descripción del listado: {record.listing_description}")
        parts.extend(f"{label}: {value}" for label, value in deferred_sections)
        return clean_text(" ".join(part for part in parts if part), lowercase=False)

    @classmethod
    def _allocate_section(cls, value: str, limit: int) -> tuple[str, str]:
        """Keep ordered sentence units intact when allocating a section prefix."""
        normalized = cls._normalise(value)
        if not normalized:
            return "", ""

        units = [
            unit.strip()
            for unit in re.split(r"(?<=[.!?])\s+", normalized)
            if unit.strip()
        ]
        prefix: list[str] = []
        prefix_length = 0
        split_at = len(units)
        for index, unit in enumerate(units):
            candidate_length = len(unit) + (1 if prefix else 0)
            if prefix and prefix_length + candidate_length > limit:
                split_at = index
                break
            if not prefix and len(unit) > limit:
                split_at = index
                break
            prefix.append(unit)
            prefix_length += candidate_length

        return " ".join(prefix), " ".join(units[split_at:])

    def parse_detail(self, detail_html: str) -> str:
        """Extract one detail paragraph without any network access."""
        self.diagnostics.clear()
        record = self._parse_detail_record(
            str(detail_html),
            require_snapshot_identity=True,
        )
        return self._record_text(record)

    @staticmethod
    def _read_source(source: Union[Path, str, io.BytesIO, io.TextIOBase]) -> str:
        if isinstance(source, Path):
            with open(source, "rb") as source_file:
                raw_source: object = source_file.read()
        elif isinstance(source, str):
            if source.lstrip().startswith("<"):
                raw_source = source
            else:
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
    ) -> list[BOPage]:
        """Parse an offline detail or listing snapshot without constructing/fetching."""
        self.diagnostics.clear()
        html = self._read_source(source)
        reference_date = target_date or date.today()
        if target_date is not None:
            self._diagnose(
                "target_date is used only for explicit application deadlines; current FULP "
                "HTML cannot reconstruct historical availability."
            )

        if self.has_supported_detail_structure(html):
            try:
                record = self._parse_detail_record(
                    html,
                    require_snapshot_identity=True,
                    reference_date=reference_date,
                )
            except FulpParseError as exc:
                self._diagnose(f"offline detail was quarantined: {exc}")
                return []
            if record.availability_status in {"CLOSED", "EXPIRED"}:
                self._diagnose(
                    f"offline detail {record.offer_id} is {record.availability_status.casefold()}; skipped."
                )
                return []
            return [self._to_page(record, 1)]

        # A detail-shaped snapshot without canonical/og identity is still a
        # detail failure, not a generic page. Keep the identity diagnostic
        # explicit while returning no offline offer.
        detail_soup = BeautifulSoup(html, "html.parser")
        detail_roots = self._top_level_roots(detail_soup)
        if detail_roots:
            detail_titles = self._owned_descendants(
                detail_roots[0], self.TITLE_SELECTOR, "root"
            )
            if detail_titles and self._owned_text(detail_titles[0], detail_roots[0], "root"):
                try:
                    self._parse_detail_record(
                        html,
                        require_snapshot_identity=True,
                        reference_date=reference_date,
                    )
                except FulpParseError as exc:
                    self._diagnose(f"offline detail was quarantined: {exc}")
                    return []

        if self.has_supported_list_structure(html):
            records = self._parse_listing(html, reference_date)
            self._diagnose(
                "offline FULP listing produced listing-evidence-only records; detail content, "
                "eligibility and current availability are not reconstructed."
            )
            return [
                self._to_page(record, page_number, listing_only=True)
                for page_number, record in enumerate(records, start=1)
            ]

        self._diagnose(
            "offline HTML is neither a supported FULP listing nor a detail snapshot; ignored."
        )
        return []

    @classmethod
    def _merge_listing_metadata(cls, listing: FulpRecord, detail: FulpRecord) -> FulpRecord:
        if not detail.employer_raw and listing.employer_raw:
            detail.employer_raw = listing.employer_raw
            detail.employer = listing.employer_raw
        if not detail.location_raw and listing.location_raw:
            detail.location_raw = listing.location_raw
        if not detail.offer_type and listing.offer_type:
            detail.offer_type = listing.offer_type
            detail.type_normalized = listing.type_normalized
        if not detail.publication_date and listing.publication_date:
            detail.publication_date = listing.publication_date
            detail.publication_raw = listing.publication_raw
        if not detail.contract and listing.contract:
            detail.contract = listing.contract
        if not detail.working_time and listing.working_time:
            detail.working_time = listing.working_time
        if not detail.vacancies and listing.vacancies:
            detail.vacancies = listing.vacancies
        if not detail.deadline_date and listing.deadline_date:
            detail.deadline_date = listing.deadline_date
            detail.deadline_raw = listing.deadline_raw
        return detail

    def _to_page(self, record: FulpRecord, page_number: int, *, listing_only: bool = False) -> BOPage:
        return BOPage(
            page_number=page_number,
            text=self._record_text(record, listing_only=listing_only),
            section="Ofertas de empleo" + (" (evidencia limitada)" if listing_only else ""),
            detected_organism=record.employer or "Empresa no identificada",
            source=self.SOURCE,
            url=record.url,
        )

    def scan(self, target_date: Optional[date] = None) -> list[BOPage]:
        """Fetch one listing, deduplicate IDs, then process details serially."""
        self.diagnostics.clear()
        self.last_discovery = {}
        self.last_scan = {}
        if self.fetcher is None:
            raise FulpParseError("FULP scan requires an injected fetcher")
        if hasattr(self.fetcher, "begin_scan"):
            self.fetcher.begin_scan()

        reference_date = target_date or date.today()
        if target_date is not None:
            self._diagnose(
                "target_date is used only for explicit application deadlines; current FULP "
                "HTML cannot reconstruct historical availability."
            )
        try:
            list_html = self.fetcher.fetch_list()
        except FulpBudgetExceeded as exc:
            self._diagnose(f"listing fetch stopped before detail discovery: {exc}")
            self.last_scan = {
                "discovery_complete": False,
                "detail_complete": False,
                "attempted": 0,
                "successful": 0,
                "failed": 0,
                "remaining_ids": [],
                "budget_stopped": True,
            }
            return []
        except Exception as exc:
            self._diagnose(f"listing fetch failed; no details were attempted: {exc}")
            self.last_scan = {
                "discovery_complete": False,
                "detail_complete": False,
                "attempted": 0,
                "successful": 0,
                "failed": 0,
                "remaining_ids": [],
                "budget_stopped": False,
            }
            return []

        records = self.parse_list(list_html, target_date=reference_date)
        discovery_state = self.last_discovery.get("state", "INCOMPLETE")
        detail_pages: list[BOPage] = []
        detail_failures = 0
        attempted = 0
        remaining_ids = [record.offer_id for record in records]
        budget_stopped = False

        for index, listing in enumerate(records):
            remaining_ids = [record.offer_id for record in records[index:]]
            attempted += 1
            try:
                detail_html = self.fetcher.fetch_detail(listing.url)
                response_url = str(getattr(self.fetcher, "last_response_url", "") or "")
                detail = self._parse_detail_record(
                    detail_html,
                    fallback_url=listing.url,
                    expected_id=listing.offer_id,
                    response_url=response_url,
                    reference_date=reference_date,
                )
                detail = self._merge_listing_metadata(listing, detail)
            except FulpBudgetExceeded as exc:
                budget_stopped = True
                self._diagnose(
                    f"HTTP scheduling budget exhausted after {attempted - 1} detail attempts: {exc}. "
                    f"Remaining IDs: {', '.join(remaining_ids)}"
                )
                break
            except (FulpFetchError, FulpParseError, requests.RequestException, RuntimeError, ValueError) as exc:
                detail_failures += 1
                self._diagnose(
                    f"detail {listing.offer_id} failed and was skipped: {exc}"
                )
                continue
            except Exception as exc:
                detail_failures += 1
                self._diagnose(
                    f"detail {listing.offer_id} failed with an unexpected error and was skipped: {exc}"
                )
                continue

            if detail.availability_status in {"CLOSED", "EXPIRED"}:
                self._diagnose(
                    f"detail {listing.offer_id} is {detail.availability_status.casefold()}; skipped."
                )
                continue
            detail_pages.append(self._to_page(detail, len(detail_pages) + 1))

        if not budget_stopped:
            remaining_ids = []
        discovery_complete = discovery_state == "RECONCILED_FOR_RESPONSE"
        detail_complete = not budget_stopped and detail_failures == 0
        self.last_scan = {
            "discovery_complete": discovery_complete,
            "discovery_state": discovery_state,
            "detail_complete": detail_complete,
            "attempted": attempted,
            "successful": len(detail_pages),
            "failed": detail_failures,
            "remaining_ids": remaining_ids,
            "budget_stopped": budget_stopped,
        }
        self._diagnose(
            "detail processing: "
            f"attempted={attempted}, successful={len(detail_pages)}, failed={detail_failures}, "
            f"remaining={len(remaining_ids)}; "
            f"discovery={discovery_state}, details={'complete' if detail_complete else 'incomplete'}."
        )
        return detail_pages
