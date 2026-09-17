import io
from datetime import date
from pathlib import Path

import pytest

from job_finder.fulp_parser import FulpIdentityError, FulpParser, FulpParseError, FulpRecord
from job_finder.interfaces import BOPage
from job_finder.keyword_filter import KeywordFilter


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


def test_nested_linked_listing_card_cannot_override_outer_identity():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/1/outer"><div class="row oferta"><h3>Outer systems</h3>
        <p class="descripcion">Outer description with sistemas.</p>
        <span class="etiqueta tipo">OFERTA DE EMPLEO</span>
        <a href="/ofertas/2/foreign"><div class="row oferta">
          <h3>Foreign systems</h3><p class="descripcion">Foreign description.</p>
          <span class="etiqueta tipo">OFERTA DE EMPLEO</span>
        </div></a>
      </div></a>
    </div></body></html>
    """

    records = FulpParser().parse_list(html, target_date=date(2026, 9, 16))

    assert [record.offer_id for record in records] == ["1"]
    assert records[0].title == "Outer systems"
    assert "Foreign" not in records[0].listing_description


def test_nested_detail_identity_is_not_used_when_outer_root_has_no_identity():
    html = """
    <html><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5>
        <h2 class="titulo">Outer systems</h2>
        <div class="Descripcion">Outer description with sistemas.</div>
        <div class="Content-Oferta">
          <link rel="canonical" href="https://www.fulp.es/ofertas/2/foreign">
        </div>
      </div>
    </body></html>
    """

    with pytest.raises(FulpIdentityError, match="no reliable canonical"):
        FulpParser()._parse_detail_record(html, require_snapshot_identity=True)


def test_application_word_in_owned_listing_role_does_not_hide_the_offer():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/3/aplicaciones"><div class="row oferta">
        <h3>Desarrollo de Aplicaciones Informáticas</h3>
        <p class="descripcion">Requisitos: sistemas y redes.</p>
        <span class="etiqueta tipo">PRÁCTICAS UNIVERSITARIAS</span>
      </div></a>
    </div></body></html>
    """

    records = FulpParser().parse_list(html, target_date=date(2026, 9, 16))

    assert len(records) == 1
    assert records[0].title == "Desarrollo de Aplicaciones Informáticas"
    assert "sistemas y redes" in records[0].listing_description


@pytest.mark.parametrize(
    ("offer_id", "expected_organism"),
    [
        ("108550", "Empresa no identificada"),
        ("108571", "Mistral Tecnologías de Informacion y Comunicaciones SL"),
    ],
)
def test_fulp_finding_uses_evidenced_employer_and_keeps_source(offer_id, expected_organism):
    from job_finder.keyword_filter import KeywordFilter

    parser = FulpParser()
    record = parser._parse_detail_record(
        fixture(f"fulp_detail_{offer_id}.html"),
        require_snapshot_identity=True,
        reference_date=date(2026, 9, 16),
    )
    findings = KeywordFilter().search_page(parser._to_page(record, 1))

    assert len(findings) == 1
    assert findings[0].organism == expected_organism
    assert findings[0].source == "FULP"


def test_location_detection_does_not_extract_locality_from_company_text():
    html = """
    <html><head><link rel="canonical" href="/ofertas/4/company-role"></head><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5>
        <h2 class="titulo">Systems administrator</h2>
        <div class="container-details"><ul>
          <li>Servicios Gran Canaria SL</li><li>Plazas: 1</li>
          <li>Santa Cruz de Tenerife</li>
        </ul></div>
        <div class="Descripcion">Requisitos: sistemas y redes.</div>
      </div>
    </body></html>
    """

    record = FulpParser()._parse_detail_record(html, require_snapshot_identity=True)

    assert record.location_raw == "Santa Cruz de Tenerife"
    assert "Gran Canaria" not in record.location_raw


