import hashlib
import io
import re
import unicodedata
from collections import deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Union
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from job_finder.indra_fetcher import IndraFetchError
from job_finder.interfaces import BOPage, BaseParser, BaseWebBoardParser
from job_finder.text_cleaner import clean_text


class IndraParseError(ValueError):
    """The current Indra response does not satisfy a supported structure."""


class IndraIdentityError(IndraParseError):
    """A detail response identifies a different job than the requested listing."""


@dataclass
class IndraJob:
    """Fields retained from one Indra listing/detail record."""

    job_id: str = ""
    title: str = ""
    url: str = ""
    location_raw: str = ""
    country: str = ""
    work_mode_raw: str = ""
    work_mode_normalized: str = "UNKNOWN"
    professional_profile: str = ""
    experience: str = ""
    role: str = ""
    description: str = ""
    requirements: str = ""
    responsibilities: str = ""
    publication_date: Optional[date] = None
    listing_date_raw: str = ""
    source_query: str = ""

    @property
    def id(self) -> str:
        return self.job_id

    @property
    def location(self) -> str:
        return self.location_raw

    @property
    def raw_location(self) -> str:
        return self.location_raw

    @property
    def raw_country(self) -> str:
        return self.country

    @property
    def work_mode(self) -> str:
        return self.work_mode_normalized

    @property
    def canonical_url(self) -> str:
        return self.url


@dataclass(frozen=True)
class _SearchPage:
    jobs: list[IndraJob]
    next_urls: list[str]
    advertised_total: Optional[int]
    candidate_identities: frozenset[str] = frozenset()
    rejected_records: int = 0
    malformed_records: int = 0


