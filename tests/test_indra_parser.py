import datetime
import io
from pathlib import Path
from urllib.parse import parse_qsl, quote_plus, urlparse

import pytest
from bs4 import BeautifulSoup

from job_finder.indra_fetcher import IndraFetchError
from job_finder.indra_parser import IndraJob, IndraParseError, IndraParser
from job_finder.keyword_filter import KeywordFilter


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SEARCH_FIXTURE = FIXTURE_DIR / "indra_search_page.html"
REMOTE_FIXTURE = FIXTURE_DIR / "indra_detail_remote.html"
FLEXIBLE_FIXTURE = FIXTURE_DIR / "indra_detail_flexible.html"
OBSERVED_SECTIONS_FIXTURE = FIXTURE_DIR / "indra_detail_observed_sections.html"


def _search_page(rows, links=(), total=None):
    total_attribute = f' data-total="{total}"' if total is not None else ""
    row_html = "".join(
        f"""
        <tr class="data-row">
          <td><a class="jobTitle-link" href="{url}">{title}</a></td>
          <td class="colLocation"><span class="jobLocation">{location}</span></td>
          <td><span class="jobDate">{job_date}</span></td>
        </tr>
        """
        for title, url, location, job_date in rows
    )
    link_html = "".join(f'<a href="{link}">next</a>' for link in links)
    return f"""
    <html><body>
      <table id="searchresults"{total_attribute}>
        <tbody>{row_html}</tbody>
      </table>
      <div class="pagination">{link_html}</div>
    </body></html>
    """


def _detail_html(
    job_id="123",
    title="Ingeniero de Datos",
    location="Madrid, ES",
    mode="Remoto",
    body="Proceso de selección para ingeniería de datos con Python.",
    canonical=None,
):
    canonical = canonical or f"https://careers.indragroup.com/job/example/{job_id}/"
    return f"""
    <html><head><link rel="canonical" href="{canonical}"></head><body>
      <div class="job">
        <div data-careersite-propertyid="title">{title}</div>
        <div data-careersite-propertyid="location">{location}</div>
        <div data-careersite-propertyid="customfield1">Ingeniería de Datos</div>
        <div data-careersite-propertyid="customfield3">Más de 2 años</div>
        <div data-careersite-propertyid="customfield4">{mode}</div>
        <div data-careersite-propertyid="customfield2">T IV</div>
        <div data-careersite-propertyid="description">
          <div class="jobdescription"><h2>Requisitos</h2><p>{body}</p></div>
        </div>
      </div>
    </body></html>
    """


def _detail_html_with_description_markup(markup, **kwargs):
    html = _detail_html(body="__DESCRIPTION_MARKUP__", **kwargs)
    return html.replace(
        '<div class="jobdescription"><h2>Requisitos</h2><p>__DESCRIPTION_MARKUP__</p></div>',
        markup,
    )


class MappingFetcher:
    def __init__(self, pages=None, details=None, failing_terms=()):
        self.pages = pages or {}
        self.details = details or {}
        self.failing_terms = set(failing_terms)
        self.search_calls = []
        self.page_calls = []
        self.detail_calls = []

    def fetch_list(self):
        self.search_calls.append("")
        return self.pages["initial"]

    def fetch_search(self, term):
        self.search_calls.append(term)
        if term in self.failing_terms:
            raise IndraFetchError(f"query {term} timed out")
        return self.pages[term]

    def fetch_page(self, url):
        self.page_calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return page

    def fetch_detail(self, url):
        self.detail_calls.append(url)
        detail = self.details[url]
        if isinstance(detail, Exception):
            raise detail
        return detail


def test_parse_list_keeps_row_owned_fields_and_rejects_invalid_job_links():
    records = IndraParser().parse_list(SEARCH_FIXTURE.read_text(encoding="utf-8"))

    assert [record.job_id for record in records] == ["1362450555", "978243255"]
    assert records[0].title == "781969-01/26"
    assert records[0].location_raw == "Madrid, ES"
    assert records[0].listing_date_raw == "15/09/2026"
    assert records[1].url == "https://careers.indragroup.com/job/Inteligencia-Artificial-Perfil-Junior/978243255/"


