import datetime
import io
import json
import sys
import time
from pathlib import Path

import pytest

from job_finder import main
from job_finder.gemini_validator import GeminiValidator
from job_finder.gsc_fetcher import GSCFetcher
from job_finder.interfaces import ParsedAnnouncement


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "gsc_ofertas_de_empleo.html"


class FixtureGSCFetcher(GSCFetcher):
    def fetch(self, target_date):
        del target_date
        return io.BytesIO(FIXTURE_PATH.read_bytes())


IN_WINDOW_ADMINISTRATIVE_HTML = """
<div id="seleccion">
  <div class="projects_holder portfolio_main_holder">
    <article>
      <h5 class="portfolio_title entry_title">
        <a href="/gsc/portfolio_page/ordinary/">01/09/2026 BASES DESARROLLADOR/A</a>
      </h5>
    </article>
    <article>
      <h5 class="portfolio_title entry_title">
        <a href="/gsc/portfolio_page/results/">01/09/2026 RESULTADOS BOLSA DE EMPLEO TECNICO INFORMATICO</a>
      </h5>
    </article>
    <article>
      <h5 class="portfolio_title entry_title">
        <a href="/gsc/portfolio_page/cancelled/">01/09/2026 BASES TECNICO INFORMATICO SE ANULA LA PRESENTE CONVOCATORIA</a>
      </h5>
    </article>
  </div>
</div>
"""


class InlineGSCFetcher(GSCFetcher):
    def fetch(self, target_date):
        del target_date
        return io.BytesIO(IN_WINDOW_ADMINISTRATIVE_HTML.encode("utf-8"))


def test_gsc_runs_through_pipeline_without_ai_or_network(monkeypatch, capsys):
    monkeypatch.setattr(main, "GSCFetcher", FixtureGSCFetcher)

    findings = main.run_scan(
        target_date=datetime.date(2026, 6, 22),
        sources=["GSC"],
        no_ai=True,
    )

    output = capsys.readouterr().out
    assert findings
    assert {finding.source for finding in findings} == {"GSC"}
    assert any("TÉCNICO III" in finding.description for finding in findings)
    assert all("RESULTADOS" not in finding.description for finding in findings)
    assert "GSC included records" in output
    assert "matching announcement" in output


def test_gsc_administrative_notice_filter_runs_before_shared_it_filter(monkeypatch, capsys):
    monkeypatch.setattr(main, "GSCFetcher", InlineGSCFetcher)

    findings = main.run_scan(
        target_date=datetime.date(2026, 9, 1),
        sources=["GSC"],
        no_ai=True,
    )

    assert len(findings) == 1
    assert "BASES DESARROLLADOR/A" in findings[0].description
    assert all("RESULTADOS" not in finding.description for finding in findings)
    assert all("SE ANULA" not in finding.description for finding in findings)
    assert "administrative or cancelled notice" in capsys.readouterr().out


def test_gsc_ai_enabled_orchestration_uses_fake_validator(monkeypatch):
    validator_calls = []

    class FakeValidator:
        enabled = True

        def __init__(self):
            pass

        def validate_batch(self, announcements):
            validator_calls.append(announcements)
            return announcements[:1]

    monkeypatch.setattr(main, "GSCFetcher", FixtureGSCFetcher)
    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", FakeValidator)

    findings = main.run_scan(
        target_date=datetime.date(2026, 6, 22),
        sources=["GSC"],
        no_ai=False,
    )

    assert len(validator_calls) == 1
    assert len(validator_calls[0]) == len(findings) + 1
    assert len(findings) == 1
    assert findings[0].source == "GSC"


