import io
from datetime import date
from pathlib import Path

import pytest

from job_finder.fulp_parser import FulpIdentityError, FulpParser, FulpParseError


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def test_listing_parses_all_observed_types_and_deduplicates_responsive_badges():
    parser = FulpParser()
    records = parser.parse_list(fixture("fulp_listing_observed.html"), target_date=date(2026, 9, 16))

    assert [record.offer_id for record in records] == [
        "108550",
        "108571",
        "110711",
        "112271",
        "109630",
        "110613",
    ]
    assert {record.type_normalized for record in records} == {
        "UNIVERSITY_INTERNSHIP",
        "ORDINARY_EMPLOYMENT",
        "INSERTA_FP_SUPERIOR",
        "INSERTA_UNIVERSITARIO",
    }
    assert parser.last_discovery["advertised_total"] == 6
    assert parser.last_discovery["discovered_unique_ids"] == 6
    assert parser.last_discovery["state"] == "RECONCILED_FOR_RESPONSE"
    assert parser.last_discovery["duplicate_records"] == 0


@pytest.mark.parametrize(
    "offer_id, expected",
    [
        ("108550", ["cursando grado universitario", "B1", "Microsoft 365"]),
        ("108571", ["sistemas y redes", "Mistral"]),
        ("110711", ["SAP", "Santa Cruz de Tenerife"]),
        ("112271", ["Service Desk", "soporte técnico", "Residencia"]),
        ("109630", ["Inserta FP", "Microsoft Intune", "Desarrollo de Aplicaciones Informáticas"]),
        ("110613", ["Inserta Universitario", "Ingeniería de Tecnologías de Telecomunicación", "telefonía móvil"]),
    ],
)
def test_detail_keeps_owned_role_eligibility_and_metadata_before_footer(offer_id, expected):
    parser = FulpParser()
    text = parser.parse_detail(fixture(f"fulp_detail_{offer_id}.html"))

    assert "Comparte esta oferta" not in text
    assert "Política de seguridad" not in text
    assert "INSCRIBIRME" not in text
    assert "\n\n" not in text
    assert all(fragment.casefold() in text.casefold() for fragment in expected)


def test_offline_detail_requires_public_identity_and_does_not_use_filename_or_numeric_text():
    parser = FulpParser()
    no_identity = fixture("fulp_detail_108550.html").replace(
        '<link rel="canonical" href="https://www.fulp.es/ofertas/108550/tecnicoa-en-administracion-de-sistemas-informaticos-108550">',
        "",
    ).replace(
        '<meta property="og:url" content="/ofertas/108550/tecnicoa-en-administracion-de-sistemas-informaticos-108550">',
        "",
    )

    assert parser.parse(io.BytesIO(no_identity.encode("utf-8"))) == []
    assert any("identity" in message.casefold() for message in parser.diagnostics)


def test_parse_is_network_free_even_when_fetcher_is_injected():
    class Tripwire:
        def fetch_list(self):
            raise AssertionError("offline parsing must not fetch a list")

        def fetch_detail(self, url):
            raise AssertionError("offline parsing must not fetch a detail")

    parser = FulpParser(fetcher=Tripwire())
    pages = parser.parse(FIXTURE_DIR / "fulp_detail_108550.html", target_date=date(2026, 9, 16))
    assert len(pages) == 1
    assert pages[0].source == "FULP"
    assert pages[0].url.endswith("/108550/tecnicoa-en-administracion-de-sistemas-informaticos-108550")


def test_offline_listing_is_explicitly_limited_and_never_fetches_details():
    class Tripwire:
        def fetch_list(self):
            raise AssertionError("offline listing unexpectedly fetched")

        def fetch_detail(self, url):
            raise AssertionError("offline listing unexpectedly fetched detail")

    parser = FulpParser(fetcher=Tripwire())
    pages = parser.parse(FIXTURE_DIR / "fulp_listing_observed.html", target_date=date(2026, 9, 16))
    assert len(pages) == 6
    assert all("EVIDENCIA LIMITADA" in page.text for page in pages)
    assert all(page.section.endswith("evidencia limitada)") for page in pages)
    assert any("listing-evidence-only" in message for message in parser.diagnostics)


def test_unknown_type_is_preserved_and_not_reclassified():
    html = """
    <html><head><link rel="canonical" href="/ofertas/123/future-role"></head><body>
      <div class="Content-Oferta"><h5>OPORTUNIDAD ESPECIAL</h5><h2 class="titulo">Administrador de redes</h2>
      <div class="container-details"><ul><li>Gran Canaria</li></ul></div>
      <div class="Tareas">Administración de redes y soporte técnico a usuarios.</div></div>
    </body></html>
    """
    record = FulpParser()._parse_detail_record(html, require_snapshot_identity=True)
    assert record.offer_type == "OPORTUNIDAD ESPECIAL"
    assert record.type_normalized == "UNKNOWN"


def test_nested_foreign_detail_root_cannot_contaminate_outer_record():
    html = """
    <html><head><link rel="canonical" href="https://www.fulp.es/ofertas/1/outer"></head><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5><h2 class="titulo">Outer systems role</h2>
        <div class="Descripcion">Outer description with sistemas.</div>
        <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5><h2 class="titulo">Foreign malware role</h2>
          <div class="Requisitos">Foreign secret requirement</div>
        </div>
        <div class="Requisitos">Outer requisitos: formación técnica.</div>
      </div>
    </body></html>
    """
    record = FulpParser()._parse_detail_record(html, require_snapshot_identity=True)
    assert record.title == "Outer systems role"
    assert "Foreign" not in record.requirements
    assert "Outer requisitos" in record.requirements


