import datetime
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from job_finder import main
from job_finder.fulp_fetcher import FulpBudgetExceeded, FulpFetcher
from job_finder.fulp_parser import FulpParser


FIXTURE_DIR = Path(__file__).parent / "fixtures"
LISTING = (FIXTURE_DIR / "fulp_listing_observed.html").read_text(encoding="utf-8")


class FixtureFulpFetcher(FulpFetcher):
    detail_calls = []

    def __init__(self, details=None):
        super().__init__(request_get=lambda *args, **kwargs: None)
        self.details = details or {
            offer_id: (FIXTURE_DIR / f"fulp_detail_{offer_id}.html").read_text(encoding="utf-8")
            for offer_id in ("108550", "108571", "110711", "112271", "109630", "110613")
        }
        type(self).detail_calls = []

    def fetch_list(self):
        return LISTING

    def fetch_detail(self, detail_url):
        offer_id = self.detail_id(detail_url)
        type(self).detail_calls.append(detail_url)
        return self.details[offer_id]


def patch_fixture_fetcher(monkeypatch, details=None):
    class BoundFixtureFetcher(FixtureFulpFetcher):
        def __init__(self):
            super().__init__(details=details)

    monkeypatch.setattr(main, "FulpFetcher", BoundFixtureFetcher)
    return BoundFixtureFetcher


def test_fulp_online_scan_fetches_one_detail_per_unique_id_and_shared_filter_keeps_all_six(monkeypatch):
    fetcher_class = patch_fixture_fetcher(monkeypatch)
    findings = main.run_scan(
        target_date=datetime.date(2026, 9, 16),
        sources=["FULP"],
        no_ai=True,
    )

    assert len(fetcher_class.detail_calls) == 6
    assert len(findings) == 6
    assert {finding.source for finding in findings} == {"FULP"}
    assert {FulpFetcher.detail_id(finding.url) for finding in findings} == {
        "108550",
        "108571",
        "110711",
        "112271",
        "109630",
        "110613",
    }


def test_fulp_scan_preserves_detail_failures_and_continues(monkeypatch):
    details = {
        offer_id: (FIXTURE_DIR / f"fulp_detail_{offer_id}.html").read_text(encoding="utf-8")
        for offer_id in ("108550", "108571", "110711", "112271", "109630", "110613")
    }

    class PartialFetcher(FixtureFulpFetcher):
        def __init__(self):
            super().__init__(details=details)

        def fetch_detail(self, detail_url):
            if self.detail_id(detail_url) == "110711":
                raise RuntimeError("fixture detail failed")
            return super().fetch_detail(detail_url)

    parser = FulpParser(fetcher=PartialFetcher())
    pages = parser.scan(target_date=datetime.date(2026, 9, 16))
    assert len(pages) == 5
    assert parser.last_scan["detail_complete"] is False
    assert parser.last_scan["remaining_ids"] == []
    assert any("110711" in message and "skipped" in message for message in parser.diagnostics)


def test_fulp_budget_stop_reports_remaining_ids_and_keeps_prior_results():
    class BudgetFetcher:
        last_response_url = ""

        def __init__(self):
            self.calls = []

        def begin_scan(self):
            pass

        def fetch_list(self):
            return LISTING

        def fetch_detail(self, detail_url):
            offer_id = FulpFetcher.detail_id(detail_url)
            self.calls.append(offer_id)
            if len(self.calls) == 2:
                raise FulpBudgetExceeded("test budget")
            return (FIXTURE_DIR / f"fulp_detail_{offer_id}.html").read_text(encoding="utf-8")

    fetcher = BudgetFetcher()
    parser = FulpParser(fetcher=fetcher)
    pages = parser.scan(target_date=datetime.date(2026, 9, 16))
    assert len(pages) == 1
    assert parser.last_scan["budget_stopped"] is True
    assert parser.last_scan["remaining_ids"] == ["108571", "110711", "112271", "109630", "110613"]
    assert any("Remaining IDs" in message for message in parser.diagnostics)