def test_search_row_text_excludes_nested_data_row_content_from_parent_fields():
    html = """
    <table id="searchresults">
      <tr class="data-row">
        <td>
          <a class="jobTitle-link" href="/job/outer/1/">Outer title
            <table>
              <tr class="data-row">
                <td><a class="jobTitle-link" href="/job/nested/2/">Nested title</a></td>
              </tr>
            </table>
          </a>
        </td>
        <td>
          <span class="jobLocation">Madrid
            <table>
              <tr class="data-row">
                <td><span class="jobLocation">Gran Canaria</span></td>
              </tr>
            </table>
          </span>
        </td>
        <td>
          <span class="jobDate">15/09/2026
            <table>
              <tr class="data-row">
                <td><span class="jobDate">01/01/2000</span></td>
              </tr>
            </table>
          </span>
        </td>
      </tr>
    </table>
    """

    records = IndraParser().parse_list(html)
    outer = next(record for record in records if record.job_id == "1")

    assert outer.title == "Outer title"
    assert outer.location_raw == "Madrid"
    assert outer.country == ""
    assert outer.listing_date_raw == "15/09/2026"


def test_noresults_suggestions_are_not_query_matches():
    html = """
    <div id="noresults">No results found</div>
    <table id="searchresults"><tr class="data-row">
      <td><a class="jobTitle-link" href="/job/suggestion/1/">Suggested Python</a></td>
      <td class="colLocation"><span class="jobLocation">ES</span></td>
      <td><span class="jobDate">15/09/2026</span></td>
    </tr></table>
    """
    assert IndraParser().parse_list(html) == []


def test_empty_supported_table_stays_empty_and_missing_table_is_structural_error():
    assert IndraParser().parse_list('<table id="searchresults"></table>') == []
    with pytest.raises(IndraParseError, match="searchresults"):
        IndraParser().parse_list("<html><body><p>Indra Group</p></body></html>")


def test_advertised_total_prefers_result_range_over_page_start_number():
    html = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")]
    ).replace(
        '<table id="searchresults">',
        '<table id="searchresults" aria-label="Resultados de búsqueda. Página 1 de 30, resultados 1 a 25 de 738">',
    )

    parsed = IndraParser()._parse_search_page(
        html,
        "https://careers.indragroup.com/search/?q=&locale=es_ES",
        "",
    )

    assert parsed.advertised_total == 738


def test_detail_extracts_metadata_sections_unicode_and_cleans_canonical_url():
    parser = IndraParser()
    job = parser.parse_detail_job(REMOTE_FIXTURE.read_text(encoding="utf-8"))

    assert job.job_id == "1362450555"
    assert job.title == "781969-01/26"
    assert job.location_raw == "Madrid, ES"
    assert job.work_mode_raw == "Remoto"
    assert job.work_mode_normalized == "REMOTE"
    assert job.experience == "Más de 2 años de experiencia"
    assert "Python" in job.requirements
    assert "pipelines" in job.responsibilities
    assert "beneficios corporativos" not in job.description
    assert job.url == "https://careers.indragroup.com/job/Madrid-781969-0126/1362450555/"
    assert "Work mode: Remoto (REMOTE)" in parser.parse_detail(
        REMOTE_FIXTURE.read_text(encoding="utf-8")
    )


def test_description_traversal_emits_nested_owned_text_once_in_final_page():
    parser = IndraParser()
    job = parser.parse_detail_job(
        _detail_html_with_description_markup(
            "<div><div>Unique responsibility</div></div>",
        )
    )
    page = parser._to_page(job, 1)

    assert job.description == "Unique responsibility"
    assert page.text.count("Unique responsibility") == 1


def test_description_traversal_excludes_bounded_benefits_boilerplate_from_all_fields():
    parser = IndraParser()
    job = parser.parse_detail_job(
        _detail_html_with_description_markup(
            "<div><div>Benefits</div><div>Corporate Python recruitment selection</div></div>",
        )
    )
    page = parser._to_page(job, 1)
    emitted_fields = (
        job.description,
        job.requirements,
        job.responsibilities,
        page.text,
    )

    assert all("Benefits" not in field for field in emitted_fields)
    assert all("Corporate Python recruitment selection" not in field for field in emitted_fields)
    assert KeywordFilter().search_page(page) == []


def test_description_traversal_accepts_inline_jobdescription_container():
    parser = IndraParser()
    job = parser.parse_detail_job(
        _detail_html_with_description_markup(
            '<span class="jobdescription">Must preserve this job qualification</span>',
        )
    )
    page = parser._to_page(job, 1)

    assert job.description == "Must preserve this job qualification"
    assert "Must preserve this job qualification" in page.text