class IndraParser(BaseParser, BaseWebBoardParser):
    """Parse and scan the server-rendered Indra Group careers portal."""

    BASE_URL = "https://careers.indragroup.com/"
    SEARCH_URL = "https://careers.indragroup.com/search/"
    OFFICIAL_HOST = "careers.indragroup.com"
    SOURCE = "INDRA"
    ORGANISM = "Indra Group"
    DEFAULT_LOCALE = "es_ES"
    DEFAULT_SORT_COLUMN = "referencedate"
    DEFAULT_SORT_DIRECTION = "desc"
    MAX_PAGES_PER_QUERY = 200
    SEARCH_TABLE_ID = "searchresults"
    JOB_OWNER_SELECTOR = ".job"
    TITLE_SELECTOR = "[data-careersite-propertyid='title']"
    DETAIL_PROPERTY_LABELS = {
        "title": ("titulo", "título", "title", "job title", "puesto"),
        "location": ("ubicacion", "ubicación", "location", "localizacion", "localización"),
        "country": ("pais", "país", "country"),
        "professional_profile": ("perfil profesional", "professional profile"),
        "experience": ("experiencia requerida", "experiencia", "required experience", "experience"),
        "work_mode": ("modalidad del puesto", "modalidad", "work mode", "work modality"),
        "role": ("rol", "role"),
        "description": ("descripcion", "descripción", "description"),
    }
    PROPERTY_IDS = {
        "title": "title",
        "location": "location",
        "professional_profile": "customfield1",
        "experience": "customfield3",
        "work_mode": "customfield4",
        "role": "customfield2",
        "description": "description",
    }
    SECTION_LABELS = {
        "description": {"descripcion", "descripción", "description", "resumen", "summary"},
        "requirements": {
            "requisitos",
            "requisitos minimos",
            "requisitos imprescindibles",
            "que buscamos en ti",
            "requirements",
            "required skills",
        },
        "responsibilities": {
            "responsabilidades",
            "funciones",
            "que haras",
            "responsibilities",
            "duties",
        },
        "skip": {
            "beneficios",
            "benefits",
            "que ofrecemos",
            "qué ofrecemos",
            "lo que ofrecemos",
            "lo que te ofrecemos",
            "proceso de seleccion",
            "proceso de selección",
            "como es nuestro proceso de seleccion",
            "como es nuestro proceso de selección",
            "selection process",
            "recruitment process",
            "sobre nosotros",
            "about us",
        },
    }
    PAGINATION_QUERY_KEYS = {"q", "locale", "sortcolumn", "sortdirection", "startrow"}
    DESCRIPTION_BLOCK_TAGS = frozenset(
        {
            "article",
            "blockquote",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "ol",
            "p",
            "section",
            "table",
            "tbody",
            "td",
            "tfoot",
            "th",
            "thead",
            "tr",
            "ul",
        }
    )
    JOB_PATH_PATTERN = re.compile(r"^/(?:[^/]+/)?job/[^/]+/\d+/?$", re.IGNORECASE)
    JOB_ID_PATTERN = re.compile(r"/(?:[^/]+/)?job/[^/]+/(\d+)/?$", re.IGNORECASE)
    DATE_PATTERNS = (
        re.compile(r"(?<!\d)(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?!\d)"),
        re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    )
    BOILERPLATE_PATTERNS = (
        re.compile(r"^(?:cookies?|privacy policy|pol[ií]tica de privacidad)\b", re.IGNORECASE),
        re.compile(r"^(?:únete a nuestro equipo|join our team)\b", re.IGNORECASE),
    )
    RESTRICTION_PATTERN = re.compile(
        r"\b(?:availability|contractual|contract|must|required|on-call|residence|schedule|shift|"
        r"guardia|guardias|horario|jornada|movilidad|obligatorio|obligatoria|"
        r"imprescindible|imprescindibles|disponibilidad|residencia|turno|turnos|"
        r"contratacion|contrato|requiere|requieren|requerimos)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        fetcher=None,
        locale: str = DEFAULT_LOCALE,
        max_pages: int = MAX_PAGES_PER_QUERY,
        keyword_filter=None,
    ):
        self.fetcher = fetcher
        self.locale = locale
        self.max_pages = max_pages
        self.keyword_filter = keyword_filter

    @classmethod
    def has_supported_structure(cls, html: str) -> bool:
        """Recognise a detail page only with both bounded fields and official identity."""
        soup = BeautifulSoup(html, "html.parser")
        owner = soup.select_one(cls.JOB_OWNER_SELECTOR)
        if owner is None or not cls._has_title_field(owner):
            return False
        canonical = cls._find_official_job_url(soup)
        return bool(canonical)

    def parse_list(self, list_html: str, target_date=None) -> list[IndraJob]:
        """Parse one search response while retaining only row-owned job records."""
        del target_date
        return self._parse_search_page(list_html, self._initial_search_url(""), "").jobs

    def parse_detail(self, detail_html: str) -> str:
        """Return one cohesive candidate paragraph from an Indra detail page."""
        return self._page_text(self.parse_detail_job(detail_html))

    def parse_detail_job(self, detail_html: str, fallback_url: str = "") -> IndraJob:
        """Extract detail metadata and bounded job-description sections."""
        soup = BeautifulSoup(detail_html, "html.parser")
        owner = soup.select_one(self.JOB_OWNER_SELECTOR)
        if owner is None:
            raise IndraParseError("detail owner .job is missing")

        title = self._detail_field(owner, "title")
        if not title:
            raise IndraParseError("detail title is missing")

        try:
            fallback_clean = self._clean_job_url(fallback_url)
        except ValueError as exc:
            raise IndraParseError(f"detail fallback URL is malformed: {exc}") from exc
        canonical = self._find_official_job_url(soup)
        url = canonical or fallback_clean
        if not url:
            raise IndraParseError(f"detail {title!r} has no reliable official job URL")

        canonical_id = self._job_id(canonical)
        fallback_id = self._job_id(fallback_clean)
        if canonical_id and fallback_id and canonical_id != fallback_id:
            raise IndraIdentityError(
                f"detail {title} canonical ID {canonical_id} disagrees with listing ID {fallback_id}; "
                "response quarantined."
            )

        location = self._detail_field(owner, "location")
        country = self._detail_field(owner, "country") or self._infer_country(location)
        mode_values = self._detail_field_values(owner, "work_mode")
        mode = " | ".join(mode_values)
        normalized_modes = [self._normalise_work_mode(value) for value in mode_values]
        if len(mode_values) > 1 and len(set(normalized_modes)) != 1:
            self._diagnose(
                f"detail {title} contains contradictory work modes {mode_values}; "
                "preserving raw values and using UNKNOWN."
            )
            normalized_mode = "UNKNOWN"
        else:
            normalized_mode = normalized_modes[0] if normalized_modes else "UNKNOWN"
        description, requirements, responsibilities = self._description_fields(owner)

        return IndraJob(
            job_id=canonical_id or fallback_id or "",
            title=title,
            url=url,
            location_raw=location,
            country=country,
            work_mode_raw=mode,
            work_mode_normalized=normalized_mode,
            professional_profile=self._detail_field(owner, "professional_profile"),
            experience=self._detail_field(owner, "experience"),
            role=self._detail_field(owner, "role"),
            description=description,
            requirements=requirements,
            responsibilities=responsibilities,
            publication_date=self._publication_date(soup, owner),
        )

    def parse(self, source: Union[Path, str, io.BytesIO]) -> list[BOPage]:
        """Parse a local detail snapshot without making any network request."""
        html = self._read_source(source)
        if self.has_supported_structure(html):
            job = self.parse_detail_job(html)
            if self._should_reject_title(job.title):
                self._diagnose(f"offline detail title rejected by shared title rules: {job.title}")
                return []
            allowed, status, reason = self._geography_decision(job)
            if not allowed:
                self._diagnose(f"offline detail geographically {status}: {reason}; skipped.")
                return []
            return [self._to_page(job, 1)]

        soup = BeautifulSoup(html, "html.parser")
        if soup.find("table", id=self.SEARCH_TABLE_ID) or soup.find(id="noresults"):
            self._diagnose(
                "offline listing snapshot has no detail modality evidence; "
                "not inferring remote eligibility or fetching missing details."
            )
            return []
        raise IndraParseError("offline HTML is neither a supported Indra detail nor search snapshot")

    def scan(self, search_terms: Optional[Iterable[str]] = None) -> list[BOPage]:
        """Discover, deduplicate, detail-parse, and geographically filter Indra jobs."""
        if self.fetcher is None:
            raise IndraParseError("Indra scan requires an injected fetcher")

        terms = self._normalise_terms(search_terms)
        jobs_by_identity: dict[str, IndraJob] = {}
        for term in terms:
            self._scan_query(term, jobs_by_identity)

        print(f"📊 INDRA unique logical jobs before details: {len(jobs_by_identity)}")
        accepted_pages: list[BOPage] = []
        detail_successes = 0
        detail_failures = 0
        geographic_counts = {"accepted": 0, "rejected": 0, "unknown": 0}

        for job in jobs_by_identity.values():
            try:
                detail_html = self.fetcher.fetch_detail(job.url)
                detailed_job = self.parse_detail_job(detail_html, fallback_url=job.url)
                detail_successes += 1
            except (IndraParseError, IndraFetchError, requests.RequestException, RuntimeError) as exc:
                detail_failures += 1
                self._diagnose(
                    f"detail failed for {job.job_id or job.url}: {exc}; skipping because "
                    "failure does not prove geographic eligibility."
                )
                continue

            if self._should_reject_title(detailed_job.title):
                self._diagnose(
                    f"detail {detailed_job.job_id or detailed_job.url} title rejected by shared title rules: "
                    f"{detailed_job.title}; skipped."
                )
                continue

            detailed_job.source_query = job.source_query
            detailed_job.listing_date_raw = job.listing_date_raw
            allowed, status, reason = self._geography_decision(detailed_job)
            geographic_counts[status] += 1
            if not allowed:
                self._diagnose(
                    f"job {detailed_job.job_id or detailed_job.url} geographically {status}: {reason}; skipped."
                )
                continue
            accepted_pages.append(self._to_page(detailed_job, len(accepted_pages) + 1))

        print(
            "📊 INDRA details: "
            f"attempted={len(jobs_by_identity)}, successful={detail_successes}, failed={detail_failures}; "
            "geographic accepted="
            f"{geographic_counts['accepted']}, rejected={geographic_counts['rejected']}, "
            f"unknown={geographic_counts['unknown']}"
        )
        return accepted_pages

    @staticmethod
    def is_geographically_eligible(job: IndraJob) -> bool:
        """Return the mandatory Indra geographic decision for one parsed job."""
        return IndraParser._geography_decision(job)[0]

    @classmethod
    def _normalise_terms(cls, search_terms: Optional[Iterable[str]]) -> list[str]:
        terms: list[str] = []
        for term in search_terms or []:
            if not isinstance(term, str):
                raise ValueError("Indra search terms must be strings")
            cleaned = term.strip()
            if cleaned and cleaned not in terms:
                terms.append(cleaned)
        return terms or [""]

    def _should_reject_title(self, title: str) -> bool:
        return self.keyword_filter is not None and self.keyword_filter.should_reject_title(title)

    def _scan_query(self, term: str, jobs_by_identity: dict[str, IndraJob]) -> None:
        initial_url = self._initial_search_url(term)
        try:
            html = self.fetcher.fetch_list() if not term else self.fetcher.fetch_search(term)
        except (IndraFetchError, requests.RequestException, RuntimeError) as exc:
            self._diagnose(f"query {(term or '<blank catalogue>')!r} failed: {exc}; continuing other queries.")
            return

        pending = deque([(initial_url, html)])
        scheduled = {self._page_identity(initial_url, term)}
        visited: set[str] = set()
        content_hashes: set[str] = set()
        result_signatures: set[tuple[str, ...]] = set()
        discovered_keys: set[str] = set()
        accepted_keys: set[str] = set()
        advertised_totals: set[int] = set()
        rejected_records = 0
        malformed_records = 0
        pages_seen = 0
        incomplete = False

        while pending and pages_seen < self.max_pages:
            page_url, page_html = pending.popleft()
            page_identity = self._page_identity(page_url, term)
            if page_identity in visited:
                self._diagnose(
                    f"query {(term or '<blank catalogue>')!r} ignored duplicate navigation to "
                    f"already covered page {page_identity}."
                )
                continue
            visited.add(page_identity)

            if page_html is None:
                try:
                    page_html = self.fetcher.fetch_page(page_url)
                except (IndraFetchError, requests.RequestException, RuntimeError) as exc:
                    self._diagnose(f"query {(term or '<blank catalogue>')!r} page {page_url} failed: {exc}; continuing known pages.")
                    incomplete = True
                    continue

            digest = hashlib.sha256(page_html.encode("utf-8", errors="replace")).hexdigest()
            if digest in content_hashes:
                self._diagnose(f"query {(term or '<blank catalogue>')!r} returned a repeated page body at {page_url}; traversal is incomplete.")
                incomplete = True
                continue
            content_hashes.add(digest)

            try:
                parsed_page = self._parse_search_page(page_html, page_url, term)
            except IndraParseError as exc:
                self._diagnose(f"query {(term or '<blank catalogue>')!r} page {page_url} has structural error: {exc}")
                incomplete = True
                continue

            pages_seen += 1
            rejected_records += parsed_page.rejected_records
            malformed_records += parsed_page.malformed_records
            if parsed_page.advertised_total is not None:
                advertised_totals.add(parsed_page.advertised_total)

            result_signature = tuple(sorted(parsed_page.candidate_identities))
            if result_signature and result_signature in result_signatures:
                self._diagnose(
                    f"query {(term or '<blank catalogue>')!r} returned repeated results at "
                    f"{page_url} despite a new page identity; traversal is incomplete."
                )
                incomplete = True
                continue
            if result_signature:
                result_signatures.add(result_signature)

            discovered_keys.update(parsed_page.candidate_identities)
            for job in parsed_page.jobs:
                identity = self._job_identity(job)
                accepted_keys.add(identity)
                if identity not in jobs_by_identity:
                    job.source_query = term
                    jobs_by_identity[identity] = job

            for next_url in parsed_page.next_urls:
                next_identity = self._page_identity(next_url, term)
                if next_identity in scheduled:
                    continue
                scheduled.add(next_identity)
                pending.append((next_url, None))

        if pending:
            incomplete = True
            self._diagnose(
                f"query {(term or '<blank catalogue>')!r} reached the safety bound of "
                f"{self.max_pages} pages; discovery is incomplete."
            )

        if len(advertised_totals) > 1:
            incomplete = True
            self._diagnose(
                f"query {(term or '<blank catalogue>')!r} reported contradictory totals "
                f"{sorted(advertised_totals)}."
            )
        if advertised_totals:
            advertised_total = max(advertised_totals)
            if len(discovered_keys) != advertised_total:
                incomplete = True
                self._diagnose(
                    f"query {(term or '<blank catalogue>')!r} discovered {len(discovered_keys)} "
                    f"records against advertised total {advertised_total}; "
                    f"rejected_titles={rejected_records}, malformed_records={malformed_records}; "
                    "coverage is incomplete."
                )

        status = "incomplete" if incomplete else "complete"
        print(
            f"🔎 INDRA query {(term or '<blank catalogue>')!r}: pages={pages_seen}, "
            f"discovered_records={len(discovered_keys)}, accepted_records={len(accepted_keys)}, "
            f"rejected_titles={rejected_records}, malformed_records={malformed_records}, status={status}"
        )

    def _parse_search_page(self, html: str, current_url: str, term: str) -> _SearchPage:
        soup = BeautifulSoup(html, "html.parser")
        if soup.find(id="noresults") is not None:
            return _SearchPage([], [], 0)

        table = soup.find("table", id=self.SEARCH_TABLE_ID)
        if table is None:
            raise IndraParseError("table#searchresults is missing without #noresults")

        jobs: list[IndraJob] = []
        candidate_identities: set[str] = set()
        rejected_records = 0
        malformed_records = 0
        for row_number, row in enumerate(table.find_all("tr", class_="data-row"), start=1):
            if self._nearest_search_table(row) is not table:
                continue
            job = self._parse_search_row(row, row_number)
            if job is None:
                malformed_records += 1
                continue
            candidate_identities.add(self._job_identity(job))
            if self._should_reject_title(job.title):
                rejected_records += 1
                self._diagnose(
                    f"search row {row_number} title rejected by shared title rules: {job.title}"
                )
                continue
            jobs.append(job)

        next_urls = self._pagination_urls(soup, current_url, term)
        return _SearchPage(
            jobs,
            next_urls,
            self._advertised_total(table, soup),
            frozenset(candidate_identities),
            rejected_records,
            malformed_records,
        )

    def _parse_search_row(self, row: Tag, row_number: int) -> Optional[IndraJob]:
        anchors = [
            anchor
            for anchor in row.select("a.jobTitle-link")
            if self._nearest_data_row(anchor) is row
        ]
        titles = [self._owned_row_text(anchor) for anchor in anchors]
        titles = [title for title in titles if title]
        if not anchors or not titles or len(set(titles)) != 1:
            self._diagnose(f"search row {row_number} has missing or contradictory title anchors; skipped.")
            return None
        urls = []
        for anchor in anchors:
            try:
                resolved = self._clean_job_url(anchor.get("href", ""))
            except ValueError as exc:
                self._diagnose(f"search row {row_number} has malformed job URL: {exc}; skipped.")
                return None
            if not resolved:
                self._diagnose(f"search row {row_number} has a non-navigation or off-host job URL; skipped.")
                return None
            urls.append(resolved)
        if len(set(urls)) != 1:
            self._diagnose(f"search row {row_number} has contradictory duplicate job URLs; skipped.")
            return None

        location = self._owned_row_value(row, ".jobLocation")
        listing_date = self._owned_row_value(row, ".jobDate")
        return IndraJob(
            job_id=self._job_id(urls[0]),
            title=titles[0],
            url=urls[0],
            location_raw=location,
            country=self._infer_country(location),
            listing_date_raw=listing_date,
        )

    def _pagination_urls(self, soup: BeautifulSoup, current_url: str, term: str) -> list[str]:
        urls: list[str] = []
        for anchor in soup.select(".pagination a[href]"):
            href = str(anchor.get("href", "")).strip()
            if not href:
                continue
            try:
                normalised = self._normalise_pagination_url(href, current_url, term)
            except ValueError as exc:
                self._diagnose(f"pagination link {href!r} rejected: {exc}")
                continue
            if normalised and normalised not in urls:
                urls.append(normalised)
        return urls

    def _normalise_pagination_url(self, href: str, current_url: str, term: str) -> str:
        try:
            resolved = urlparse(urljoin(current_url or self.SEARCH_URL, href))
        except ValueError:
            raise ValueError("malformed pagination URL") from None
        if resolved.scheme.lower() not in {"http", "https"} or resolved.netloc.casefold() != self.OFFICIAL_HOST:
            raise ValueError("pagination URL is off the official host")
        if resolved.path.rstrip("/").casefold() != "/search":
            raise ValueError("pagination URL is outside /search/")

        params = parse_qsl(resolved.query, keep_blank_values=True)
        unsupported = {
            key.casefold()
            for key, _ in params
            if not key.casefold().startswith("utm_") and key.casefold() not in self.PAGINATION_QUERY_KEYS
        }
        if unsupported:
            raise ValueError(
                "pagination query introduces unsupported narrower filters: "
                + ", ".join(sorted(unsupported))
            )

        params = [
            (key, value) for key, value in params if not key.casefold().startswith("utm_")
        ]
        q_values = [value for key, value in params if key.casefold() == "q"]
        locale_values = [value for key, value in params if key.casefold() == "locale"]
        if q_values and (len(set(q_values)) != 1 or q_values[0] != term):
            raise ValueError("pagination query does not preserve q")
        if locale_values and (len(set(locale_values)) != 1 or locale_values[0] != self.locale):
            raise ValueError("pagination query does not preserve the chosen locale")
        if not q_values:
            params.append(("q", term))
        if not locale_values:
            params.append(("locale", self.locale))

        current_params = parse_qsl(urlparse(current_url or self.SEARCH_URL).query, keep_blank_values=True)
        current_sort = self._effective_sorting(current_params)
        target_sort = self._explicit_sorting(params)
        if target_sort is not None:
            target_column, target_direction = target_sort
            target_column = target_column or current_sort[0]
            target_direction = target_direction or current_sort[1]
            if (target_column.casefold(), target_direction.casefold()) != (
                current_sort[0].casefold(),
                current_sort[1].casefold(),
            ):
                raise ValueError("pagination query has conflicting sort order with current page")
            has_column = any(key.casefold() == "sortcolumn" for key, _ in params)
            has_direction = any(key.casefold() == "sortdirection" for key, _ in params)
            if not has_column or not has_direction:
                params = self._with_sorting(params, target_column, target_direction)
        elif self._explicit_sorting(current_params) is not None:
            params = self._with_sorting(params, current_sort[0], current_sort[1])

        self._single_query_value(params, "startrow")

        clean_query = urlencode(params, doseq=True)
        return urlunparse(("https", self.OFFICIAL_HOST, "/search/", "", clean_query, ""))

    def _initial_search_url(self, term: str) -> str:
        query = urlencode({"q": term, "locale": self.locale})
        return urlunparse(("https", self.OFFICIAL_HOST, "/search/", "", query, ""))

    @classmethod
    def _page_identity(cls, page_url: str, term: str) -> str:
        parsed = urlparse(page_url)
        params = parse_qsl(parsed.query, keep_blank_values=True)
        cleaned: list[tuple[str, str]] = []
        has_startrow = False
        sort_params: list[tuple[str, str]] = []
        for key, value in params:
            normalized_key = key.casefold()
            if normalized_key.startswith("utm_"):
                continue
            if normalized_key in {"sortcolumn", "sortdirection"}:
                sort_params.append((normalized_key, value))
                continue
            if normalized_key == "startrow":
                if has_startrow:
                    continue
                has_startrow = True
                try:
                    value = str(int(value or "0"))
                except ValueError:
                    value = value.strip()
            cleaned.append((normalized_key, value))
        if not has_startrow:
            cleaned.append(("startrow", "0"))
        if not any(key == "q" for key, _ in cleaned):
            cleaned.append(("q", term))
        sort_column, sort_direction = cls._effective_sorting(sort_params)
        cleaned.extend(
            [("sortcolumn", sort_column.casefold()), ("sortdirection", sort_direction.casefold())]
        )
        startrow = next((value for key, value in cleaned if key == "startrow"), "")
        if (
            startrow == "0"
            and sort_column.casefold() == cls.DEFAULT_SORT_COLUMN
            and sort_direction.casefold() == cls.DEFAULT_SORT_DIRECTION
        ):
            cleaned = [
                (key, value)
                for key, value in cleaned
                if key not in {"sortcolumn", "sortdirection"}
            ]
        return f"{parsed.path.rstrip('/').casefold()}/?{urlencode(sorted(cleaned))}"

    @classmethod
    def _explicit_sorting(cls, params: Iterable[tuple[str, str]]) -> Optional[tuple[str, str]]:
        params = list(params)
        column = cls._single_query_value(params, "sortcolumn")
        direction = cls._single_query_value(params, "sortdirection")
        if column is None and direction is None:
            return None
        return column or "", direction or ""

    @classmethod
    def _effective_sorting(cls, params: Iterable[tuple[str, str]]) -> tuple[str, str]:
        explicit = cls._explicit_sorting(params)
        if explicit is None:
            return cls.DEFAULT_SORT_COLUMN, cls.DEFAULT_SORT_DIRECTION
        column, direction = explicit
        return column or cls.DEFAULT_SORT_COLUMN, direction or cls.DEFAULT_SORT_DIRECTION

    @staticmethod
    def _with_sorting(
        params: Iterable[tuple[str, str]], column: str, direction: str
    ) -> list[tuple[str, str]]:
        query_params = list(params)
        without_sorting = [
            (key, value)
            for key, value in query_params
            if key.casefold() not in {"sortcolumn", "sortdirection"}
        ]
        leading = [
            (key, value)
            for key, value in without_sorting
            if key.casefold() in {"q", "locale"}
        ]
        trailing = [
            (key, value)
            for key, value in without_sorting
            if key.casefold() not in {"q", "locale", "startrow"}
        ]
        startrows = [
            (key, value)
            for key, value in without_sorting
            if key.casefold() == "startrow"
        ]
        return (
            leading
            + [("sortColumn", column), ("sortDirection", direction)]
            + startrows
            + trailing
        )

    @staticmethod
    def _single_query_value(
        params: Iterable[tuple[str, str]], key: str
    ) -> Optional[str]:
        values = [value for parameter, value in params if parameter.casefold() == key]
        if len(set(values)) > 1:
            raise ValueError(f"pagination query contains contradictory {key} values")
        return values[0] if values else None

    @classmethod
    def _advertised_total(cls, table: Tag, soup: BeautifulSoup) -> Optional[int]:
        for element in (table, soup.select_one(".results-count"), soup.select_one(".search-results-count")):
            if element is None:
                continue
            for attribute in ("data-total", "data-total-results", "data-count"):
                value = element.get(attribute)
                parsed = cls._parse_integer(value)
                if parsed is not None:
                    return parsed

        range_patterns = (
            r"\b(?:results?|resultados?)\s+\d+\s*(?:[-–—]|a|to)\s*\d+\s+(?:of|de)\s+(\d[\d,.]*)\b",
            r"\b\d+\s*(?:[-–—]|a|to)\s*\d+\s+(?:of|de)\s+(\d[\d,.]*)\b",
        )
        range_texts = [str(table.get("aria-label", ""))]
        range_texts.append(soup.get_text(" ", strip=True))
        for text in range_texts:
            for pattern in range_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    parsed = cls._parse_integer(match.group(1))
                    if parsed is not None:
                        return parsed

        text = soup.get_text(" ", strip=True)
        patterns = (
            r"\b(?:total|results?|resultados?|jobs?|vacantes?)\D{0,12}(\d[\d,.]*)\b",
            r"\b(\d[\d,.]*)\s+(?:results?|resultados?|jobs?|vacantes?)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                parsed = cls._parse_integer(match.group(1))
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _parse_integer(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        digits = re.sub(r"[^0-9]", "", str(value))
        return int(digits) if digits else None

    def _detail_field(self, owner: Tag, field_name: str) -> str:
        values = self._detail_field_values(owner, field_name)
        return values[0] if values else ""

    def _detail_field_values(self, owner: Tag, field_name: str) -> list[str]:
        values: list[str] = []
        property_id = self.PROPERTY_IDS.get(field_name)
        if property_id:
            selector = f'[data-careersite-propertyid="{property_id}"]'
            for element in owner.select(selector):
                if self._nearest_job(element) is owner:
                    value = self._owned_text(element)
                    label = element.select_one(".joblayouttoken-label")
                    if label is not None:
                        value = self._remove_label_prefix(
                            value, self._owned_text(label)
                        )
                    if value:
                        if value not in values:
                            values.append(value)

        wanted = {self._comparison(label) for label in self.DETAIL_PROPERTY_LABELS.get(field_name, ())}
        for label in owner.select(".joblayouttoken-label"):
            if self._nearest_job(label) is not owner:
                continue
            label_text = self._comparison(self._owned_text(label)).rstrip(":")
            if label_text not in wanted:
                continue
            sibling = label.find_next_sibling()
            while isinstance(sibling, Tag):
                if "joblayouttoken-label" in (sibling.get("class") or []):
                    sibling = None
                    break
                if self._nearest_job(sibling) is not owner:
                    sibling = sibling.find_next_sibling()
                    continue
                sibling_text = self._owned_text(sibling)
                if sibling_text:
                    break
                sibling = sibling.find_next_sibling()
            if isinstance(sibling, Tag):
                value = self._owned_text(sibling)
                if value and self._comparison(value) not in wanted:
                    if value not in values:
                        values.append(value)
                    continue
            wrapper = label.parent if isinstance(label.parent, Tag) else None
            if wrapper is not None and wrapper is not owner and self._nearest_job(wrapper) is owner:
                value = self._owned_text(wrapper)
                value = self._remove_label_prefix(value, self._owned_text(label))
                if value:
                    if value not in values:
                        values.append(value)
        return values

    def _description_fields(self, owner: Tag) -> tuple[str, str, str]:
        description_node = None
        property_id = self.PROPERTY_IDS["description"]
        for element in owner.select(f'[data-careersite-propertyid="{property_id}"]'):
            if self._nearest_job(element) is owner:
                description_node = element
                break
        if description_node is None:
            for label in owner.select(".joblayouttoken-label"):
                if self._nearest_job(label) is not owner:
                    continue
                if self._comparison(self._owned_text(label)).rstrip(":") in {
                    self._comparison(value) for value in self.DETAIL_PROPERTY_LABELS["description"]
                }:
                    candidate = self._description_label_candidate(label, owner)
                    if candidate is not None:
                        description_node = candidate
                        break
        if description_node is None:
            return "", "", ""

        container = description_node
        if "jobdescription" not in (description_node.get("class") or []):
            for candidate in description_node.select(".jobdescription"):
                if self._nearest_job(candidate) is owner:
                    container = candidate
                    break
        fragment = BeautifulSoup(str(container), "html.parser")
        for element in fragment.find_all(("script", "style", "nav", "footer", "form")):
            element.decompose()
        for nested_job in fragment.select(self.JOB_OWNER_SELECTOR):
            nested_job.decompose()

        buckets: dict[str, list[str]] = {
            "description": [],
            "requirements": [],
            "responsibilities": [],
        }
        current: Optional[str] = "description"
        root = fragment.find()
        if root is None:
            return "", "", ""
        for text in self._description_segments(root):
            heading_section, remainder = self._section_from_text(text)
            if heading_section is not None:
                current = None if heading_section == "skip" else heading_section
                if remainder and current in buckets and not self._is_boilerplate(remainder):
                    buckets[current].append(remainder)
                elif heading_section == "skip":
                    retained_restriction = self._restriction_text(remainder)
                    if retained_restriction:
                        buckets["requirements"].append(retained_restriction)
                continue
            if current is None:
                retained_restriction = self._restriction_text(text)
                if retained_restriction:
                    buckets["requirements"].append(retained_restriction)
                continue
            if current in buckets and not self._is_boilerplate(text):
                buckets[current].append(text)

        return (
            self._normalise_text(" ".join(buckets["description"])),
            self._normalise_text(" ".join(buckets["requirements"])),
            self._normalise_text(" ".join(buckets["responsibilities"])),
        )

    @classmethod
    def _description_label_candidate(cls, label: Tag, owner: Tag) -> Optional[Tag]:
        parent = label.parent if isinstance(label.parent, Tag) else None
        if parent is not None and parent is not owner:
            return parent if cls._nearest_job(parent) is owner else None

        sibling = label.find_next_sibling()
        while isinstance(sibling, Tag):
            if "joblayouttoken-label" in (sibling.get("class") or []):
                return None
            if cls._nearest_job(sibling) is owner and cls._owned_text(sibling):
                return sibling
            sibling = sibling.find_next_sibling()
        return None

    @classmethod
    def _description_segments(cls, root: Tag) -> list[str]:
        segments: list[str] = []
        cls._collect_description_segments(root, segments)
        return segments

    @classmethod
    def _collect_description_segments(cls, element: Tag, segments: list[str]) -> None:
        direct_parts: list[str] = []
        for child in element.children:
            if isinstance(child, Tag) and child.name in cls.DESCRIPTION_BLOCK_TAGS:
                cls._append_description_segment(direct_parts, segments)
                cls._collect_description_segments(child, segments)
                continue
            text = cls._description_text_without_blocks(child)
            if text:
                direct_parts.append(text)
        cls._append_description_segment(direct_parts, segments)

    @classmethod
    def _description_text_without_blocks(cls, node) -> str:
        if not isinstance(node, Tag):
            return cls._normalise_text(str(node))
        parts = [
            cls._description_text_without_blocks(child)
            for child in node.children
            if not (isinstance(child, Tag) and child.name in cls.DESCRIPTION_BLOCK_TAGS)
        ]
        return cls._normalise_text(" ".join(part for part in parts if part))

    @classmethod
    def _append_description_segment(cls, parts: list[str], segments: list[str]) -> None:
        text = cls._normalise_text(" ".join(parts))
        if text:
            segments.append(text)
        parts.clear()

    def _section_from_text(self, text: str) -> tuple[Optional[str], str]:
        comparison = re.sub(r"^[^\w]+", "", self._comparison(text), flags=re.UNICODE)
        for section, labels in self.SECTION_LABELS.items():
            for label in labels:
                label_comparison = self._heading_comparison(label)
                if comparison != label_comparison and not comparison.startswith(label_comparison):
                    continue
                if len(comparison) > len(label_comparison) and comparison[len(label_comparison)] not in ":.-?!,;":
                    continue
                remainder = self._heading_remainder(text, label_comparison)
                return section, remainder
        return None, ""

    @classmethod
    def _heading_comparison(cls, value: str) -> str:
        comparison = cls._comparison(value)
        return re.sub(r"^[^\w]+|[^\w]+$", "", comparison, flags=re.UNICODE)

    @classmethod
    def _heading_remainder(cls, text: str, label_comparison: str) -> str:
        candidate = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE)
        for end in range(1, len(candidate) + 1):
            if cls._heading_comparison(candidate[:end]) != label_comparison:
                continue
            return candidate[end:].lstrip(" \t:.-?!,;")
        return ""

    @classmethod
    def _is_boilerplate(cls, text: str) -> bool:
        return any(pattern.search(text) for pattern in cls.BOILERPLATE_PATTERNS)

    @classmethod
    def _restriction_text(cls, text: str) -> str:
        retained = []
        for fragment in re.split(r"(?<=[.!?;])\s+", text):
            if cls.RESTRICTION_PATTERN.search(cls._comparison(fragment)):
                retained.append(fragment.strip())
        return cls._normalise_text(" ".join(retained))

    @classmethod
    def _publication_date(cls, soup: BeautifulSoup, owner: Tag) -> Optional[date]:
        meta = owner.select_one('[itemprop="datePosted"]') or soup.select_one('[itemprop="datePosted"]')
        raw = meta.get("content", "") if meta else ""
        for pattern in cls.DATE_PATTERNS:
            match = pattern.search(raw)
            if not match:
                continue
            try:
                values = [int(value) for value in match.groups()]
                if len(values) == 3 and values[0] > 31:
                    return date(values[0], values[1], values[2])
                return date(values[2], values[1], values[0])
            except ValueError:
                return None
        return None

    @classmethod
    def _find_official_job_url(cls, soup: BeautifulSoup) -> str:
        candidates = []
        for link in soup.select('link[rel="canonical"][href], meta[property="og:url"][content]'):
            candidates.append(link.get("href") or link.get("content") or "")
        for candidate in candidates:
            try:
                clean = cls._clean_job_url(candidate)
            except ValueError as exc:
                cls._diagnose(f"malformed canonical URL {candidate!r} ignored: {exc}")
                continue
            if clean:
                return clean
        return ""

    @classmethod
    def _clean_job_url(cls, url: str) -> str:
        if not url:
            return ""
        try:
            parsed = urlparse(urljoin(cls.BASE_URL, str(url)))
        except ValueError:
            raise ValueError(f"malformed URL {url!r}") from None
        if parsed.scheme.lower() not in {"http", "https"} or parsed.netloc.casefold() != cls.OFFICIAL_HOST:
            return ""
        path = re.sub(r"/+", "/", parsed.path)
        if not cls.JOB_PATH_PATTERN.match(path):
            return ""
        path_parts = [part for part in path.split("/") if part]
        if path_parts and path_parts[0].casefold() == "go":
            return ""
        return urlunparse(("https", cls.OFFICIAL_HOST, path.rstrip("/") + "/", "", "", ""))

    @classmethod
    def _job_id(cls, url: str) -> str:
        match = cls.JOB_ID_PATTERN.search(urlparse(url).path)
        return match.group(1) if match else ""

    @classmethod
    def _job_identity(cls, job: IndraJob) -> str:
        return f"id:{job.job_id}" if job.job_id else f"url:{job.url}"

    @classmethod
    def _normalise_work_mode(cls, value: str) -> str:
        normalized = cls._heading_comparison(value)
        return {
            "remote": "REMOTE",
            "remoto": "REMOTE",
            "indiferente": "FLEXIBLE_OR_UNSPECIFIED",
            "hybrid": "HYBRID",
            "hibrido": "HYBRID",
            "on site": "ONSITE",
            "on-site": "ONSITE",
            "onsite": "ONSITE",
            "presencial": "ONSITE",
        }.get(normalized, "UNKNOWN")

    @classmethod
    def _geography_decision(cls, job: IndraJob) -> tuple[bool, str, str]:
        mode = job.work_mode_normalized
        if mode == "REMOTE":
            return True, "accepted", "explicit remote mode"
        if mode == "FLEXIBLE_OR_UNSPECIFIED":
            return True, "accepted", "explicit Indiferente mode"
        location = cls._comparison(job.location_raw)
        explicit_gran_canaria = bool(re.search(r"\bgran\s+canaria\b", location))
        negated = bool(re.search(r"\b(?:no|sin|excepto)\b[^.;,]{0,30}\bgran\s+canaria\b", location))
        unrelated_office_list = bool(
            re.search(
                r"\b(?:oficinas|sedes|ubicaciones|office\s+locations?|offices?)\b",
                location,
            )
        )
        if explicit_gran_canaria and not negated and not unrelated_office_list:
            return True, "accepted", "explicit Gran Canaria job location"
        if mode == "UNKNOWN":
            return False, "unknown", "mode is missing or unrecognised and no explicit Gran Canaria location is present"
        return False, "rejected", f"mode {mode} and location {(job.location_raw or '<missing>')!r} do not meet Indra geographic policy"

    @classmethod
    def _infer_country(cls, location: str) -> str:
        parts = [part.strip() for part in re.split(r"[,;/|]", location) if part.strip()]
        if not parts:
            return ""
        last = parts[-1]
        if re.fullmatch(r"[A-Za-z]{2,3}", last) or cls._comparison(last) in {"espana", "españa", "mexico", "méxico", "portugal", "brasil", "brazil"}:
            return last
        return ""

    @classmethod
    def _comparison(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFD", value.replace("\xa0", " "))
        without_accents = "".join(
            character for character in normalized if unicodedata.category(character) != "Mn"
        )
        return " ".join(without_accents.casefold().split())

    @classmethod
    def _normalise_text(cls, value: str) -> str:
        return " ".join(unicodedata.normalize("NFC", value.replace("\xa0", " ")).split())

    @classmethod
    def _owned_text(cls, element: Tag) -> str:
        return cls._owned_text_excluding(element, (cls.JOB_OWNER_SELECTOR,))

    @classmethod
    def _owned_row_text(cls, element: Tag) -> str:
        return cls._owned_text_excluding(
            element,
            (cls.JOB_OWNER_SELECTOR, "tr.data-row"),
        )

    @classmethod
    def _owned_text_excluding(
        cls, element: Tag, excluded_selectors: tuple[str, ...]
    ) -> str:
        fragment = BeautifulSoup(str(element), "html.parser")
        root = fragment.find()
        if root is None:
            return ""
        for selector in excluded_selectors:
            for nested_element in root.select(selector):
                nested_element.decompose()
        return cls._normalise_text(root.get_text(" ", strip=True))

    @classmethod
    def _remove_label_prefix(cls, value: str, label: str) -> str:
        if cls._comparison(value).startswith(cls._comparison(label)):
            return value[len(label) :].lstrip(" :.-")
        return value

    @classmethod
    def _nearest_job(cls, element: Tag) -> Optional[Tag]:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if cls._matches_job_owner(current):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _matches_job_owner(cls, element: Tag) -> bool:
        return "job" in (element.get("class") or [])

    @classmethod
    def _owned_value(cls, owner: Tag, selector: str) -> str:
        for element in owner.select(selector):
            if cls._nearest_job(element) is owner:
                return cls._owned_text(element)
        return ""

    @classmethod
    def _has_title_field(cls, owner: Tag) -> bool:
        if cls._owned_value(owner, cls.TITLE_SELECTOR):
            return True
        wanted = {cls._comparison(label) for label in cls.DETAIL_PROPERTY_LABELS["title"]}
        for label in owner.select(".joblayouttoken-label"):
            if cls._nearest_job(label) is not owner:
                continue
            if cls._comparison(cls._owned_text(label)).rstrip(":") not in wanted:
                continue
            sibling = label.find_next_sibling()
            if (
                isinstance(sibling, Tag)
                and cls._nearest_job(sibling) is owner
                and cls._owned_text(sibling)
            ):
                return True
        return False

    @classmethod
    def _nearest_search_table(cls, element: Tag) -> Optional[Tag]:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if current.name == "table" and current.get("id") == cls.SEARCH_TABLE_ID:
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _nearest_data_row(cls, element: Tag) -> Optional[Tag]:
        current: Optional[Tag] = element
        while isinstance(current, Tag):
            if current.name == "tr" and "data-row" in (current.get("class") or []):
                return current
            current = current.parent if isinstance(current.parent, Tag) else None
        return None

    @classmethod
    def _owned_row_value(cls, row: Tag, selector: str) -> str:
        for element in row.select(selector):
            if cls._nearest_data_row(element) is row:
                value = cls._owned_row_text(element)
                if value:
                    return value
        return ""

    @classmethod
    def _read_source(cls, source: Union[Path, str, io.BytesIO]) -> str:
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

    @classmethod
    def _to_page(cls, job: IndraJob, page_number: int) -> BOPage:
        return BOPage(
            page_number=page_number,
            text=cls._page_text(job),
            section="Indra Group careers",
            detected_organism=cls.ORGANISM,
            source=cls.SOURCE,
            url=job.url,
        )

    @classmethod
    def _page_text(cls, job: IndraJob) -> str:
        parts = [
            "Source: Indra Group",
            f"Title: {job.title}",
            f"Location: {job.location_raw or 'Unknown'}",
            f"Country: {job.country}" if job.country else "",
            f"Work mode: {job.work_mode_raw or 'Unknown'} ({job.work_mode_normalized})",
            f"Professional profile: {job.professional_profile}" if job.professional_profile else "",
            f"Experience: {job.experience}" if job.experience else "",
            f"Role: {job.role}" if job.role else "",
            f"Requirements: {job.requirements}" if job.requirements else "",
            f"Responsibilities: {job.responsibilities}" if job.responsibilities else "",
            f"Description: {job.description}" if job.description else "",
        ]
        return clean_text(" ".join(part for part in parts if part), lowercase=False).replace("\n\n", " ")

    @classmethod
    def _diagnose(cls, message: str) -> None:
        print(f"      ⚠️ INDRA: {message}")