def test_fulp_duplicate_ids_do_not_duplicate_detail_fetches_but_same_title_different_ids_survive():
    listing = """
    <html><body><h5>3 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/1/same"><div class="row oferta"><h3>Same systems title</h3><p class="fecha">01/09/2026</p><p class="descripcion">Requisitos: sistemas y redes</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span></div></a>
      <a href="/ofertas/001/variant"><div class="row oferta"><h3>Same systems title</h3><p class="fecha">01/09/2026</p><p class="descripcion">Requisitos: sistemas y redes</p><span class="etiqueta tipo">OFERTA EMPLEO</span></div></a>
      <a href="/ofertas/2/other"><div class="row oferta"><h3>Same systems title</h3><p class="fecha">01/09/2026</p><p class="descripcion">Requisitos: sistemas y redes</p><span class="etiqueta tipo">OFERTA DE EMPLEO</span></div></a>
    </div></body></html>
    """
    detail = """
    <html><head><link rel="canonical" href="https://www.fulp.es/ofertas/{id}/same"></head><body>
      <div class="Content-Oferta"><h5>OFERTA DE EMPLEO</h5><h2 class="titulo">Same systems title</h2>
      <div class="Descripcion">Requisitos: sistemas y redes.</div></div>
    </body></html>
    """

    class Fetcher:
        last_response_url = ""

        def __init__(self):
            self.detail_calls = []

        def begin_scan(self):
            pass

        def fetch_list(self):
            return listing

        def fetch_detail(self, url):
            offer_id = FulpFetcher.detail_id(url)
            self.detail_calls.append(offer_id)
            return detail.format(id=offer_id)

    fetcher = Fetcher()
    pages = FulpParser(fetcher=fetcher).scan(target_date=datetime.date(2026, 9, 16))
    assert fetcher.detail_calls == ["1", "2"]
    assert [FulpFetcher.detail_id(page.url) for page in pages] == ["1", "2"]


def test_fulp_fake_ai_payload_keeps_type_eligibility_and_distinct_urls(monkeypatch):
    patch_fixture_fetcher(monkeypatch)
    import job_finder.gemini_validator as gemini_validator

    captured = []

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            captured.append((model, contents, config))
            jobs = json.loads(contents.split("<context>\n", 1)[1].split("\n</context>", 1)[0])
            return SimpleNamespace(
                text=json.dumps(
                    {
                        "results": [
                            {
                                "id": job["id"],
                                "is_tech_job": True,
                                "job_title": "FULP role",
                                "organism": "FULP",
                                "confidence": "high",
                                "reason": "fixture",
                            }
                            for job in jobs
                        ]
                    }
                )
            )

    class CaptureValidator(gemini_validator.GeminiValidator):
        def __init__(self):
            self.enabled = True
            self.client = SimpleNamespace(models=FakeModels())
            self.system_prompt = "fixture system prompt"
            self.user_prompt_template = "<context>\n{jobs_json}\n</context>"

    monkeypatch.setattr(gemini_validator, "GeminiValidator", CaptureValidator)
    monkeypatch.setattr(gemini_validator.types, "GenerateContentConfig", lambda **kwargs: kwargs)

    findings = main.run_scan(sources=["FULP"], no_ai=False)
    assert len(findings) == 6
    assert len(captured) == 1
    payload = json.loads(captured[0][1].split("<context>\n", 1)[1].split("\n</context>", 1)[0])
    assert len(payload) == 6
    assert len({item["text"] for item in payload}) == 6
    assert all(len(item["text"]) <= 1503 for item in payload)
    first_text = payload[0]["text"]
    assert first_text.index("PRÁCTICAS UNIVERSITARIAS") < 1500
    assert first_text.index("cursando grado universitario") < 1500
    assert "B1" in first_text[:1500]
    assert "prácticas extracurriculares" in first_text[:1500]
    assert "cursando grado universitario acorde a la práctica ofertada" in first_text[:1500]
    assert "nivel intermedio de inglés" in first_text[:1500]
    assert "Helpdesk" in first_text[:1500]
    assert "Microsoft 365" in first_text[:1500]


def test_no_ai_does_not_construct_gemini(monkeypatch):
    patch_fixture_fetcher(monkeypatch)
    import job_finder.gemini_validator as gemini_validator

    class ExplodingValidator:
        def __init__(self):
            raise AssertionError("no_ai must prevent Gemini construction")

    monkeypatch.setattr(gemini_validator, "GeminiValidator", ExplodingValidator)
    assert main.run_scan(sources=["FULP"], no_ai=True)


