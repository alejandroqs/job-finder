"""Pure page-status parser for the active SODETEGC employment section."""

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag


class ObservationStatus(str, Enum):
    BASELINE = "BASELINE"
    CHANGED = "CHANGED"
    UNVERIFIABLE = "UNVERIFIABLE"


@dataclass(frozen=True)
class SODETEGCObservation:
    """Comparison result and diagnostic context for one page response."""

    status: ObservationStatus
    owned_text: str = ""
    diagnostic: str = ""


@dataclass(frozen=True)
class _PageOwner:
    article: Tag
    content: Tag


class SODETEGCParser:
    """Compare only visible text owned by the active open-calls section."""

    URL = "https://www.sodetegc.org/conocenos/informacion-administrativa/empleo/"
    ALLOWED_HOSTS = frozenset({"sodetegc.org", "www.sodetegc.org"})
    PATH = "/conocenos/informacion-administrativa/empleo"
    REFERENCE_TEXT = "Actualmente no hay ninguna convocatoria abierta"
    TITLE_SELECTOR = "#sodetegc-title h1"
    MAIN_SELECTOR = "main#sodetegc-content"
    ACTIVE_HEADING = "convocatorias abiertas"
    HEADING_NAMES = ("h1", "h2", "h3", "h4", "h5", "h6")
    EXCLUDED_TAGS = frozenset(
        {"script", "style", "noscript", "template", "nav", "footer"}
    )
    BLOCK_TAGS = frozenset(
        {
            "address", "article", "blockquote", "div", "dl", "dt", "dd", "fieldset",
            "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "li",
            "ol", "p", "pre", "section", "table", "tbody", "td", "th", "tr", "ul",
        }
    )
    HIDDEN_CLASSES = frozenset(
        {"hidden", "is-hidden", "d-none", "screen-reader-text", "sr-only"}
    )

    @staticmethod
    def _normalise_visible_text(value: str) -> str:
        value = unicodedata.normalize("NFC", value.replace("\u00a0", " ").replace("\u202f", " "))
        return " ".join(value.split())

    @classmethod
    def _normalise_comparison(cls, value: str) -> str:
        normalised = cls._normalise_visible_text(value).casefold()
        if normalised.endswith("."):
            normalised = normalised[:-1].rstrip()
        return normalised

    @classmethod
    def _tag_text(cls, tag: Tag, owner: Optional[_PageOwner] = None) -> str:
        def collect(node) -> str:
            if isinstance(node, Comment):
                return ""
            if isinstance(node, NavigableString):
                parent = node.parent
                if isinstance(parent, Tag) and cls._is_hidden_or_excluded(parent, owner):
                    return ""
                return str(node)
            if not isinstance(node, Tag):
                return ""
            if cls._is_hidden_or_excluded(node, owner):
                return ""

            text = "".join(collect(child) for child in node.children)
            if node.name == "br" or node.name in cls.BLOCK_TAGS:
                return f" {text} "
            return text

        return cls._normalise_visible_text(collect(tag))

    @classmethod
    def _is_official_employment_url(cls, value: str) -> bool:
        try:
            parts = urlsplit(value.strip())
            port = parts.port
        except ValueError:
            return False
        return (
            parts.scheme.lower() == "https"
            and (parts.hostname or "").lower() in cls.ALLOWED_HOSTS
            and parts.username is None
            and parts.password is None
            and port in {None, 443}
            and parts.path.rstrip("/") == cls.PATH
            and not parts.query
            and not parts.fragment
        )

    @classmethod
    def _has_official_identity(cls, soup: BeautifulSoup) -> tuple[bool, str]:
        identity_values = []
        for link in soup.find_all("link", rel=lambda value: value and "canonical" in value):
            href = str(link.get("href", "")).strip()
            if href:
                identity_values.append(href)
        for meta in soup.find_all("meta", attrs={"property": "og:url"}):
            content = str(meta.get("content", "")).strip()
            if content:
                identity_values.append(content)

        if not identity_values:
            return False, "official canonical or og:url identity is missing"
        if any(not cls._is_official_employment_url(value) for value in identity_values):
            return False, "canonical/og:url evidence contains an invalid or conflicting identity"
        if len({cls._normalise_identity(value) for value in identity_values}) != 1:
            return False, "canonical/og:url evidence conflicts"
        return True, ""

    @classmethod
    def _normalise_identity(cls, value: str) -> str:
        parts = urlsplit(value.strip())
        return f"{parts.scheme.lower()}://{(parts.hostname or '').lower()}{parts.path.rstrip('/')}"

    @classmethod
    def _nearest_article(cls, tag: Tag) -> Optional[Tag]:
        current: Optional[Tag] = tag
        while isinstance(current, Tag):
            if current.name == "article":
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _nearest_entry_content(cls, tag: Tag) -> Optional[Tag]:
        current: Optional[Tag] = tag
        while isinstance(current, Tag):
            if "entry-content" in current.get("class", []):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _page_owner(cls, soup: BeautifulSoup) -> tuple[Optional[_PageOwner], str]:
        title_nodes = soup.select(cls.TITLE_SELECTOR)
        titles = [cls._tag_text(node).casefold() for node in title_nodes]
        page_title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
        if (
            len(titles) != 1
            or "empleo" not in titles[0]
            or "sodetegc" not in page_title
            or "empleo" not in page_title
        ):
            return None, "employment-page title signature is missing or ambiguous"

        mains = soup.select(cls.MAIN_SELECTOR)
        if len(mains) != 1:
            return None, "main#sodetegc-content owner is missing or ambiguous"
        main = mains[0]

        content_nodes = [
            node
            for node in main.select(".entry-content")
            if cls._nearest_article(node) is not None
        ]
        article_owners = []
        for node in content_nodes:
            article_owner = cls._nearest_article(node)
            if article_owner is not None and all(
                article_owner is not existing for existing in article_owners
            ):
                article_owners.append(article_owner)
        outer_owners = [
            owner
            for owner in article_owners
            if not any(
                isinstance(parent, Tag)
                and any(parent is candidate for candidate in article_owners)
                for parent in owner.parents
            )
        ]
        if len(outer_owners) != 1:
            return None, "article content owner is missing or ambiguous"

        article = outer_owners[0]
        owned_content_nodes = [
            node for node in content_nodes if cls._nearest_article(node) is article
        ]
        if len(owned_content_nodes) != 1:
            return None, "article .entry-content owner is missing or ambiguous"

        return _PageOwner(article=article, content=owned_content_nodes[0]), ""

    @classmethod
    def _page_signature(cls, html: str) -> tuple[bool, str]:
        if not html or not html.strip():
            return False, "HTML response is empty"
        folded = html.casefold()
        if not all(token in folded for token in ("</main>", "</article>", "</html>")):
            return False, "HTML document appears truncated or lacks closing page-owner boundaries"

        soup = BeautifulSoup(html, "html.parser")
        identity_ok, identity_diagnostic = cls._has_official_identity(soup)
        if not identity_ok:
            return False, identity_diagnostic
        owner, owner_diagnostic = cls._page_owner(soup)
        if owner is None:
            return False, owner_diagnostic
        return True, ""

    @classmethod
    def has_page_signature(cls, html: str) -> bool:
        """Return whether HTML has this official, structurally owned page signature."""
        return cls._page_signature(html)[0]

    @classmethod
    def _is_hidden_or_excluded(
        cls, tag: Tag, owner: Optional[_PageOwner] = None
    ) -> bool:
        current: Optional[Tag] = tag
        while isinstance(current, Tag):
            if current.name in cls.EXCLUDED_TAGS:
                return True
            if owner is not None and current is not owner.article and current.name == "article":
                return True
            if (
                owner is not None
                and current is not owner.content
                and "entry-content" in current.get("class", [])
                and owner.content in current.parents
            ):
                return True
            if current.name == "details" and not current.has_attr("open"):
                summary = current.find("summary", recursive=False)
                if summary is None or (tag is not summary and summary not in tag.parents):
                    return True
            if current.has_attr("hidden"):
                return True
            if str(current.get("aria-hidden", "")).strip().casefold() == "true":
                return True
            classes = {str(value).casefold() for value in current.get("class", [])}
            if classes & cls.HIDDEN_CLASSES:
                return True
            style = re.sub(r"\s+", "", str(current.get("style", "")).casefold())
            if re.search(r"(?:^|;)display:none(?:!important)?(?:;|$)", style) or re.search(
                r"(?:^|;)visibility:hidden(?:!important)?(?:;|$)", style
            ):
                return True
            current = current.parent if isinstance(current.parent, Tag) else None
        return False

    @classmethod
    def _is_owned(cls, tag: Tag, owner: _PageOwner) -> bool:
        return (
            cls._nearest_article(tag) is owner.article
            and cls._nearest_entry_content(tag) is owner.content
        )

    @classmethod
    def _visible_owned_headings(cls, owner: _PageOwner) -> list[Tag]:
        return [
            heading
            for heading in owner.content.find_all(cls.HEADING_NAMES)
            if cls._is_owned(heading, owner)
            and not cls._is_hidden_or_excluded(heading, owner)
            and cls._tag_text(heading, owner)
        ]

    @classmethod
    def _extract_section_text(
        cls, heading: Tag, boundary: Optional[Tag], owner: _PageOwner
    ) -> str:
        pieces = []
        for node in heading.next_elements:
            if node is boundary:
                break
            if isinstance(node, Comment):
                continue
            if isinstance(node, Tag):
                if not cls._is_owned(node, owner) or cls._is_hidden_or_excluded(node, owner):
                    continue
                if node.name == "br" or node.name in cls.BLOCK_TAGS:
                    pieces.append(" ")
                continue
            if not isinstance(node, NavigableString) or heading in node.parents:
                continue
            parent = node.parent
            if (
                not isinstance(parent, Tag)
                or not cls._is_owned(parent, owner)
                or cls._is_hidden_or_excluded(parent, owner)
            ):
                continue
            pieces.append(str(node))
        return cls._normalise_visible_text("".join(pieces))

    @classmethod
    def parse(cls, html: str) -> SODETEGCObservation:
        """Return baseline, changed, or unverifiable for the owned active section."""
        if not html or not html.strip():
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE, diagnostic="HTML response is empty"
            )

        folded = html.casefold()
        if (
            "cf-challenge" in folded
            or "challenge-platform" in folded
            or "just a moment..." in folded
            or "checking your browser" in folded
        ):
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic="response appears to be a challenge page",
            )

        soup = BeautifulSoup(html, "html.parser")
        password_form = soup.find("input", attrs={"type": re.compile("^password$", re.I)})
        page_title = soup.title.get_text(" ", strip=True).casefold() if soup.title else ""
        if password_form is not None and any(
            token in page_title for token in ("login", "log in", "sign in", "iniciar sesión")
        ):
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic="response appears to be a login page",
            )

        identity_ok, identity_diagnostic = cls._has_official_identity(soup)
        if not identity_ok:
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE, diagnostic=identity_diagnostic
            )
        owner, owner_diagnostic = cls._page_owner(soup)
        if owner is None:
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE, diagnostic=owner_diagnostic
            )
        if not all(token in folded for token in ("</main>", "</article>", "</html>")):
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic="HTML document appears truncated or lacks closing page-owner boundaries",
            )
        if cls._is_hidden_or_excluded(owner.content, owner):
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic="active section owner is explicitly hidden or excluded",
            )

        matching_headings = [
            heading
            for heading in cls._visible_owned_headings(owner)
            if cls._normalise_comparison(cls._tag_text(heading, owner)).rstrip(":")
            == cls.ACTIVE_HEADING
        ]
        if len(matching_headings) != 1:
            detail = "missing" if not matching_headings else "ambiguous"
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic=f"active 'Convocatorias abiertas' heading is {detail}",
            )

        heading = matching_headings[0]
        rank = int(heading.name[1])
        headings = cls._visible_owned_headings(owner)
        heading_index = headings.index(heading)
        boundary = next(
            (candidate for candidate in headings[heading_index + 1:] if int(candidate.name[1]) <= rank),
            None,
        )
        owned_text = cls._extract_section_text(heading, boundary, owner)
        if not owned_text and boundary is None:
            return SODETEGCObservation(
                ObservationStatus.UNVERIFIABLE,
                diagnostic="active section is empty and has no verified subsequent section boundary",
            )

        if cls._normalise_comparison(owned_text) == cls._normalise_comparison(
            cls.REFERENCE_TEXT
        ):
            return SODETEGCObservation(ObservationStatus.BASELINE, owned_text=owned_text)
        return SODETEGCObservation(ObservationStatus.CHANGED, owned_text=owned_text)