def test_description_traversal_preserves_inline_content_and_section_boundaries():
    parser = IndraParser()
    job = parser.parse_detail_job(
        _detail_html_with_description_markup(
            """
            <div>Introductory job context.</div>
            <h2>¿Qué harás?</h2>
            <div><p><span>Unique responsibility</span> <strong>with formatting</strong><br>and direct text.</p></div>
            <h2>Lo que te ofrecemos</h2>
            <div><p>Corporate Python recruitment selection</p></div>
            <h2>Requisitos imprescindibles</h2>
            <ul><li><strong>Real Python qualification</strong></li></ul>
            """
        )
    )
    page = parser._to_page(job, 1)

    assert "Introductory job context." in job.description
    assert job.responsibilities == "Unique responsibility with formatting and direct text."
    assert job.requirements == "Real Python qualification"
    assert "Corporate Python recruitment selection" not in page.text
    assert page.text.count("Unique responsibility") == 1
    assert page.text.count("Real Python qualification") == 1


def test_observed_sections_are_bounded_owned_and_emitted_without_boilerplate():
    parser = IndraParser()
    job = parser.parse_detail_job(OBSERVED_SECTIONS_FIXTURE.read_text(encoding="utf-8"))

    emitted_fields = (
        job.title,
        job.location_raw,
        job.country,
        job.work_mode_raw,
        job.professional_profile,
        job.experience,
        job.role,
        job.description,
        job.requirements,
        job.responsibilities,
    )
    page = parser._to_page(job, 1)

    assert "Indra Group: este puesto diseña servicios" in job.description
    assert "Diseñar pipelines de datos" in job.responsibilities
    assert "Experiencia práctica en Python y SQL" in job.requirements
    assert "residencia contractual" in job.requirements
    assert "requieren disponibilidad para guardias" in job.requirements
    assert job.work_mode_raw == "Híbrido"
    assert job.location_raw == "Madrid, ES"
    assert job.work_mode_normalized == "HYBRID"
    assert not IndraParser.is_geographically_eligible(job)
    assert all("Beneficios corporativos" not in field for field in emitted_fields)
    assert all("proceso incluye entrevistas" not in field for field in emitted_fields)
    assert all("Nested unrelated role" not in field for field in emitted_fields)
    assert all("Gran Canaria" not in field for field in emitted_fields)
    assert "Beneficios corporativos" not in page.text
    assert "proceso incluye entrevistas" not in page.text
    assert "Nested unrelated role" not in page.text
    assert "Location: Madrid, ES" in page.text
    assert "Work mode: Híbrido (HYBRID)" in page.text
    assert job.responsibilities.count("Diseñar pipelines de datos") == 1


def test_nested_label_fallback_fields_belong_to_the_nearest_job_record():
    html = """
    <html><head><link rel="canonical" href="https://careers.indragroup.com/job/labels/445/" /></head>
    <body><div class="job">
      <div class="joblayouttoken-label">Título</div><div>Outer role</div>
      <div class="joblayouttoken-label">Ubicación</div><div>Madrid, ES</div>
      <div class="joblayouttoken-label">Modalidad del puesto</div><div>Híbrido</div>
      <div class="joblayouttoken-label">Descripción</div>
      <div class="jobdescription"><p>Outer description with Python.</p>
        <div class="job">
          <div class="joblayouttoken-label">Título</div><div>Nested role</div>
          <div class="joblayouttoken-label">Ubicación</div><div>Gran Canaria</div>
          <div class="joblayouttoken-label">Modalidad del puesto</div><div>Remoto</div>
          <div class="joblayouttoken-label">Descripción</div><div>Nested description.</div>
        </div>
      </div>
    </div></body></html>
    """

    job = IndraParser().parse_detail_job(html)

    assert job.title == "Outer role"
    assert job.location_raw == "Madrid, ES"
    assert job.work_mode_raw == "Híbrido"
    assert job.description == "Outer description with Python."
    assert not IndraParser.is_geographically_eligible(job)


def test_detail_normalizes_html_entities_and_nonbreaking_spaces_without_losing_raw_mode():
    html = _detail_html(
        title="T&eacute;cnico&nbsp;de&nbsp;Datos",
        location="Gran Canaria&nbsp;, ES",
        mode="H&iacute;brido",
    )

    job = IndraParser().parse_detail_job(html)

    assert job.title == "Técnico de Datos"
    assert job.location_raw == "Gran Canaria , ES"
    assert job.work_mode_raw == "Híbrido"
    assert job.work_mode_normalized == "HYBRID"
    assert IndraParser.is_geographically_eligible(job)


