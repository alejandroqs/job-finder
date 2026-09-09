import datetime
import io
from pathlib import Path

from job_finder.geursa_parser import GeursaParser
from job_finder.keyword_filter import KeywordFilter


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "geursa_procesos_de_seleccion.html"


def fixture_html() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parser_extracts_only_active_cards_and_uses_stable_card_content():
    pages = GeursaParser().parse(FIXTURE_PATH, target_date=datetime.date(2026, 9, 9))

    assert len(pages) == 4
    assert [page.page_number for page in pages] == [1, 2, 3, 4]
    assert all(page.source == "GEURSA" for page in pages)
    assert all(page.detected_organism == "GEURSA" for page in pages)
    assert all(page.section == "Convocatorias en vigor" for page in pages)
    assert any("TIC-TDI" in page.text for page in pages)
    assert any("Administrativo/a" in page.text for page in pages)
    assert any("Técnico/a de Sistemas y Redes" in page.text for page in pages)
    assert any("Ingeniero/a de Software" in page.text for page in pages)
    assert not any("Finalizado" in page.text for page in pages)


def test_parser_keeps_past_future_and_missing_deadlines_and_target_dates_do_not_change_output():
    parser = GeursaParser()
    past = parser.parse(io.BytesIO(fixture_html().encode("utf-8")), datetime.date(2020, 1, 1))
    future = parser.parse(io.BytesIO(fixture_html().encode("utf-8")), datetime.date(2099, 12, 31))

    assert [page.text for page in past] == [page.text for page in future]
    assert "15 de febrero de 2025" in past[0].text
    assert "31 de diciembre de 2099" in past[1].text
    assert "fecha de presentación pendiente" in past[2].text


def test_parser_supports_path_filename_and_bytesio_with_nested_titles_and_collapsed_panels():
    parser = GeursaParser()
    path_pages = parser.parse(str(FIXTURE_PATH))
    stream_pages = parser.parse(io.BytesIO(fixture_html().encode("utf-8")))

    assert [page.text for page in path_pages] == [page.text for page in stream_pages]
    assert path_pages[0].text.startswith(
        "Responsable en Tecnologías de la Información, Comunicación y Transformación Digital"
    )
    assert "aria-hidden" not in path_pages[0].text
    assert "La solicitudes se podrán presentar" in path_pages[0].text


def test_parser_prefers_bases_over_other_attachments_and_excludes_attachment_captions():
    pages = GeursaParser().parse(FIXTURE_PATH)

    assert pages[0].url == "https://www.geursa.es/documentos/bases-tic.pdf"
    assert pages[1].url == "https://www.geursa.es/procesos-de-seleccion/documentos/bases-admin.pdf"
    assert all("Anexo I" not in page.text for page in pages)
    assert all("Listado provisional" not in page.text for page in pages)


def test_parser_uses_source_page_fallback_and_preserves_distinct_same_url_processes():
    pages = GeursaParser().parse(FIXTURE_PATH)
    fallback_pages = [
        page for page in pages if page.url == GeursaParser.LIST_URL
    ]

    assert len(fallback_pages) == 2
    assert {page.text.split(" ", 1)[0] for page in fallback_pages} == {
        "Técnico/a",
        "Ingeniero/a",
    }
    assert all("#" not in page.url for page in fallback_pages)