def test_fulp_group_membership_is_once_and_eu_precedence_is_unchanged(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [], ""

    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    for selected, expected, count in (
        ("FULP", {"FULP"}, 1),
        ("ES", {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "INDRA", "FULP", "SODETEGC"}, 11),
        ("EU", {"EPSO", "EURES", "EULISA"}, 3),
        ("ALL", {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "INDRA", "FULP", "SODETEGC", "EPSO", "EURES", "EULISA"}, 14),
    ):
        calls.clear()
        main.run_scan(sources=[selected], no_ai=True)
        assert set(calls) == expected
        assert len(calls) == count


def test_cli_accepts_fulp_source(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(main, "save_markdown_findings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", "FULP", "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()
    assert raised.value.code == 1
    assert calls[0]["sources"] == ["FULP"]


@pytest.mark.parametrize("suffix", [".html", ".htm", ".snapshot"])
def test_offline_fulp_routing_accepts_long_headers_and_keeps_zero_network(tmp_path, capsys, suffix):
    local_file = tmp_path / f"public_offers{suffix}"
    local_file.write_text("x" * 5000 + LISTING, encoding="utf-8")
    findings = main.run_scan(local_file=local_file, no_ai=True)
    output = capsys.readouterr().out
    assert "Scanning local FULP file" in output
    assert findings
    assert all(finding.source == "FULP" for finding in findings)


@pytest.mark.parametrize("fixture_name", ["fulp_listing_observed.html", "fulp_detail_108550.html"])
def test_generic_snapshot_html_routes_fulp_without_long_prefix_or_http(
    tmp_path, capsys, monkeypatch, fixture_name
):
    local_file = tmp_path / "public_offer.snapshot"
    local_file.write_text((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("offline snapshot made HTTP")),
    )
    findings = main.run_scan(local_file=local_file, no_ai=True)

    assert findings
    assert "Scanning local FULP file" in capsys.readouterr().out
    assert all(finding.source == "FULP" for finding in findings)


def test_bounded_fulp_filename_can_route_but_unsupported_html_cannot_become_an_offer(tmp_path, capsys):
    named = tmp_path / "fulp_snapshot.html"
    named.write_text("<html><body><p>not a supported FULP response</p></body></html>", encoding="utf-8")
    assert main.run_scan(local_file=named, no_ai=True) == []
    assert "Scanning local FULP file" in capsys.readouterr().out

    generic = tmp_path / "employment.html"
    generic.write_text("<html><body><p>FULP footer mention only.</p></body></html>", encoding="utf-8")
    assert main.run_scan(local_file=generic, no_ai=True) == []
    assert "Scanning local SAGULPA file" in capsys.readouterr().out


def test_first_filter_negative_regressions_do_not_admit_incidental_products():
    from job_finder.interfaces import BOPage
    from job_finder.keyword_filter import KeywordFilter

    kf = KeywordFilter()
    unrelated = [
        "Administrativo. Experiencia en SAP. Requisitos administrativos.",
        "Auxiliar administrativo. Conocimientos básicos de Microsoft Office. Requisitos.",
        "Atención al cliente. Uso de Microsoft 365. Requisitos de atención.",
    ]
    assert all(
        not kf.search_page(
            BOPage(page_number=1, text=text, source="FULP", detected_organism="FULP")
        )
        for text in unrelated
    )


def test_training_title_is_not_rejected_by_fulp_optional_heuristic(monkeypatch):
    listing = """
    <html><body><h5>1 RESULTADOS ENCONTRADOS</h5><div class="panel_ofertas">
      <a href="/ofertas/77/training"><div class="row oferta"><h3>Prácticas formativas de Ingeniería Informática</h3>
      <p class="fecha">01/09/2026</p><p class="descripcion">Requisitos: prácticas de sistemas informáticos.</p>
      <span class="etiqueta tipo">PRÁCTICAS UNIVERSITARIAS</span></div></a></div></body></html>
    """
    detail = """
    <html><head><link rel="canonical" href="https://www.fulp.es/ofertas/77/training"></head><body>
      <div class="Content-Oferta"><h5>PRÁCTICAS UNIVERSITARIAS</h5><h2 class="titulo">Prácticas formativas de Ingeniería Informática</h2>
      <div class="Requisitos">Requisitos: prácticas de sistemas informáticos.</div></div>
    </body></html>
    """

    class Fetcher:
        last_response_url = ""

        def begin_scan(self):
            pass

        def fetch_list(self):
            return listing

        def fetch_detail(self, url):
            return detail

    monkeypatch.setattr(main, "FulpFetcher", lambda: Fetcher())
    findings = main.run_scan(sources=["FULP"], no_ai=True)
    assert findings