def test_label_fallback_supports_valid_wrapping_changes():
    job = IndraParser().parse_detail_job(FLEXIBLE_FIXTURE.read_text(encoding="utf-8"))

    assert job.title == "Inteligencia Artificial - Perfil Junior"
    assert job.location_raw == "ES"
    assert job.work_mode_raw == "Indiferente"
    assert job.work_mode_normalized == "FLEXIBLE_OR_UNSPECIFIED"
    assert job.professional_profile == "Inteligencia Artificial"
    assert IndraParser.has_supported_structure(FLEXIBLE_FIXTURE.read_text(encoding="utf-8"))


def test_description_label_fallback_does_not_traverse_unrelated_job_fields():
    html = """
    <link rel="canonical" href="https://careers.indragroup.com/job/labels/445/">
    <div class="job">
      <div class="joblayouttoken-label">Título</div><div>Outer role</div>
      <div class="joblayouttoken-label">Descripción</div>
      <div class="joblayouttoken-label">Ubicación</div><div>Madrid, ES</div>
      <div class="joblayouttoken-label">Modalidad del puesto</div><div>Presencial</div>
    </div>
    """

    job = IndraParser().parse_detail_job(html)

    assert job.title == "Outer role"
    assert job.location_raw == "Madrid, ES"
    assert job.description == ""
    assert job.requirements == ""
    assert job.responsibilities == ""


def test_malformed_canonical_is_ignored_when_listing_fallback_is_valid(capsys):
    html = _detail_html(canonical="http://[broken")

    job = IndraParser().parse_detail_job(
        html,
        fallback_url="https://careers.indragroup.com/job/example/123/",
    )

    assert job.job_id == "123"
    assert job.url == "https://careers.indragroup.com/job/example/123/"
    assert "malformed canonical" in capsys.readouterr().out.casefold()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("Not remote", "UNKNOWN"),
        ("Non-remote", "UNKNOWN"),
        ("No remoto", "UNKNOWN"),
        ("Remoto / Presencial", "UNKNOWN"),
        ("Remote / Hybrid", "UNKNOWN"),
        ("Remote", "REMOTE"),
        ("Remoto", "REMOTE"),
        ("Indiferente", "FLEXIBLE_OR_UNSPECIFIED"),
    ],
)
def test_single_structured_work_mode_requires_an_explicit_unambiguous_value(mode, expected):
    job = IndraParser().parse_detail_job(_detail_html(location="Madrid", mode=mode))

    assert job.work_mode_raw == mode
    assert job.work_mode_normalized == expected
    assert IndraParser.is_geographically_eligible(job) is (expected in {"REMOTE", "FLEXIBLE_OR_UNSPECIFIED"})


def test_shared_title_rejection_is_reused_before_detail_fetch():
    class RejectingFilter:
        @staticmethod
        def should_reject_title(title):
            return title == "Training role"

    html = _search_page(
        [("Training role", "/job/training/111/", "ES", "15/09/2026")]
    )
    assert IndraParser(keyword_filter=RejectingFilter()).parse_list(html) == []


@pytest.mark.parametrize(
    ("location", "mode", "expected"),
    [
        ("ES", "Remoto", True),
        ("ES", "Indiferente", True),
        ("Madrid", "Híbrido", False),
        ("Las Palmas de Gran Canaria", "Híbrido", True),
        ("Gran Canaria", "Presencial", True),
        ("Mexico", "Remoto", True),
        ("ES", "", False),
        ("ES", "Híbrido", False),
        ("Las Palmas", "Híbrido", False),
        ("LPGC", "Presencial", False),
    ],
)
def test_geographic_policy_uses_mode_or_explicit_gran_canaria(location, mode, expected):
    job = IndraParser().parse_detail_job(
        _detail_html(location=location, mode=mode),
    )
    assert IndraParser.is_geographically_eligible(job) is expected


def test_geographic_policy_does_not_read_unrelated_description_prose():
    job = IndraParser().parse_detail_job(
        _detail_html(
            location="Madrid",
            mode="Presencial",
            body="El equipo trabaja con clientes de Gran Canaria, pero el puesto es en Madrid.",
        )
    )
    assert IndraParser.is_geographically_eligible(job) is False


@pytest.mark.parametrize(
    "location",
    [
        "Oficinas: Madrid, Gran Canaria, Barcelona",
        "Office locations: Madrid; Gran Canaria",
        "Sin Gran Canaria",
    ],
)
def test_geographic_policy_rejects_unrelated_or_negated_gran_canaria(location):
    job = IndraParser().parse_detail_job(
        _detail_html(location=location, mode="Presencial")
    )

    assert IndraParser.is_geographically_eligible(job) is False