def test_online_detail_keeps_employer_merged_from_owned_listing_metadata():
    listing = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/8/merged-employer"><div class="row oferta">
        <h3>Systems administrator</h3><p class="empresa">Owned Employer SL</p>
        <p class="descripcion">Buscamos sistemas y redes. Requisitos: sistemas y redes.</p>
        <span class="etiqueta tipo">OFERTA DE EMPLEO</span>
      </div></a>
    </div></body></html>
    """
    detail = """
    <html><head><link rel="canonical" href="/ofertas/8/merged-employer"></head><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5>
        <h2 class="titulo">Systems administrator</h2>
        <div class="Descripcion">Buscamos sistemas y redes. Requisitos: sistemas y redes.</div>
      </div>
    </body></html>
    """

    class Fetcher:
        last_response_url = ""

        def begin_scan(self):
            pass

        def fetch_list(self):
            return listing

        def fetch_detail(self, url):
            assert url.endswith("/ofertas/8/merged-employer")
            return detail

    from job_finder.keyword_filter import KeywordFilter

    pages = FulpParser(fetcher=Fetcher()).scan(target_date=date(2026, 9, 16))
    findings = KeywordFilter().search_page(pages[0])

    assert len(findings) == 1
    assert findings[0].organism == "Owned Employer SL"
    assert findings[0].source == "FULP"


def test_record_text_keeps_description_eligibility_before_long_optional_tasks():
    record = FulpRecord(
        offer_id="5",
        title="Técnico de sistemas",
        url="https://www.fulp.es/ofertas/5/sistemas",
        offer_type="PRÁCTICAS UNIVERSITARIAS",
        description=(
            "Se requieren prácticas extracurriculares en IT. "
            "Se requiere encontrarse cursando grado universitario acorde a la práctica "
            "ofertada y nivel intermedio de inglés."
        ),
        tasks="Tarea opcional detallada. " * 500,
        profile="Perfil técnico",
        requirements="Inglés B1",
    )

    text = FulpParser._record_text(record)

    assert "cursando grado universitario acorde a la práctica ofertada" in text[:1500]
    assert "nivel intermedio de inglés" in text[:1500]
    assert "Tarea opcional detallada." in text


def test_listing_type_comes_from_owned_type_badges_not_contract_badges():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/6/nuevo-programa"><div class="row oferta">
        <h3>Software support role</h3><p class="descripcion">Requisitos: sistemas.</p>
        <span class="etiqueta">CONTRATO INDEFINIDO</span>
        <span class="etiqueta tipo">NUEVO PROGRAMA</span>
      </div></a>
    </div></body></html>
    """

    records = FulpParser().parse_list(html, target_date=date(2026, 9, 16))

    assert len(records) == 1
    assert records[0].offer_type == "NUEVO PROGRAMA"
    assert records[0].type_normalized == "UNKNOWN"
    assert records[0].contract == "CONTRATO INDEFINIDO"


def test_conflicting_owned_listing_type_badges_are_diagnosed_and_skipped():
    html = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/9/conflicting-type"><div class="row oferta">
        <h3>Conflicting role</h3><p class="descripcion">Requisitos: sistemas.</p>
        <span class="etiqueta tipo">OFERTA DE EMPLEO</span>
        <span class="etiqueta tipo">NUEVO PROGRAMA</span>
      </div></a>
    </div></body></html>
    """

    parser = FulpParser()

    assert parser.parse_list(html, target_date=date(2026, 9, 16)) == []
    assert any("conflicting owned offer types" in message for message in parser.diagnostics)


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
    al_interval_status = FulpParser._availability(
        "Plazo de solicitudes del 01/09/2026 al 10/09/2026.",
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
    assert al_interval_status[:2] == ("EXPIRED", date(2026, 9, 10))
    assert closing_day_status[:2] == ("OPEN", date(2026, 9, 30))
    assert after_closing_status[:2] == ("EXPIRED", date(2026, 9, 30))


def test_detail_availability_uses_owned_application_text_not_role_wording():
    html = """
    <html><head><link rel="canonical" href="/ofertas/7/detail-deadline"></head><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5>
        <h2 class="titulo">Systems role</h2>
        <div class="Descripcion">Publicación: 01/09/2026. Plazo de solicitud hasta el 10/09/2026.</div>
        <div class="Requisitos">Estudios universitarios finalizados en Ingeniería Informática.</div>
        <div class="Tareas">Administrar tickets cerrados y resolver incidencias.</div>
      </div>
    </body></html>
    """

    record = FulpParser()._parse_detail_record(
        html,
        require_snapshot_identity=True,
        reference_date=date(2026, 9, 16),
    )

    assert record.availability_status == "EXPIRED"
    assert record.deadline_date == date(2026, 9, 10)


@pytest.mark.parametrize("offer_type", ["OFERTA DE EMPLEO", "PROGRAMA INSERTA UNIVERSITARIO"])
def test_listing_availability_does_not_join_type_to_qualification_status(offer_type):
    html = f"""
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/1/role"><div class="row oferta">
        <h3>Ingeniero de software</h3><span class="etiqueta tipo">{offer_type}</span>
        <p class="descripcion">Requisitos: estudios universitarios finalizados en Informática.</p>
      </div></a>
    </div></body></html>
    """

    records = FulpParser().parse_list(html, target_date=date(2026, 9, 16))

    assert [record.offer_id for record in records] == ["1"]
    assert records[0].availability_status == "UNKNOWN"


def test_detail_availability_does_not_join_type_to_qualification_status():
    html = """
    <html><head><link rel="canonical" href="/ofertas/1/role"></head><body>
      <div class="Content-Oferta"><h2 class="titulo">Ingeniero de software</h2>
        <h5>OFERTA DE EMPLEO</h5>
        <div class="Descripcion">Requisitos: estudios universitarios finalizados en Informática.</div>
      </div>
    </body></html>
    """

    record = FulpParser()._parse_detail_record(
        html,
        require_snapshot_identity=True,
        reference_date=date(2026, 9, 16),
    )

    assert record.availability_status == "UNKNOWN"


def test_listing_and_detail_availability_use_al_interval_closing_date():
    listing = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/10/interval"><div class="row oferta">
        <h3>Systems role</h3><span class="etiqueta tipo">OFERTA DE EMPLEO</span>
        <p class="descripcion">Plazo de solicitudes del 01/09/2026 al 10/09/2026.</p>
      </div></a>
    </div></body></html>
    """
    detail = """
    <html><head><link rel="canonical" href="/ofertas/10/interval"></head><body>
      <div class="Content-Oferta"><h2 class="titulo">Systems role</h2>
        <h5>OFERTA DE EMPLEO</h5>
        <div class="Descripcion">Plazo de solicitudes del 01/09/2026 al 10/09/2026.</div>
      </div>
    </body></html>
    """
    reference = date(2026, 9, 16)

    listing_records = FulpParser().parse_list(listing, target_date=reference)
    detail_record = FulpParser()._parse_detail_record(
        detail,
        require_snapshot_identity=True,
        reference_date=reference,
    )

    assert listing_records == []
    assert detail_record.availability_status == "EXPIRED"
    assert detail_record.deadline_date == date(2026, 9, 10)


