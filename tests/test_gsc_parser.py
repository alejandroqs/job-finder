import datetime
import io
from pathlib import Path

import pytest

from job_finder import gsc_parser
from job_finder.gsc_parser import GSCParser
from job_finder.keyword_filter import KeywordFilter


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gsc_ofertas_de_empleo.html"


def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def make_card(title: str, href: str = "/gsc/portfolio_page/test/") -> str:
    return f"""
    <article class="mix portfolio_category_41 default">
      <div class="image_holder"><a href="/decorative">01/01/2030 Informática</a></div>
      <div class="portfolio_description">
        <h5 class="portfolio_title entry_title"><a href="{href}">{title}</a></h5>
        <span class="project_category">Convocatoria informática</span>
      </div>
    </article>
    """


def wrap_cards(cards: str, include_section: bool = True, include_holder: bool = True) -> str:
    holder = (
        '<div class="projects_holder portfolio_main_holder">'
        f"{cards}"
        "</div>"
        if include_holder
        else ""
    )
    return f'<div id="seleccion">{holder}</div>' if include_section else holder


MALFORMED_URL_HTML = wrap_cards(
    make_card(
        "01/09/2026 BASES DESARROLLADOR/A",
        "https://www.gsccanarias.com/gsc/portfolio_page/valid-one/",
    )
    + make_card("01/09/2026 BASES PROGRAMADOR/A", "http://[broken")
    + make_card(
        "01/09/2026 BASES INGENIERO/A",
        "https://www.gsccanarias.com/gsc/portfolio_page/valid-three/",
    )
)


def test_parser_preserves_owned_title_date_and_links_and_filters_notices():
    pages = GSCParser().parse(FIXTURE_PATH, target_date=datetime.date(2026, 6, 22))

    assert [page.page_number for page in pages] == [1, 2]
    assert [page.source for page in pages] == ["GSC"] * 2
    assert [page.detected_organism for page in pages] == [
        "Gestión de Servicios para la Salud y Seguridad en Canarias"
    ] * 2
    assert pages[0].text.startswith("18-06-2026 BASES TÉCNICO III")
    assert pages[0].url == "https://www.gsccanarias.com/gsc/portfolio_page/utic-622/"
    assert pages[1].url == "https://www.gsccanarias.com/gsc/portfolio_page/shared-process/"
    assert "RESULTADOS" not in " ".join(page.text for page in pages)
    assert "RELACIÓN" not in " ".join(page.text for page in pages)
    assert "ANULA" not in " ".join(page.text for page in pages)


@pytest.mark.parametrize(
    ("publication", "reference", "included"),
    [
        ("01/09/2026", datetime.date(2026, 9, 1), True),
        ("01/09/2026", datetime.date(2026, 9, 8), True),
        ("01/09/2026", datetime.date(2026, 9, 9), False),
        ("10/09/2026", datetime.date(2026, 9, 9), False),
    ],
)
def test_inclusive_publication_plus_seven_day_window(publication, reference, included):
    html = wrap_cards(make_card(f"{publication} BASES DESARROLLADOR/A"))

    pages = GSCParser().parse_list(html, target_date=reference)

    assert bool(pages) is included


def test_parser_accepts_hyphen_format_and_handles_rollover_and_leap_day():
    html = wrap_cards(
        make_card("31-12-2025 BASES DESARROLLADOR/A", "/year-end")
        + make_card("29/02/2024 BASES DESARROLLADOR/A", "/leap")
    )

    records = GSCParser().parse_list(html, target_date=datetime.date(2026, 1, 1))
    leap_records = GSCParser().parse_list(
        html, target_date=datetime.date(2024, 3, 7)
    )

    assert records[0].inferred_end_date == datetime.date(2026, 1, 7)
    assert leap_records[0].publication_date == datetime.date(2024, 2, 29)
    assert leap_records[0].inferred_end_date == datetime.date(2024, 3, 7)