def test_detail_failure_isolated_and_total_mismatch_reported(capsys):
    page = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        total=2,
    )
    fetcher = MappingFetcher(
        pages={"initial": page},
        details={
            "https://careers.indragroup.com/job/one/101/": IndraFetchError("detail timeout"),
        },
    )

    assert IndraParser(fetcher=fetcher).scan([]) == []
    output = capsys.readouterr().out.casefold()
    assert "incomplete" in output
    assert "detail timeout" in output


def test_scan_quarantines_canonical_identity_mismatch_and_continues(capsys):
    page = _search_page(
        [
            ("Mismatch", "/job/mismatch/123/", "ES", "15/09/2026"),
            ("Valid", "/job/valid/456/", "ES", "15/09/2026"),
        ],
        total=2,
    )
    mismatch_url = "https://careers.indragroup.com/job/mismatch/123/"
    valid_url = "https://careers.indragroup.com/job/valid/456/"
    fetcher = MappingFetcher(
        pages={"initial": page},
        details={
            mismatch_url: _detail_html(
                job_id="999",
                title="Mismatch detail",
                canonical="https://careers.indragroup.com/job/mismatch/999/",
            ),
            valid_url: _detail_html(job_id="456", title="Valid", canonical=valid_url),
        },
    )

    result = IndraParser(fetcher=fetcher).scan([])

    assert [page.url for page in result] == [valid_url]
    assert fetcher.detail_calls == [mismatch_url, valid_url]
    assert "canonical ID 999 disagrees with listing ID 123" in capsys.readouterr().out


def test_scan_paginates_from_real_links_without_short_page_early_stop():
    page_one_url = "https://careers.indragroup.com/search/?q=&locale=es_ES"
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    page_three_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=50"
    rows = [
        ("One", "/job/one/101/", "ES", "15/09/2026"),
        ("Two", "/job/two/102/", "ES", "15/09/2026"),
    ]
    pages = {
        "initial": _search_page(rows[:1], links=["/search/?q=&locale=es_ES&startrow=25"], total=3),
        page_two_url: _search_page(rows[1:], links=[page_three_url], total=3),
        page_three_url: _search_page(
            [("Three", "/job/three/103/", "ES", "15/09/2026")], total=3
        ),
    }
    details = {
        f"https://careers.indragroup.com/job/{name}/{job_id}/": _detail_html(
            job_id=job_id, title=name, mode="Remoto"
        )
        for name, job_id in [("one", "101"), ("two", "102"), ("three", "103")]
    }
    fetcher = MappingFetcher(pages=pages, details=details)
    pages_result = IndraParser(fetcher=fetcher).scan([])

    assert len(pages_result) == 3
    assert len(fetcher.detail_calls) == 3
    assert page_two_url in fetcher.page_calls
    assert page_three_url in fetcher.page_calls


def test_scan_accounts_for_duplicate_scheduled_links_as_one_complete_page():
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    page_three_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=50"
    page_one = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        links=[page_two_url, page_three_url],
        total=3,
    )
    pages = {
        "initial": page_one,
        page_two_url: _search_page(
            [("Two", "/job/two/102/", "ES", "15/09/2026")],
            links=[page_three_url],
            total=3,
        ),
        page_three_url: _search_page(
            [("Three", "/job/three/103/", "ES", "15/09/2026")],
            total=3,
        ),
    }
    details = {
        f"https://careers.indragroup.com/job/{name}/{job_id}/": _detail_html(
            job_id=job_id, title=name, canonical=f"https://careers.indragroup.com/job/{name}/{job_id}/"
        )
        for name, job_id in [("one", "101"), ("two", "102"), ("three", "103")]
    }

    fetcher = MappingFetcher(pages=pages, details=details)
    result = IndraParser(fetcher=fetcher).scan([])

    assert {page.url for page in result} == set(details)
    assert fetcher.page_calls.count(page_three_url) == 1


def test_scan_does_not_mark_an_ordinary_navigation_cycle_incomplete(capsys):
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    page_one = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        links=[page_two_url],
        total=2,
    )
    page_two = _search_page(
        [("Two", "/job/two/102/", "ES", "15/09/2026")],
        links=["/search/?q=&locale=es_ES&startrow=0"],
        total=2,
    )
    details = {
        f"https://careers.indragroup.com/job/{name}/{job_id}/": _detail_html(
            job_id=job_id, title=name, canonical=f"https://careers.indragroup.com/job/{name}/{job_id}/"
        )
        for name, job_id in [("one", "101"), ("two", "102")]
    }

    fetcher = MappingFetcher(pages={"initial": page_one, page_two_url: page_two}, details=details)
    result = IndraParser(fetcher=fetcher).scan([])

    assert {page.url for page in result} == set(details)
    assert "status=complete" in capsys.readouterr().out