def test_source_groups_include_gsc_once_and_eu_remains_unchanged(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [], ""

    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    for selected, expected, count in (
        ("GSC", {"GSC"}, 1),
        ("ES", {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA"}, 8),
        ("EU", {"EPSO", "EURES", "EULISA"}, 3),
        ("ALL", {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "EPSO", "EURES", "EULISA"}, 11),
        (None, {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "EPSO", "EURES", "EULISA"}, 11),
    ):
        calls.clear()
        kwargs = {"sources": [selected], "no_ai": True} if selected else {"no_ai": True}
        main.run_scan(**kwargs)
        assert set(calls) == expected
        assert len(calls) == count


def test_gsc_cli_accepts_explicit_source(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(main, "save_markdown_findings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", "GSC", "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()

    assert raised.value.code == 1
    assert calls[0]["sources"] == ["GSC"]


@pytest.mark.parametrize("suffix", [".html", ".htm"])
def test_offline_gsc_detection_supports_named_generic_and_long_header_files(
    tmp_path, capsys, suffix
):
    named = tmp_path / f"gsc_snapshot{suffix}"
    named.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    main.run_scan(local_file=named, no_ai=True)
    assert "Scanning local GSC file" in capsys.readouterr().out

    generic = tmp_path / f"board_snapshot{suffix}"
    generic.write_text("x" * 5000 + FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    main.run_scan(local_file=generic, no_ai=True)
    assert "Scanning local GSC file" in capsys.readouterr().out


def test_offline_gsc_signature_detection_works_for_unknown_extension(tmp_path, capsys):
    local_file = tmp_path / "snapshot.data"
    local_file.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    main.run_scan(local_file=local_file, no_ai=True)

    assert "Scanning local GSC file" in capsys.readouterr().out

    long_header = tmp_path / "snapshot_long.data"
    long_header.write_text(
        "x" * 5000 + FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )

    main.run_scan(local_file=long_header, no_ai=True)

    assert "Scanning local GSC file" in capsys.readouterr().out


def test_short_gsc_filename_substring_does_not_shortcut_detection(tmp_path, capsys):
    local_file = tmp_path / "gscout.html"
    local_file.write_text(
        "<html><body><p>GSC employment mention without the supported layout.</p>"
        "</body></html>",
        encoding="utf-8",
    )

    main.run_scan(local_file=local_file, no_ai=True)

    assert "Scanning local SAGULPA file" in capsys.readouterr().out


def test_offline_gsc_empty_layout_is_not_replaced_by_unrelated_holder(tmp_path, capsys):
    local_file = tmp_path / "gsc_empty.html"
    local_file.write_text(
        """
        <div id="seleccion"><div class="projects_holder portfolio_main_holder"></div></div>
        <div class="projects_holder portfolio_main_holder">
          <article><h5 class="portfolio_title entry_title">
            <a href="/outside">01/09/2026 BASES DESARROLLADOR/A</a>
          </h5></article>
        </div>
        """,
        encoding="utf-8",
    )

    assert main.run_scan(local_file=local_file, no_ai=True) == []
    output = capsys.readouterr().out
    assert "Scanning local GSC file" in output
    assert "supported but empty" in output


def test_gsc_parser_does_not_request_detail_or_pdf_urls(monkeypatch):
    class NoNetworkFetcher(FixtureGSCFetcher):
        def fetch_list(self):
            raise AssertionError("offline integration must use the fixture stream")

    monkeypatch.setattr(main, "GSCFetcher", NoNetworkFetcher)
    findings = main.run_scan(
        target_date=datetime.date(2026, 6, 22), sources=["GSC"], no_ai=True
    )

    assert findings


def _gsc_candidate(description: str, page_number: int) -> ParsedAnnouncement:
    return ParsedAnnouncement(
        organism="Gestión de Servicios para la Salud y Seguridad en Canarias",
        description=description,
        page_number=page_number,
        matched_keywords=["bases"],
        source="GSC",
        url="https://www.gsccanarias.com/gsc/portfolio_page/shared-process/",
    )


def test_gsc_identity_keeps_shared_url_candidates_independent_in_both_orders(monkeypatch):
    from google import genai

    captured_jobs = []

    class MockResponse:
        def __init__(self, text):
            self.text = text

    class MockModels:
        def generate_content(self, model, contents, config):
            del model, config
            context = contents.split("<context>\n", 1)[1].split("\n</context>", 1)[0]
            jobs = json.loads(context)
            captured_jobs.append(jobs)
            results = []
            for job in jobs:
                keep = "KEEP" in job["text"]
                results.append(
                    {
                        "id": job["id"],
                        "is_tech_job": keep,
                        "job_title": job["text"] if keep else None,
                        "organism": "GSC" if keep else None,
                        "confidence": "high",
                    }
                )
            return MockResponse(json.dumps({"results": results}, ensure_ascii=False))

    class MockClient:
        def __init__(self, api_key):
            del api_key
            self.models = MockModels()

    monkeypatch.setattr(genai, "Client", MockClient)
    candidates = [
        _gsc_candidate("KEEP: 22/06/2026 BASES PROGRAMADOR/A", 1),
        _gsc_candidate("DROP: 23/06/2026 BASES PROGRAMADOR/A", 2),
    ]
    validator = GeminiValidator(api_key="mock-key")

    first = validator.validate_batch(candidates)
    reversed_result = validator.validate_batch(list(reversed(candidates)))

    assert [ann.description for ann in first] == [candidates[0].description]
    assert [ann.description for ann in reversed_result] == [candidates[0].description]
    assert all(len(jobs) == 2 for jobs in captured_jobs)


def test_gsc_exact_duplicates_and_failed_chunks_keep_existing_validator_fallbacks(
    monkeypatch,
):
    from google import genai

    submitted_payloads = []

    class MockModels:
        def generate_content(self, model, contents, config):
            del model, config
            context = contents.split("<context>\n", 1)[1].split("\n</context>", 1)[0]
            submitted_payloads.append(json.loads(context))
            raise RuntimeError("mock chunk failure")

    class MockClient:
        def __init__(self, api_key):
            del api_key
            self.models = MockModels()

    monkeypatch.setattr(genai, "Client", MockClient)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    first = _gsc_candidate("Exact GSC candidate", 1)
    duplicate = _gsc_candidate("Exact GSC candidate", 1)
    second = _gsc_candidate("Second GSC candidate", 2)

    result = GeminiValidator(api_key="mock-key").validate_batch([first, duplicate, second])

    assert result == [first, duplicate, second]
    assert len(submitted_payloads) == 3
    assert all(len(jobs) == 2 for jobs in submitted_payloads)
    assert all(len({job["text"] for job in jobs}) == 2 for jobs in submitted_payloads)
    assert {job["text"] for job in submitted_payloads[0]} == {
        "Exact GSC candidate",
        "Second GSC candidate",
    }


def test_gsc_missing_verdict_keeps_only_the_omitted_shared_url_candidate(monkeypatch):
    from google import genai

    class MockResponse:
        text = json.dumps(
            {
                "results": [
                    {
                        "id": 0,
                        "is_tech_job": False,
                        "job_title": None,
                        "organism": None,
                        "confidence": "high",
                        "reason": "administrative test verdict",
                    }
                ]
            }
        )

    class MockModels:
        def generate_content(self, model, contents, config):
            del model, contents, config
            return MockResponse()

    class MockClient:
        def __init__(self, api_key):
            del api_key
            self.models = MockModels()

    monkeypatch.setattr(genai, "Client", MockClient)
    dropped = _gsc_candidate("DROP candidate with shared URL", 1)
    omitted = _gsc_candidate("OMITTED candidate with shared URL", 2)

    result = GeminiValidator(api_key="mock-key").validate_batch([dropped, omitted])

    assert result == [omitted]