@pytest.mark.parametrize(
    "title",
    [
        "BASES DESARROLLADOR/A",
        "01/09/26 BASES DESARROLLADOR/A",
        "2026/09/01 BASES DESARROLLADOR/A",
        "01/09-2026 BASES DESARROLLADOR/A",
        "32/09/2026 BASES DESARROLLADOR/A",
        "01/13/2026 BASES DESARROLLADOR/A",
        "BASES DESARROLLADOR/A PUBLICADO 02/09/2026",
    ],
)
def test_invalid_or_ambiguous_publication_prefix_is_skipped(title, capsys):
    pages = GSCParser().parse_list(
        wrap_cards(make_card(title)), target_date=datetime.date(2026, 9, 1)
    )

    assert pages == []
    assert "GSC" in capsys.readouterr().out


def test_omitted_target_date_uses_frozen_today(monkeypatch):
    class FrozenDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 8)

    monkeypatch.setattr(gsc_parser, "date", FrozenDate)
    html = wrap_cards(make_card("01/09/2026 BASES DESARROLLADOR/A"))

    assert GSCParser().parse_list(html)  # 1 September through 8 September, inclusive


def test_parser_reports_missing_section_holder_empty_holder_and_malformed_cards(capsys):
    parser = GSCParser()

    assert parser.parse_list("<html><body><p>GSC</p></body></html>") == []
    assert "selection section" in capsys.readouterr().out

    assert parser.parse_list(wrap_cards("", include_holder=False)) == []
    assert "selection holder" in capsys.readouterr().out

    assert parser.parse_list(wrap_cards("")) == []
    assert "supported but empty" in capsys.readouterr().out

    malformed = wrap_cards(
        '<article class="mix"><div class="portfolio_description">'
        '<h5 class="portfolio_title entry_title">No owned title anchor</h5>'
        "</div></article>"
        + make_card("01/09/2026 BASES DESARROLLADOR/A")
    )
    pages = parser.parse_list(malformed, target_date=datetime.date(2026, 9, 1))

    assert len(pages) == 1
    assert "card 1" in capsys.readouterr().out


def test_empty_selection_does_not_consume_another_holder(capsys):
    html = """
    <div id="seleccion">
      <div class="projects_holder portfolio_main_holder"></div>
    </div>
    <div class="projects_holder portfolio_main_holder">
      <article><h5 class="portfolio_title entry_title">
        <a href="/outside">01/09/2026 BASES DESARROLLADOR/A</a>
      </h5></article>
    </div>
    """

    assert GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1)) == []
    assert "supported but empty" in capsys.readouterr().out


def test_nested_and_decorative_metadata_cannot_supply_record_fields_or_it_findings():
    html = """
    <div id="seleccion">
      <div class="projects_holder portfolio_main_holder">
        <article>
          <div class="image_holder">
            <a href="/wrong">02/09/2026 BASES INFORMÁTICO</a>
            <img alt="03/09/2026 BASES DESARROLLADOR" />
          </div>
          <div class="portfolio_description">
            <h5 class="portfolio_title entry_title">
              <a href="/owned">01/09/2026 PROCESO ADMINISTRATIVO</a>
            </h5>
            <span class="project_category">Convocatoria informática</span>
            <article>
              <h5 class="portfolio_title entry_title">
                <a href="/nested">04/09/2026 BASES DESARROLLADOR</a>
              </h5>
            </article>
          </div>
        </article>
        <article>
          <div class="image_holder"><a href="/nested-only">05/09/2026 BASES DESARROLLADOR</a></div>
          <div class="portfolio_description"><article>
            <h5 class="portfolio_title entry_title">
              <a href="/nested-only-record">06/09/2026 BASES DESARROLLADOR</a>
            </h5>
          </article></div>
        </article>
      </div>
    </div>
    """

    pages = GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1))

    assert len(pages) == 1
    assert pages[0].url == "https://www.gsccanarias.com/owned"
    assert "04/09/2026" not in pages[0].title
    assert not KeywordFilter().search_page(
        GSCParser().parse(
            io.BytesIO(html.encode("utf-8")), target_date=datetime.date(2026, 9, 1)
        )[0]
    )