def test_scan_does_not_refetch_explicit_default_sort_first_page():
    default_first_url = (
        "https://careers.indragroup.com/search/?q=&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=desc&startrow=0"
    )
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&sortColumn=referencedate&sortDirection=desc&startrow=25"
    page_one = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        links=[default_first_url, page_two_url],
        total=2,
    )
    pages = {
        "initial": page_one,
        default_first_url: page_one,
        page_two_url: _search_page(
            [("Two", "/job/two/102/", "ES", "15/09/2026")],
            total=2,
        ),
    }
    details = {
        f"https://careers.indragroup.com/job/{name}/{job_id}/": _detail_html(
            job_id=job_id, title=name, canonical=f"https://careers.indragroup.com/job/{name}/{job_id}/"
        )
        for name, job_id in [("one", "101"), ("two", "102")]
    }

    fetcher = MappingFetcher(pages=pages, details=details)
    result = IndraParser(fetcher=fetcher).scan([])

    assert {page.url for page in result} == set(details)
    assert default_first_url not in fetcher.page_calls
    assert page_two_url in fetcher.page_calls


def test_pagination_uses_current_url_and_rejects_narrower_filter_links(capsys):
    parser = IndraParser()
    current_url = "https://careers.indragroup.com/search/?q=Python&locale=es_ES&startrow=25"

    assert parser._normalise_pagination_url("?startrow=50", current_url, "Python") == (
        "https://careers.indragroup.com/search/?startrow=50&q=Python&locale=es_ES"
    )
    assert parser._pagination_urls(
        BeautifulSoup(
            '<div class="pagination"><a href="?startrow=50&location=Madrid">next</a></div>',
            "html.parser",
        ),
        current_url,
        "Python",
    ) == []
    assert "narrower filter" in capsys.readouterr().out


def test_pagination_inherits_explicit_sorting_and_accepts_matching_sorting():
    parser = IndraParser()
    current_url = (
        "https://careers.indragroup.com/search/?q=Python&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=asc&startrow=25"
    )
    expected = {
        "q": "Python",
        "locale": "es_ES",
        "sortcolumn": "referencedate",
        "sortdirection": "asc",
        "startrow": "50",
    }

    inherited = parser._normalise_pagination_url("?startrow=50", current_url, "Python")
    matching = parser._normalise_pagination_url(
        "?startrow=50&sortColumn=referencedate&sortDirection=asc",
        current_url,
        "Python",
    )

    assert dict((key.casefold(), value) for key, value in parse_qsl(urlparse(inherited).query)) == expected
    assert dict((key.casefold(), value) for key, value in parse_qsl(urlparse(matching).query)) == expected


def test_pagination_rejects_conflicting_sorting_with_diagnostic(capsys):
    parser = IndraParser()
    current_url = (
        "https://careers.indragroup.com/search/?q=Python&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=asc&startrow=25"
    )

    urls = parser._pagination_urls(
        BeautifulSoup(
            '<div class="pagination"><a href="?startrow=50&sortColumn=salary&sortDirection=desc">next</a></div>',
            "html.parser",
        ),
        current_url,
        "Python",
    )

    assert urls == []
    output = capsys.readouterr().out.casefold()
    assert "conflicting sort" in output


def test_page_identity_equates_omitted_and_explicit_default_sorting():
    omitted = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    explicit = (
        "https://careers.indragroup.com/search/?q=&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=desc&startrow=25"
    )

    assert IndraParser._page_identity(omitted, "") == IndraParser._page_identity(explicit, "")


def test_scan_keeps_one_sorting_when_a_later_link_omits_sorting(capsys):
    page_two_url = (
        "https://careers.indragroup.com/search/?q=&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=desc&startrow=25"
    )
    page_three_url = (
        "https://careers.indragroup.com/search/?q=&locale=es_ES&"
        "sortColumn=referencedate&sortDirection=desc&startrow=50"
    )
    page_one = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        links=[page_two_url],
        total=3,
    )
    pages = {
        "initial": page_one,
        page_two_url: _search_page(
            [("Two", "/job/two/102/", "ES", "15/09/2026")],
            links=["?startrow=50"],
            total=3,
        ),
        page_three_url: _search_page(
            [("Three", "/job/three/103/", "ES", "15/09/2026")],
            total=3,
        ),
    }
    details = {
        f"https://careers.indragroup.com/job/{name}/{job_id}/": _detail_html(
            job_id=job_id,
            title=name,
            canonical=f"https://careers.indragroup.com/job/{name}/{job_id}/",
        )
        for name, job_id in [("one", "101"), ("two", "102"), ("three", "103")]
    }

    fetcher = MappingFetcher(pages=pages, details=details)
    result = IndraParser(fetcher=fetcher).scan([])

    assert {page.url for page in result} == set(details)
    assert fetcher.page_calls == [page_two_url, page_three_url]
    assert "status=complete" in capsys.readouterr().out


