from pathlib import Path

import pytest

from job_finder.sodetegc_parser import ObservationStatus, SODETEGCParser


FIXTURE = Path(__file__).parent / "fixtures" / "sodetegc_empleo_observed.html"
HTML = FIXTURE.read_text(encoding="utf-8")
REFERENCE = "Actualmente no hay ninguna convocatoria abierta"
ACTIVE_BLOCK = (
    "<h2><strong>Convocatorias abiertas:</strong></h2>"
    f"<ul><li>{REFERENCE}</li></ul>"
)
ACTIVE_HEADING = "<h2><strong>Convocatorias abiertas:</strong></h2>"


def with_active_content(content: str) -> str:
    return HTML.replace(ACTIVE_BLOCK, ACTIVE_HEADING + content, 1)


def synthetic_page(section_html: str) -> str:
    return f"""<!doctype html>
<html><head><title>Ofertas de empleo | SODETEGC</title>
<link rel="canonical" href="{SODETEGCParser.URL}"></head><body>
<div id="sodetegc-title"><h1>Ofertas de empleo</h1></div>
<main id="sodetegc-content"><article><div class="entry-content">
{section_html}
</div></article></main></body></html>"""


def test_observed_page_is_baseline_despite_historical_tic_offers():
    observation = SODETEGCParser.parse(HTML)

    assert observation.status is ObservationStatus.BASELINE
    assert observation.owned_text == REFERENCE
    assert "Tecnologías de la Información" in HTML


@pytest.mark.parametrize(
    "replacement",
    [
        " actualmente&nbsp;no hay ninguna convocatoria abierta. ",
        "Actual<strong>mente</strong> no hay ninguna convocatoria abierta",
        "ACTUALMENTE\n  NO HAY NINGUNA CONVOCATORIA ABIERTA",
    ],
)
def test_normalisation_accepts_whitespace_nbsp_case_inline_markup_and_final_period(replacement):
    html = with_active_content(f"<ul><li>{replacement}</li></ul>")

    assert SODETEGCParser.parse(html).status is ObservationStatus.BASELINE


@pytest.mark.parametrize(
    ("content", "expected_text"),
    [
        ("<ul><li>Convocatoria para técnico informático</li></ul>", "Convocatoria para técnico informático"),
        ("<ul></ul>", ""),
        (f"<ul><li>{REFERENCE}</li><li>Nuevo contenido visible</li></ul>", f"{REFERENCE} Nuevo contenido visible"),
    ],
)
def test_replaced_removed_and_added_content_are_changed(content, expected_text):
    observation = SODETEGCParser.parse(with_active_content(content))

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == expected_text


def test_changes_outside_active_section_do_not_change_observation():
    forecast_changed = HTML.replace("Previsión de oferta de empleo:", "Previsión laboral:")
    history_changed = HTML.replace("Histórico de ofertas de empleo", "Histórico modificado")
    footer_added = HTML.replace(
        "</body>", f"<footer>Convocatoria nueva: {REFERENCE}</footer></body>"
    )

    assert SODETEGCParser.parse(forecast_changed).status is ObservationStatus.BASELINE
    assert SODETEGCParser.parse(history_changed).status is ObservationStatus.BASELINE
    assert SODETEGCParser.parse(footer_added).status is ObservationStatus.BASELINE


def test_reference_outside_active_section_cannot_suppress_notice():
    html = with_active_content("<ul><li>Convocatoria para una plaza técnica</li></ul>")
    html = html.replace("</body>", f"<footer>{REFERENCE}</footer></body>")

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == "Convocatoria para una plaza técnica"


@pytest.mark.parametrize(
    "hidden_markup",
    [
        f'<span hidden>{REFERENCE}</span>',
        f'<span aria-hidden="true">{REFERENCE}</span>',
        f'<span style="display: none !important">{REFERENCE}</span>',
        f'<span style="visibility:hidden">{REFERENCE}</span>',
        f'<span class="hidden">{REFERENCE}</span>',
    ],
)
def test_hidden_reference_does_not_determine_visible_state(hidden_markup):
    observation = SODETEGCParser.parse(with_active_content(f"<ul><li>{hidden_markup}</li></ul>"))

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == ""


@pytest.mark.parametrize("hidden_owner", ["article", "main"])
def test_hidden_page_owner_makes_changed_section_unverifiable(hidden_owner):
    html = with_active_content("<ul><li>Convocatoria visible</li></ul>")
    if hidden_owner == "article":
        html = html.replace(
            '<article id="post-3016"', '<article id="post-3016" hidden', 1
        )
    else:
        html = html.replace(
            '<main id="sodetegc-content"', '<main id="sodetegc-content" hidden', 1
        )
    assert html != with_active_content("<ul><li>Convocatoria visible</li></ul>")

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert "owner" in observation.diagnostic


@pytest.mark.parametrize(
    ("active_content", "expected_status"),
    [
        (f"<p>{REFERENCE}</p>", ObservationStatus.BASELINE),
        (
            f"<p>{REFERENCE}</p><details><summary></summary>"
            "<p>Convocatoria oculta</p></details>",
            ObservationStatus.BASELINE,
        ),
        (
            f"<p>{REFERENCE}</p><details open><summary></summary>"
            "<p>Convocatoria visible</p></details>",
            ObservationStatus.CHANGED,
        ),
    ],
    ids=["visible-baseline", "closed-details-baseline", "open-details-changed"],
)
def test_closed_details_body_is_not_visible_but_open_details_content_is(
    active_content, expected_status
):
    observation = SODETEGCParser.parse(with_active_content(active_content))

    assert observation.status is expected_status
    if expected_status is ObservationStatus.BASELINE:
        assert observation.owned_text == REFERENCE
    else:
        assert "Convocatoria visible" in observation.owned_text