def test_parser_handles_aria_controlled_content_outside_card_and_changed_classes():
    html = """
    <h4><strong> Convocatorias  en VIGOR </strong></h4>
    <div class="wrapper-a">
      <div class="x-acc-item class-that-may-change">
        <div class="header-that-may-change">
          <button aria-controls="dynamic-generated-panel" aria-expanded="false">
            <span class="x-acc-header-text"><b>Ingeniero/a</b> de <strong>Software</strong></span>
          </button>
        </div>
      </div>
    </div>
    <div id="dynamic-generated-panel" class="x-acc-content another-generated-class" aria-hidden="true">
      <p>Convocatoria con plazo pasado: 01/01/2020.</p>
      <p><a href="/bases.pdf">Bases</a></p>
    </div>
    <h4>Convocatorias finalizadas</h4>
    <div class="x-acc-item class-that-may-change-too">
      <span class="x-acc-header-text">Técnico/a Informático/a finalizado</span>
      <div class="x-acc-content"><p>Convocatoria antigua.</p></div>
    </div>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert pages[0].text.startswith("Ingeniero/a de Software")
    assert pages[0].url == "https://www.geursa.es/bases.pdf"


def test_parser_assigns_nested_card_content_to_nearest_card_only():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <span class="x-acc-header-text">Outer administrative process</span>
        <div class="x-acc-item">
          <span class="x-acc-header-text">Inner software process</span>
          <div class="x-acc-content">
            Software recruitment
            <a href="/inner.pdf">Bases</a>
          </div>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 2
    assert pages[0].text == "Outer administrative process"
    assert pages[0].url == GeursaParser.LIST_URL
    assert pages[1].text == "Inner software process Software recruitment"
    assert pages[1].url == "https://www.geursa.es/inner.pdf"


def test_parser_does_not_borrow_nested_title_from_titleless_outer_card(capsys):
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <div class="x-acc-item">
          <span class="x-acc-header-text">Inner software process</span>
          <div class="x-acc-content">Software recruitment</div>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert pages[0].text == "Inner software process Software recruitment"
    assert "card 1 has no title" in capsys.readouterr().out


def test_parser_does_not_borrow_nested_bases_from_outer_card():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <span class="x-acc-header-text">Outer process</span>
        <div class="x-acc-content">Outer description</div>
        <div class="x-acc-item">
          <span class="x-acc-header-text">Inner process</span>
          <div class="x-acc-content">
            Inner description <a href="/inner.pdf">Bases</a>
          </div>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 2
    assert pages[0].text == "Outer process Outer description"
    assert pages[0].url == GeursaParser.LIST_URL
    assert pages[1].url == "https://www.geursa.es/inner.pdf"


def test_parser_excludes_nested_card_text_from_outer_selected_body():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <span class="x-acc-header-text">Outer process</span>
        <div class="x-acc-content">
          Outer description
          <div class="x-acc-item">
            <span class="x-acc-header-text">Inner process</span>
            <div class="x-acc-content">
              Inner description <a href="/inner.pdf">Bases</a>
            </div>
          </div>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 2
    assert pages[0].text == "Outer process Outer description"
    assert "Inner process" not in pages[0].text
    assert "Inner description" not in pages[0].text
    assert pages[0].url == GeursaParser.LIST_URL


def test_parser_keeps_empty_semantic_active_owner_from_following_unrelated_cards(capsys):
    html = """
    <body>
      <section>
        <h4>Convocatorias en vigor</h4>
        <p>No processes</p>
      </section>
      <section>
        <div class="x-acc-item">
          <span class="x-acc-header-text">Unrelated Software process</span>
          <div class="x-acc-content">Convocatoria</div>
        </div>
      </section>
    </body>
    """

    assert GeursaParser().parse(io.BytesIO(html.encode("utf-8"))) == []
    assert "supported but empty" in capsys.readouterr().out


def test_parser_preserves_div_layout_and_equal_or_higher_heading_boundary():
    html = """
    <main>
      <div class="heading-wrapper"><h4> Convocatorias   en VIGOR </h4></div>
      <div class="accordion-wrapper">
        <div class="x-acc-item">
          <span class="x-acc-header-text">Active Software process</span>
          <div class="x-acc-content">Convocatoria activa</div>
        </div>
      </div>
      <div><h3>Unrelated section</h3></div>
      <div class="x-acc-item">
        <span class="x-acc-header-text">Unrelated IT process</span>
        <div class="x-acc-content">Convocatoria archivada</div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert pages[0].text.startswith("Active Software process")


def test_parser_rejects_controlled_panel_from_finalized_section(capsys):
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <button aria-controls="archived-panel">
          <span class="x-acc-header-text">Active title</span>
        </button>
      </div>
      <h4>Convocatorias finalizadas</h4>
      <div id="archived-panel" class="x-acc-content">
        Archived description and <a href="/archived-bases.pdf">Bases</a>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert pages[0].text == "Active title"
    assert pages[0].url == GeursaParser.LIST_URL
    assert "Archived" not in pages[0].text
    assert "archived" not in pages[0].url
    assert "within the active section" in capsys.readouterr().out