def _mixed_case(value: str) -> str:
    letter_number = 0
    characters = []
    for character in value:
        if character.isalpha():
            characters.append(character.upper() if letter_number % 2 == 0 else character.lower())
            letter_number += 1
        else:
            characters.append(character)
    return "".join(characters)


@pytest.mark.parametrize("case_transform", [str.upper, str.lower, _mixed_case])
@pytest.mark.parametrize(
    "notice_title",
    [
        "RESULTADOS BOLSA DE EMPLEO TECNICO INFORMATICO",
        "RELACIÓN PROVISIONAL DE ASPIRANTES TECNICO INFORMATICO",
        "LISTA DEFINITIVA DE ADMITIDOS TECNICO INFORMATICO",
        "CORRECCIÓN DE ERRORES BASES TECNICO INFORMATICO",
        "RECTIFICACIÓN DE BASES TECNICO INFORMATICO",
        "PERIODO DE SUBSANACIÓN TECNICO INFORMATICO",
        "CONVOCATORIA FASE I PRUEBA DE CONOCIMIENTOS TECNICO INFORMATICO",
        "CITACIÓN A EXAMEN TECNICO INFORMATICO",
        "BASES TECNICO INFORMATICO SE ANULA LA PRESENTE CONVOCATORIA",
        "BASES TECNICO INFORMATICO SE DECLARA LA ANULACIÓN",
    ],
)
def test_administrative_notice_exclusion_is_case_and_accent_insensitive(
    notice_title, case_transform, capsys
):
    title = f"01/09/2026 {case_transform(notice_title)}"

    pages = GSCParser().parse_list(
        wrap_cards(make_card(title)), target_date=datetime.date(2026, 9, 1)
    )

    assert pages == []
    assert "administrative or cancelled notice" in capsys.readouterr().out


def test_nested_title_text_cannot_supply_outer_it_text_or_url():
    html = wrap_cards(
        """
        <article>
          <h5 class="portfolio_title entry_title">
            <a href="/outer">
              01/09/2026 BASES AUXILIAR ADMINISTRATIVO
              <article>
                <span>DESARROLLADOR INFORMATICO</span>
                <a href="/nested">nested link</a>
              </article>
            </a>
          </h5>
        </article>
        """
    )

    records = GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1))
    pages = GSCParser().parse(
        io.BytesIO(html.encode("utf-8")), target_date=datetime.date(2026, 9, 1)
    )

    assert len(records) == 1
    assert records[0].title == "01/09/2026 BASES AUXILIAR ADMINISTRATIVO"
    assert records[0].url == "https://www.gsccanarias.com/outer"
    assert len(pages) == 1
    assert not KeywordFilter().search_page(pages[0])


def test_nested_date_cannot_rescue_outer_title_without_publication_date(capsys):
    html = wrap_cards(
        """
        <article>
          <h5 class="portfolio_title entry_title">
            <a href="/outer">BASES AUXILIAR ADMINISTRATIVO
              <article><span>01/09/2026</span></article>
            </a>
          </h5>
        </article>
        """
    )

    assert GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1)) == []
    assert "missing, invalid, or unsupported leading publication date" in capsys.readouterr().out


def test_nested_administrative_text_cannot_exclude_outer_opening():
    html = wrap_cards(
        """
        <article>
          <h5 class="portfolio_title entry_title">
            <a href="/outer">01/09/2026 BASES DESARROLLADOR/A
              <article><span>RESULTADOS SE ANULA LA PRESENTE CONVOCATORIA</span></article>
            </a>
          </h5>
        </article>
        """
    )

    records = GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1))

    assert len(records) == 1
    assert records[0].title == "01/09/2026 BASES DESARROLLADOR/A"