def test_scan_marks_semantically_repeated_results_even_when_html_changes(capsys):
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    repeated_page = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        total=2,
    ).replace("</body>", '<div data-incidental="changed">updated</div></body>')
    fetcher = MappingFetcher(
        pages={
            "initial": _search_page(
                [("One", "/job/one/101/", "ES", "15/09/2026")],
                links=[page_two_url],
                total=2,
            ),
            page_two_url: repeated_page,
        },
        details={
            "https://careers.indragroup.com/job/one/101/": _detail_html(
                job_id="101", title="One", canonical="https://careers.indragroup.com/job/one/101/"
            )
        },
    )

    result = IndraParser(fetcher=fetcher).scan([])

    assert [page.url for page in result] == [
        "https://careers.indragroup.com/job/one/101/"
    ]
    output = capsys.readouterr().out.casefold()
    assert "repeated results" in output
    assert "status=incomplete" in output


def test_scan_counts_intentionally_title_rejected_records_before_total_check(capsys):
    class RejectingFilter:
        @staticmethod
        def should_reject_title(title):
            return title == "Training role"

    page = _search_page(
        [
            ("Training role", "/job/training/111/", "ES", "15/09/2026"),
            ("Valid", "/job/valid/112/", "ES", "15/09/2026"),
        ],
        total=2,
    )
    valid_url = "https://careers.indragroup.com/job/valid/112/"
    fetcher = MappingFetcher(
        pages={"initial": page},
        details={valid_url: _detail_html(job_id="112", title="Valid", canonical=valid_url)},
    )

    result = IndraParser(fetcher=fetcher, keyword_filter=RejectingFilter()).scan([])

    assert [page.url for page in result] == [
        "https://careers.indragroup.com/job/valid/112/"
    ]
    assert "status=complete" in capsys.readouterr().out


def test_scan_continues_known_pages_after_failure_and_stops_cycles(capsys):
    page_two_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=25"
    page_three_url = "https://careers.indragroup.com/search/?q=&locale=es_ES&startrow=50"
    page_one = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        links=[page_two_url, page_three_url],
        total=2,
    )
    pages = {
        "initial": page_one,
        page_two_url: IndraFetchError("page timeout"),
        page_three_url: _search_page(
            [("Two", "/job/two/102/", "ES", "15/09/2026")],
            links=["/search/?q=&locale=es_ES&startrow=0"],
            total=2,
        ),
    }
    details = {
        "https://careers.indragroup.com/job/one/101/": _detail_html(
            job_id="101", title="One", canonical="https://careers.indragroup.com/job/one/101/"
        ),
        "https://careers.indragroup.com/job/two/102/": _detail_html(
            job_id="102", title="Two", canonical="https://careers.indragroup.com/job/two/102/"
        ),
    }
    fetcher = MappingFetcher(pages=pages, details=details)
    result = IndraParser(fetcher=fetcher).scan([])

    assert {page.url for page in result} == set(details)
    output = capsys.readouterr().out
    assert "page timeout" in output
    assert "incomplete" in output.casefold()


def test_scan_deduplicates_terms_ids_and_locale_tracking_variants_before_details():
    page = _search_page(
        [
            (
                "One",
                "/job/one/101/?locale=es_ES&utm_source=one",
                "ES",
                "15/09/2026",
            )
        ],
        total=1,
    )
    details = {
        "https://careers.indragroup.com/job/one/101/": _detail_html(job_id="101", title="One")
    }
    fetcher = MappingFetcher(pages={"Python": page, "Artificial Intelligence": page}, details=details)
    result = IndraParser(fetcher=fetcher).scan(
        [" Python ", "Python", 'Artificial Intelligence', "Artificial Intelligence"]
    )

    assert fetcher.search_calls == ["Python", "Artificial Intelligence"]
    assert len(fetcher.detail_calls) == 1
    assert len(result) == 1