def test_parser_rejects_controlled_panel_outside_owning_section():
    html = """
    <section>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <button aria-controls="outside-panel">
          <span class="x-acc-header-text">Active title</span>
        </button>
      </div>
    </section>
    <section>
      <div id="outside-panel" class="x-acc-content">
        Outside description <a href="/outside-bases.pdf">Bases</a>
      </div>
    </section>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert pages[0].text == "Active title"
    assert pages[0].url == GeursaParser.LIST_URL


def test_parser_rejects_controlled_panel_owned_by_another_card():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <button aria-controls="second-panel">
          <span class="x-acc-header-text">First title</span>
        </button>
      </div>
      <div class="x-acc-item">
        <span class="x-acc-header-text">Second title</span>
        <div id="second-panel" class="x-acc-content">
          Second description <a href="/second-bases.pdf">Bases</a>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 2
    assert pages[0].text == "First title"
    assert pages[0].url == GeursaParser.LIST_URL
    assert "Second description" not in pages[0].text
    assert pages[1].text.startswith("Second title Second description")
    assert pages[1].url == "https://www.geursa.es/second-bases.pdf"


def test_parser_rejects_external_panel_referenced_by_another_card():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <button aria-controls="shared-panel">
          <span class="x-acc-header-text">First title</span>
        </button>
      </div>
      <div class="x-acc-item">
        <button aria-controls="shared-panel">
          <span class="x-acc-header-text">Second title</span>
        </button>
      </div>
      <div id="shared-panel" class="x-acc-content">
        Claimed by another card <a href="/shared-bases.pdf">Bases</a>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 2
    assert all(page.text in {"First title", "Second title"} for page in pages)
    assert all(page.url == GeursaParser.LIST_URL for page in pages)
    assert all("Claimed by another card" not in page.text for page in pages)


def test_parser_uses_local_content_when_control_reference_is_missing():
    html = """
    <main>
      <h4>Convocatorias en vigor</h4>
      <div class="x-acc-item">
        <button aria-controls="missing-panel">
          <span class="x-acc-header-text">Local title</span>
        </button>
        <div class="x-acc-content">
          Local description <a href="/local-bases.pdf">Bases</a>
        </div>
      </div>
    </main>
    """

    pages = GeursaParser().parse(io.BytesIO(html.encode("utf-8")))

    assert len(pages) == 1
    assert "Local description" in pages[0].text
    assert pages[0].url == "https://www.geursa.es/local-bases.pdf"


def test_parser_reports_missing_heading_empty_section_and_missing_title(capsys):
    parser = GeursaParser()

    assert parser.parse(io.BytesIO(b"<html><body><h4>Other section</h4></body></html>")) == []
    assert "unsupported layout" in capsys.readouterr().out

    empty = "<h4>Convocatorias en vigor</h4><h4>Convocatorias finalizadas</h4>"
    assert parser.parse(io.BytesIO(empty.encode("utf-8"))) == []
    assert "supported but empty" in capsys.readouterr().out

    malformed = """
    <h4>Convocatorias en vigor</h4>
    <div class="x-acc-item"><div class="x-acc-content"><p>Convocatoria</p></div></div>
    <div class="x-acc-item">
      <span class="x-acc-header-text">Proceso válido</span>
      <div class="x-acc-content"><p>Convocatoria sin fecha.</p></div>
    </div>
    """
    pages = parser.parse(io.BytesIO(malformed.encode("utf-8")))
    diagnostics = capsys.readouterr().out

    assert len(pages) == 1
    assert pages[0].text.startswith("Proceso válido")
    assert "card 1 has no title" in diagnostics


def test_parser_detail_compatibility_does_not_affect_list_parsing():
    parser = GeursaParser()

    assert "Texto de detalle" in parser.parse_detail("<body><p>Texto de detalle</p></body>")
    assert parser.parse(FIXTURE_PATH)[0].source == "GEURSA"


def test_geursa_structure_detection_is_conservative():
    assert GeursaParser.has_supported_structure(fixture_html())
    assert not GeursaParser.has_supported_structure(
        "<html><body><p>GEURSA procesos de selección</p></body></html>"
    )
    assert not GeursaParser.has_supported_structure(
        "<h4>Convocatorias en vigor</h4><p>Sin acordeón</p>"
    )


def test_active_it_role_uses_normal_spanish_keyword_filter():
    pages = GeursaParser().parse(FIXTURE_PATH)
    matches = [match for page in pages for match in KeywordFilter().search_page(page)]

    assert any("Tecnologías de la Información" in match.description for match in matches)