def test_listing_nested_card_cannot_create_or_contaminate_a_record():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/1/outer"><div class="row oferta"><h3>Outer systems</h3><p class="fecha">01/01/2026</p>
        <p class="descripcion">Outer description</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span>
        <div class="row oferta"><h3>Foreign software</h3><p class="descripcion">Foreign description</p>
          <span class="etiqueta tipo">OFERTA DE EMPLEO</span></div>
      </div></a></div></body></html>
    """
    parser = FulpParser()
    records = parser.parse_list(html, target_date=date(2026, 9, 16))
    assert len(records) == 1
    assert records[0].title == "Outer systems"
    assert "Foreign" not in records[0].listing_description


def test_old_publication_is_not_an_expiration_rule_but_expired_deadline_is_excluded():
    html = """
    <html><body><h5>2 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/1/old"><div class="row oferta"><h3>Old software role</h3><p class="fecha">01/01/2020</p>
        <p class="descripcion">Requisitos: software engineer.</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span></div></a>
      <a href="/ofertas/2/expired"><div class="row oferta"><h3>Expired software role</h3><p class="fecha">01/01/2020</p>
        <p class="descripcion">El plazo de presentación de candidaturas finalizó el 01/01/2025. Requisitos: software engineer.</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span></div></a>
    </div></body></html>
    """
    parser = FulpParser()
    records = parser.parse_list(html, target_date=date(2026, 9, 16))
    assert [record.offer_id for record in records] == ["1"]
    assert parser.last_discovery["discovered_unique_ids"] == 2
    assert parser.last_discovery["unavailable_records"] == 1


def test_unrelated_or_negated_dates_remain_unknown_and_ambiguous_dates_are_diagnosed():
    reference = date(2026, 9, 16)

    status, deadline, _, _ = FulpParser._availability(
        "El plazo de ejecución del proyecto finaliza el 01/01/2025.",
        reference,
    )
    assert (status, deadline) == ("UNKNOWN", None)

    status, deadline, _, _ = FulpParser._availability(
        "No se establece plazo de solicitud; 01/01/2025 aparece como referencia.",
        reference,
    )
    assert (status, deadline) == ("UNKNOWN", None)

    status, deadline, _, evidence = FulpParser._availability(
        "El plazo de solicitud finaliza el 01/02/26.",
        reference,
    )
    assert (status, deadline) == ("UNKNOWN", None)
    assert "invalid" in evidence.casefold() or "unsupported" in evidence.casefold()


def test_availability_ignores_closed_words_in_qualifications_and_duties():
    reference = date(2026, 9, 16)

    qualification = FulpParser._availability(
        "Requisitos: estudios universitarios finalizados en Ingeniería Informática.",
        reference,
    )
    duties = FulpParser._availability(
        "Administrar tickets cerrados y resolver incidencias.",
        reference,
    )

    assert qualification[:2] == ("UNKNOWN", None)
    assert duties[:2] == ("UNKNOWN", None)


def test_application_deadlines_use_the_closing_date_and_ignore_publication_dates():
    reference = date(2026, 9, 16)

    expired_status = FulpParser._availability(
        "Publicación: 01/09/2026. Plazo de solicitud hasta el 10/09/2026.",
        reference,
    )
    interval_status = FulpParser._availability(
        "El plazo de solicitudes es del 01/09/2026 hasta el 30/09/2026.",
        reference,
    )
    closing_day_status = FulpParser._availability(
        "El plazo de solicitudes es del 01/09/2026 hasta el 30/09/2026.",
        date(2026, 9, 30),
    )
    after_closing_status = FulpParser._availability(
        "El plazo de solicitudes es del 01/09/2026 hasta el 30/09/2026.",
        date(2026, 10, 1),
    )

    assert expired_status[:2] == ("EXPIRED", date(2026, 9, 10))
    assert interval_status[:2] == ("OPEN", date(2026, 9, 30))
    assert closing_day_status[:2] == ("OPEN", date(2026, 9, 30))
    assert after_closing_status[:2] == ("EXPIRED", date(2026, 9, 30))


def test_negated_closed_wording_is_not_treated_as_closed():
    status, deadline, _, _ = FulpParser._availability(
        "La oferta no está cerrada y no se ha cancelado.",
        date(2026, 9, 16),
    )
    assert (status, deadline) == ("UNKNOWN", None)


def test_closed_evidence_remains_closed_for_a_historical_reference_date():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/3/closed"><div class="row oferta"><h3>Closed software role</h3><p class="fecha">01/01/2020</p>
        <p class="descripcion">Proceso de selección cerrado. Requisitos: software engineer.</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span></div></a>
    </div></body></html>
    """
    assert FulpParser().parse_list(html, target_date=date(2020, 1, 2)) == []


def test_supported_empty_listing_is_distinguished_from_generic_html():
    empty = '<html><body><div class="panel_ofertas"><h5>0 RESULTADOS ENCONTRADOS</h5></div></body></html>'
    generic = '<html><body><p>FULP offers and privacy policy.</p></body></html>'
    assert FulpParser.has_supported_list_structure(empty)
    assert not FulpParser.has_supported_structure(generic)
    parser = FulpParser()
    assert parser.parse_list(empty) == []
    assert any("genuinely empty" in message for message in parser.diagnostics)


def test_conflicting_canonical_and_og_id_is_quarantined():
    html = fixture("fulp_detail_108550.html").replace(
        'content="/ofertas/108550/tecnicoa-en-administracion-de-sistemas-informaticos-108550"',
        'content="/ofertas/999/other"',
    )
    with pytest.raises(FulpIdentityError):
        FulpParser().parse_detail(html)
