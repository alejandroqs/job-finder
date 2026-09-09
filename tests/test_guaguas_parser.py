import datetime
import io
from pathlib import Path
from unittest.mock import patch

from job_finder import guaguas_parser as guaguas_parser_module
from job_finder.guaguas_parser import GuaguasParser
from job_finder.interfaces import BOPage
from job_finder.keyword_filter import KeywordFilter


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "guaguas_trabaja_con_nosotros.html"
REFERENCE_DATE = datetime.date(2026, 6, 15)


def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parser_extracts_cards_without_mixing_fields_or_notice_history():
    parser = GuaguasParser()

    pages = parser.parse(FIXTURE_PATH, target_date=REFERENCE_DATE)

    assert len(pages) == 4
    assert [page.page_number for page in pages] == [1, 2, 3, 4]
    assert all(page.source == "GUAGUAS" for page in pages)
    assert all(page.detected_organism == "Guaguas Municipales" for page in pages)
    assert all(page.section == "Ofertas de Empleo" for page in pages)
    assert pages[0].text.startswith("Técnico/a de Sistemas y Redes & Soporte")
    assert "Vacantes: 2" in pages[0].text
    assert "Publicado el 15/12/2025" in pages[0].text
    assert "RESULTADOS DEFINITIVOS" not in pages[0].text
    assert "REANUDADA" not in " ".join(page.text for page in pages)

    assert pages[0].url == "https://www.guaguas.com/ofertas_trabajo/bases_it.pdf"
    assert pages[1].url == "https://cdn.example.test/bases_conductor.pdf"
    assert pages[2].url.startswith(GuaguasParser.LIST_URL + "#guaguas-")
    assert "programador-a-de-aplicaciones" in pages[2].url
    assert pages[3].url.startswith("https://www.guaguas.com/ofertas_trabajo/")
    assert len({page.url for page in pages}) == len(pages)


def test_parser_supports_bytesio_and_string_path_and_filter_pipeline():
    parser = GuaguasParser()
    stream_pages = parser.parse(
        io.BytesIO(fixture_html().encode("utf-8")), target_date=REFERENCE_DATE
    )
    string_path_pages = parser.parse(str(FIXTURE_PATH), target_date=REFERENCE_DATE)

    assert [page.text for page in stream_pages] == [page.text for page in string_path_pages]

    filter_ = KeywordFilter()
    it_matches = filter_.search_page(stream_pages[0])
    non_it_matches = filter_.search_page(stream_pages[1])
    assert len(it_matches) == 1
    assert it_matches[0].organism == "Guaguas Municipales"
    assert non_it_matches == []


def test_parser_applies_inclusive_date_boundaries():
    html = """
    <div class="contenido_seccion carnets">
      <div class="panel"><h2 class="panel-title">Oferta de borde</h2><ul>
        <li><strong>Convocatoria:</strong> del 10/06/2026 al 20/06/2026</li>
      </ul></div>
    </div>
    """
    parser = GuaguasParser()

    assert parser.parse(io.BytesIO(html.encode()), datetime.date(2026, 6, 9)) == []
    assert len(parser.parse(io.BytesIO(html.encode()), datetime.date(2026, 6, 10))) == 1
    assert len(parser.parse(io.BytesIO(html.encode()), datetime.date(2026, 6, 20))) == 1
    assert parser.parse(io.BytesIO(html.encode()), datetime.date(2026, 6, 21)) == []


def test_parser_uses_controlled_current_date_when_target_is_omitted():
    html = """
    <div class="contenido_seccion carnets">
      <div class="panel"><h2 class="panel-title">Oferta controlada</h2><ul>
        <li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li>
      </ul></div>
    </div>
    """
    real_date = datetime.date
    with patch.object(guaguas_parser_module, "date") as mocked_date:
        mocked_date.side_effect = real_date
        mocked_date.today.return_value = real_date(2026, 6, 15)
        pages = GuaguasParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1


def test_parser_skips_missing_invalid_and_inverted_intervals(capsys):
    html = """
    <div class="contenido_seccion carnets">
      <div class="panel"><h2 class="panel-title">Sin fechas</h2><ul>
        <li><strong>Vacantes:</strong> 1</li>
      </ul></div>
      <div class="panel"><h2 class="panel-title">Fecha imposible</h2><ul>
        <li><strong>Convocatoria:</strong> del 31/02/2026 al 10/03/2026</li>
      </ul></div>
      <div class="panel"><h2 class="panel-title">Fecha invertida</h2><ul>
        <li><strong>Convocatoria:</strong> del 20/06/2026 al 10/06/2026</li>
      </ul></div>
    </div>
    """

    pages = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)

    assert pages == []
    diagnostics = capsys.readouterr().out
    assert "missing or invalid Convocatoria" in diagnostics
    assert "inverted Convocatoria" in diagnostics


def test_parser_distinguishes_absent_and_empty_containers(capsys):
    parser = GuaguasParser()

    assert parser.parse(io.BytesIO(b"<html><body><p>Header</p></body></html>"), REFERENCE_DATE) == []
    absent_diagnostic = capsys.readouterr().out
    assert "container not found" in absent_diagnostic

    empty_html = '<div class="contenido_seccion carnets"></div>'
    assert parser.parse(io.BytesIO(empty_html.encode()), REFERENCE_DATE) == []
    empty_diagnostic = capsys.readouterr().out
    assert "container is empty" in empty_diagnostic