def test_inline_title_markup_remains_part_of_owned_title():
    html = wrap_cards(
        """
        <article>
          <h5 class="portfolio_title entry_title">
            <a href="/inline"><span>01/09/2026</span> <strong>BASES</strong>
              <b>DESARROLLADOR/A</b></a>
          </h5>
        </article>
        """
    )

    records = GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 1))

    assert len(records) == 1
    assert records[0].title == "01/09/2026 BASES DESARROLLADOR/A"


def test_malformed_title_url_falls_back_without_aborting_following_cards(capsys):
    records = GSCParser().parse_list(
        MALFORMED_URL_HTML, target_date=datetime.date(2026, 9, 1)
    )

    assert [record.url for record in records] == [
        "https://www.gsccanarias.com/gsc/portfolio_page/valid-one/",
        GSCParser.LIST_URL,
        "https://www.gsccanarias.com/gsc/portfolio_page/valid-three/",
    ]
    assert "no usable title URL; using the GSC list URL as fallback" in capsys.readouterr().out


def test_urls_fallback_to_list_and_exact_duplicates_are_removed():
    html = wrap_cards(
        make_card("01/09/2026 BASES DESARROLLADOR/A", "javascript:void(0)")
        + make_card("02/09/2026 BASES DESARROLLADOR/A", "#details")
        + make_card("03/09/2026 BASES DESARROLLADOR/A", "mailto:test@example.com")
        + make_card("04/09/2026 BASES DESARROLLADOR/A", "")
        + make_card("05/09/2026 BASES DESARROLLADOR/A", "https://example.com/valid")
        + make_card("05/09/2026 BASES DESARROLLADOR/A", "https://example.com/valid")
    )

    records = GSCParser().parse_list(html, target_date=datetime.date(2026, 9, 5))

    assert len(records) == 5
    assert all(record.url == GSCParser.LIST_URL for record in records[:4])
    assert records[-1].url == "https://example.com/valid"


def test_path_string_and_bytesio_inputs_are_equivalent():
    parser = GSCParser()
    path_pages = parser.parse(FIXTURE_PATH, target_date=datetime.date(2026, 6, 22))
    string_pages = parser.parse(str(FIXTURE_PATH), target_date=datetime.date(2026, 6, 22))
    stream_pages = parser.parse(
        io.BytesIO(fixture_html().encode("utf-8")), target_date=datetime.date(2026, 6, 22)
    )

    assert [page.text for page in path_pages] == [page.text for page in string_pages]
    assert [page.text for page in path_pages] == [page.text for page in stream_pages]


def test_output_keeps_distinct_date_labels_and_rejects_official_deadline_wording():
    pages = GSCParser().parse(
        io.BytesIO(fixture_html().encode("utf-8")),
        target_date=datetime.date(2026, 8, 27),
    )

    assert len(pages) == 1
    assert "Fecha de publicación: 20/08/2026" in pages[0].text
    assert "Fin de ventana de seguimiento inferida: 27/08/2026" in pages[0].text
    assert "publicación + 7 días" in pages[0].text
    assert "no es un plazo oficial de solicitud" in pages[0].text


def test_legitimate_gestion_administrativa_title_is_not_a_notice_exclusion():
    pages = GSCParser().parse(
        io.BytesIO(fixture_html().encode("utf-8")),
        target_date=datetime.date(2026, 9, 1),
    )

    assert len(pages) == 1
    assert "TÉCNICO DE GESTIÓN ADMINISTRATIVA" in pages[0].text
    assert not KeywordFilter().search_page(pages[0])


def test_supported_structure_accepts_empty_selection_holder():
    assert GSCParser.has_supported_structure(wrap_cards(""))
    assert not GSCParser.has_supported_structure("<div id='seleccion'></div>")
    assert not GSCParser.has_supported_structure("<p>GSC ofertas de empleo</p>")