def test_nested_foreign_article_content_is_excluded():
    content = (
        "<ul><li>Convocatoria nueva</li></ul>"
        f'<article><div class="entry-content"><p>{REFERENCE}</p></div></article>'
    )
    observation = SODETEGCParser.parse(with_active_content(content))

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == "Convocatoria nueva"


def test_duplicate_active_headings_are_unverifiable():
    duplicate = (
        ACTIVE_BLOCK
        + ACTIVE_HEADING
        + "<ul><li>Otra convocatoria</li></ul>"
    )
    html = HTML.replace(ACTIVE_BLOCK, duplicate, 1)

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert "ambiguous" in observation.diagnostic


def test_duplicate_top_level_content_owners_are_unverifiable():
    html = HTML.replace(
        "</main>",
        '<article><div class="entry-content"><p>duplicate owner</p></div></article></main>',
        1,
    )

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert "owner" in observation.diagnostic


@pytest.mark.parametrize(
    "html,diagnostic",
    [
        ("<html><body>Service unavailable</body></html>", "identity"),
        (HTML.replace('id="sodetegc-content"', 'id="different-content"', 1), "main"),
        (HTML.replace(ACTIVE_BLOCK, "", 1), "heading"),
        (HTML.replace("</html>", "", 1), "truncated"),
        (HTML.replace("</head>", '<link rel="canonical" href="https://example.com/empleo/"></head>', 1), "identity"),
        (HTML + "<!-- just a moment... cf-challenge -->", "challenge"),
        (
            '<html><head><title>Login</title></head><body><input type="password"></body></html>',
            "login",
        ),
    ],
    ids=[
        "generic-error",
        "missing-main-owner",
        "missing-heading",
        "truncated-document",
        "conflicting-identity",
        "challenge-page",
        "login-page",
    ],
)
def test_unrecognised_or_incomplete_pages_are_unverifiable(html, diagnostic):
    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert diagnostic in observation.diagnostic.casefold()


def test_empty_active_section_without_next_boundary_is_unverifiable():
    html = synthetic_page(ACTIVE_HEADING)

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert "boundary" in observation.diagnostic


def test_empty_section_with_verified_next_heading_is_changed():
    html = synthetic_page(
        ACTIVE_HEADING + '<ul></ul><h2>Previsión de oferta de empleo</h2>'
    )

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == ""


def test_identical_duplicate_canonical_and_og_url_evidence_is_accepted():
    canonical = f'<link rel="canonical" href="{SODETEGCParser.URL}">'
    html = HTML.replace("</head>", canonical + "</head>", 1)

    assert SODETEGCParser.parse(html).status is ObservationStatus.BASELINE


def test_utf8_text_and_inline_word_joining_are_preserved():
    content = "<ul><li>Convoca<strong>toria</strong> para técnico informático en Gran Canaria</li></ul>"

    observation = SODETEGCParser.parse(with_active_content(content))

    assert observation.status is ObservationStatus.CHANGED
    assert observation.owned_text == "Convocatoria para técnico informático en Gran Canaria"


@pytest.mark.parametrize(
    "heading_html",
    [
        "<h2>Convoca<strong>torias</strong> abiertas:</h2>",
        "<h2><span>Convocatorias</span><div>abiertas:</div></h2>",
    ],
    ids=["inline-word-join", "block-boundary-space"],
)
def test_active_heading_preserves_inline_words_and_block_boundaries(heading_html):
    html = HTML.replace(ACTIVE_HEADING, heading_html, 1)

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.BASELINE


def test_hidden_descendant_cannot_supply_active_heading_text():
    hidden_heading = '<h2><span hidden>Convocatorias abiertas:</span></h2>'
    html = HTML.replace(ACTIVE_HEADING, hidden_heading, 1).replace(
        f"<li>{REFERENCE}</li>", "<li>Convocatoria nueva</li>", 1
    )

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.UNVERIFIABLE
    assert "heading is missing" in observation.diagnostic


def test_hidden_descendant_cannot_supply_following_section_boundary():
    hidden_boundary = (
        '<h2><span hidden>Previsión de oferta de empleo</span></h2>'
        "<p>Contenido que sigue dentro de la sección activa</p>"
    )
    html = HTML.replace(
        "<h2><strong>Convocatorias abiertas:</strong></h2>"
        f"<ul><li>{REFERENCE}</li></ul>",
        ACTIVE_HEADING + f"<ul><li>{REFERENCE}</li></ul>" + hidden_boundary,
        1,
    )

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.CHANGED
    assert "Contenido que sigue dentro de la sección activa" in observation.owned_text


def test_hidden_heading_extra_is_ignored_when_visible_label_is_complete():
    visible_heading_with_hidden_extra = (
        "<h2>Convoca<strong>torias</strong> abiertas:"
        "<span hidden> borrador</span></h2>"
    )
    html = HTML.replace(ACTIVE_HEADING, visible_heading_with_hidden_extra, 1)

    observation = SODETEGCParser.parse(html)

    assert observation.status is ObservationStatus.BASELINE


def test_offline_page_signature_requires_official_identity_and_structure():
    assert SODETEGCParser.has_page_signature(HTML)
    assert not SODETEGCParser.has_page_signature(
        '<html><body><footer>SODETEGC Convocatorias abiertas</footer></body></html>'
    )
    assert not SODETEGCParser.has_page_signature(
        HTML.replace('property="og:url"', 'property="og:description"').replace(
            'rel="canonical"', 'rel="alternate"'
        )
    )