def test_parser_uses_base_tag_and_never_uses_notice_links():
    html = """
    <base href="https://example.test/root/">
    <div class="contenido_seccion carnets"><div class="panel">
      <h2 class="panel-title">Ingeniería Informática</h2>
      <div class="panel-body">
        <h3>Bases reguladoras</h3>
        <ul><li><strong>Vacantes:</strong> 1</li><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li>
          <li><a href="./ofertas_trabajo/bases.pdf">Bases</a></li></ul>
        <h3>Avisos</h3><ul><li><a href="./ofertas_trabajo/avisos/notice.pdf">Bases actualizadas</a></li></ul>
      </div>
    </div></div>
    """

    page = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)[0]

    assert page.url == "https://example.test/root/ofertas_trabajo/bases.pdf"
    assert "avisos" not in page.url


def test_notice_metadata_cannot_replace_main_application_fields(capsys):
    html = """
    <div class="contenido_seccion carnets">
      <div class="panel">
        <h2 class="panel-title">Sin intervalo principal</h2>
        <div class="panel-body">
          <h3>Bases reguladoras</h3>
          <ul><li><strong>Puesto:</strong> Puesto principal</li></ul>
          <h3>Avisos</h3>
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
        </div>
      </div>
      <div class="panel">
        <h2 class="panel-title">Sin campos principales</h2>
        <div class="panel-body">
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
          <h3>Avisos</h3>
          <ul>
            <li><strong>Puesto:</strong> Puesto inventado por aviso</li>
            <li><strong>Vacantes:</strong> 999</li>
          </ul>
        </div>
      </div>
      <div class="panel">
        <h2 class="panel-title">Intervalo principal autorizado</h2>
        <div class="panel-body">
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
          <h3>Avisos</h3>
          <ul><li><strong>Convocatoria:</strong> del 01/01/2024 al 31/01/2024</li></ul>
        </div>
      </div>
    </div>
    """

    pages = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)

    assert len(pages) == 2
    assert "Puesto inventado por aviso" not in pages[0].text
    assert "Vacantes: 999" not in pages[0].text
    assert "01/06/2026" in pages[1].text
    assert "01/01/2024" not in pages[1].text
    assert "missing or invalid Convocatoria" in capsys.readouterr().out


def test_malformed_card_does_not_block_a_valid_card(capsys):
    html = """
    <div class="contenido_seccion carnets">
      <div class="panel">
        <h2 class="panel-title">Tarjeta defectuosa</h2>
        <div class="panel-body">
          <h3>Avisos</h3>
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
        </div>
      </div>
      <div class="panel">
        <h2 class="panel-title">Tarjeta válida</h2>
        <div class="panel-body">
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
        </div>
      </div>
    </div>
    """

    pages = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)

    assert len(pages) == 1
    assert pages[0].text.startswith("Tarjeta válida")
    assert "missing or invalid Convocatoria" in capsys.readouterr().out


def test_notice_bases_link_is_not_used_as_the_record_url():
    html = """
    <base href="https://example.test/portal/">
    <div class="contenido_seccion carnets"><div class="panel">
      <h2 class="panel-title">Oferta sin bases originales</h2>
      <div class="panel-body">
        <h3>Bases reguladoras</h3>
        <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
        <h3>Avisos</h3>
        <ul>
          <li><a href="documentos/primer_aviso.pdf">Aviso inicial</a></li>
          <li>Contenido informativo sin enlace</li>
          <li><a href="documentos/correccion.pdf">Bases actualizadas</a></li>
        </ul>
      </div>
    </div></div>
    """

    page = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)[0]

    assert page.url.startswith(GuaguasParser.LIST_URL + "#guaguas-")
    assert "correccion.pdf" not in page.url


def test_bases_section_stays_inside_card_and_stops_at_nested_notice_heading():
    html = """
    <base href="https://example.test/portal/">
    <div class="contenido_seccion carnets">
      <div class="panel">
        <div class="panel-body">
          <h2 class="panel-title">Aviso anidado</h2>
          <h3>Bases reguladoras</h3>
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
          <h4>Avisos</h4>
          <ul><li><a href="documentos/aviso.pdf">Bases de la convocatoria</a></li></ul>
        </div>
      </div>
      <div class="panel">
        <div class="panel-body">
          <h2 class="panel-title">Sin bases</h2>
          <h3>Bases reguladoras</h3>
          <ul><li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li></ul>
        </div>
      </div>
    </div>
    <a href="documentos/privacy.pdf">Privacy policy</a>
    """

    pages = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)

    assert len(pages) == 2
    assert all(page.url.startswith(GuaguasParser.LIST_URL + "#guaguas-") for page in pages)
    assert all("aviso.pdf" not in page.url for page in pages)
    assert all("privacy.pdf" not in page.url for page in pages)


def test_bases_link_is_selected_after_a_non_bases_attachment():
    html = """
    <base href="https://example.test/portal/">
    <div class="contenido_seccion carnets"><div class="panel">
      <h2 class="panel-title">Oferta con solicitud y bases</h2>
      <div class="panel-body">
        <h3>Bases reguladoras</h3>
        <ul>
          <li><strong>Convocatoria:</strong> del 01/06/2026 al 30/06/2026</li>
          <li><a href="documentos/solicitud.pdf">Solicitud</a></li>
          <li><a href="./ofertas_trabajo/bases_form.pdf">Bases de la convocatoria</a></li>
        </ul>
      </div>
    </div></div>
    """

    page = GuaguasParser().parse(io.BytesIO(html.encode()), REFERENCE_DATE)[0]

    assert page.url == "https://example.test/portal/ofertas_trabajo/bases_form.pdf"
    assert "solicitud.pdf" not in page.url


def test_parser_detail_compatibility_does_not_affect_list_parsing():
    parser = GuaguasParser()

    assert "Texto de detalle" in parser.parse_detail("<body><p>Texto de detalle</p></body>")
    assert isinstance(
        parser.parse(io.BytesIO(fixture_html().encode()), REFERENCE_DATE)[0], BOPage
    )