def test_availability_does_not_treat_closed_duty_tickets_as_offer_closure():
    status, deadline, _, _ = FulpParser._availability(
        "Se requiere experiencia en la gestión de solicitudes y tickets cerrados.",
        date(2026, 9, 16),
    )

    assert (status, deadline) == ("UNKNOWN", None)


def test_record_text_prioritises_explicit_requirements_and_duties_over_long_description_and_profile():
    record = FulpRecord(
        offer_id="6",
        title="Prácticas de sistemas",
        url="https://www.fulp.es/ofertas/6/role",
        offer_type="PRÁCTICAS UNIVERSITARIAS",
        description="Presentación de la empresa. " * 100,
        requirements="Se requiere estar matriculado en un grado universitario. Inglés B1.",
        tasks="Administración de Microsoft 365 y sistemas informáticos.",
        profile="Perfil técnico. " * 200,
    )

    text = FulpParser._record_text(record)

    assert "Se requiere estar matriculado en un grado universitario. Inglés B1." in text[:1500]
    assert "Administración de Microsoft 365 y sistemas informáticos." in text[:1500]
    assert "Presentación de la empresa." in text
    assert "Perfil técnico." in text


def test_record_text_does_not_split_a_keyword_across_deferred_sections():
    value = "Contexto de empresa. " * 28 + "Área: informática."
    record = FulpRecord(
        offer_id="6",
        title="Técnico de proyectos",
        url="https://www.fulp.es/ofertas/6/role",
        offer_type="OFERTA DE EMPLEO",
        requirements="Se requiere experiencia.",
        description=value,
    )
    keyword_filter = KeywordFilter()

    intact = BOPage(
        page_number=1,
        text="Técnico de proyectos Tipo de oferta: OFERTA DE EMPLEO "
        "Se requiere experiencia. "
        + value,
        source="FULP",
    )
    assembled = BOPage(
        page_number=1,
        text=FulpParser._record_text(record),
        source="FULP",
    )

    assert keyword_filter.search_page(intact)
    assert keyword_filter.search_page(assembled)


def test_record_text_keeps_deferred_technical_and_eligibility_units_intact():
    record = FulpRecord(
        offer_id="7",
        title="Técnico de sistemas",
        url="https://www.fulp.es/ofertas/7/role",
        offer_type="PRÁCTICAS UNIVERSITARIAS",
        requirements=(
            "Antecedente sintético. " * 70
            + "Se requiere estar matriculado en un grado universitario y acreditar inglés B1."
        ),
        description=(
            "Contexto sintético. " * 28
            + "Administración de Microsoft 365 para sistemas informáticos."
        ),
    )

    text = FulpParser._record_text(record)

    assert text.count("Se requiere estar matriculado en un grado universitario y acreditar inglés B1.") == 1
    assert text.count("Administración de Microsoft 365 para sistemas informáticos.") == 1
    assert text.index("Requisitos (continuación):") < text.index(
        "Se requiere estar matriculado"
    )
    assert text.index("Descripción de la oferta (continuación):") < text.index(
        "Administración de Microsoft 365"
    )


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