def test_scan_rejects_category_urls_and_deduplicates_real_job_links():
    category_url = "https://careers.indragroup.com/go/Mobility_ES/9572055/"
    job_url = "https://careers.indragroup.com/job/Mobility/9572055/"
    division_job_url = "https://careers.indragroup.com/technology/job/Mobility/9572055/"
    category_page = _search_page(
        [
            ("Category", "/go/Mobility_ES/9572055/?locale=es_ES", "ES", "15/09/2026"),
            ("Mobility", "/job/Mobility/9572055/?utm_source=search", "ES", "15/09/2026"),
            ("Mobility duplicate", "/technology/job/Mobility/9572055/?locale=es_ES", "ES", "15/09/2026"),
        ],
        total=1,
    )
    details = {
        job_url: _detail_html(
            job_id="9572055",
            title="Mobility",
            canonical=job_url,
        ),
    }
    fetcher = MappingFetcher(
        pages={"initial": category_page},
        details=details,
    )

    parser = IndraParser(fetcher=fetcher)
    records = parser.parse_list(category_page)
    result = parser.scan([])

    assert [record.url for record in records] == [job_url, division_job_url]
    assert IndraParser._clean_job_url(category_url) == ""
    assert fetcher.detail_calls == [job_url]
    assert result[0].url == job_url


def test_contradictory_structured_modes_remain_raw_and_become_unknown(capsys):
    html = _detail_html(job_id="505", title="Conflicting", mode="Remoto")
    html = html.replace(
        '<div data-careersite-propertyid="customfield4">Remoto</div>',
        '<div data-careersite-propertyid="customfield4">Remoto</div>'
        '<div data-careersite-propertyid="customfield4">Híbrido</div>',
    )

    job = IndraParser().parse_detail_job(html)

    assert job.work_mode_raw == "Remoto | Híbrido"
    assert job.work_mode_normalized == "UNKNOWN"
    assert "contradictory" in capsys.readouterr().out.casefold()


def test_offline_detail_reuses_shared_title_rules_and_relative_it_override(tmp_path):
    absolute = tmp_path / "absolute.html"
    absolute.write_text(
        _detail_html(title="Contrato Formativo Informática"),
        encoding="utf-8",
    )
    relative = tmp_path / "relative.html"
    relative.write_text(
        _detail_html(title="Mantenimiento de Sistemas Informáticos"),
        encoding="utf-8",
    )
    parser = IndraParser(keyword_filter=KeywordFilter())

    assert parser.parse(absolute) == []
    assert len(parser.parse(relative)) == 1


def test_scan_reapplies_title_filter_to_detail_content():
    page = _search_page([("Visible listing", "/job/visible/113/", "ES", "15/09/2026")], total=1)
    detail_url = "https://careers.indragroup.com/job/visible/113/"
    fetcher = MappingFetcher(
        pages={"initial": page},
        details={
            detail_url: _detail_html(
                job_id="113",
                title="Contrato Formativo Informática",
                canonical=detail_url,
            )
        },
    )

    assert IndraParser(fetcher=fetcher, keyword_filter=KeywordFilter()).scan([]) == []


def test_scan_continues_after_one_query_retrieval_failure():
    page = _search_page(
        [("One", "/job/one/101/", "ES", "15/09/2026")],
        total=1,
    )
    fetcher = MappingFetcher(
        pages={"Python": page, "Broken": page},
        details={"https://careers.indragroup.com/job/one/101/": _detail_html(job_id="101", title="One")},
        failing_terms={"Broken"},
    )

    result = IndraParser(fetcher=fetcher).scan(["Broken", "Python"])

    assert len(result) == 1
    assert fetcher.search_calls == ["Broken", "Python"]


def test_offline_detail_parsing_makes_zero_network_calls(tmp_path):
    class NoNetworkFetcher:
        def __getattr__(self, name):
            raise AssertionError(f"network method called: {name}")

    local_file = tmp_path / "indra_detail.html"
    local_file.write_text(REMOTE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    result = IndraParser(fetcher=NoNetworkFetcher()).parse(local_file)

    assert len(result) == 1
    assert result[0].source == "INDRA"


def test_offline_listing_does_not_infer_missing_mode_or_fetch_details(capsys):
    class NoNetworkFetcher:
        def __getattr__(self, name):
            raise AssertionError(f"network method called: {name}")

    result = IndraParser(fetcher=NoNetworkFetcher()).parse(
        io.BytesIO(SEARCH_FIXTURE.read_bytes())
    )

    assert result == []
    assert "modality" in capsys.readouterr().out.casefold()
