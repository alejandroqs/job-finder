import datetime
import io
import sys
from pathlib import Path

import pytest

from job_finder import main
from job_finder.geursa_fetcher import GeursaFetcher


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "geursa_procesos_de_seleccion.html"


class FixtureGeursaFetcher(GeursaFetcher):
    detail_calls = 0

    def fetch(self, target_date):
        del target_date
        return io.BytesIO(FIXTURE_PATH.read_bytes())

    def fetch_detail(self, detail_url):
        del detail_url
        type(self).detail_calls += 1
        raise AssertionError("GEURSA list parsing must not fetch detail or PDF URLs")


def test_geursa_runs_through_pipeline_without_ai_or_network(monkeypatch):
    FixtureGeursaFetcher.detail_calls = 0
    monkeypatch.setattr(main, "GeursaFetcher", FixtureGeursaFetcher)

    findings = main.run_scan(
        target_date=datetime.date(1900, 1, 1),
        sources=["GEURSA"],
        no_ai=True,
    )

    assert FixtureGeursaFetcher.detail_calls == 0
    assert findings
    assert {finding.source for finding in findings} == {"GEURSA"}
    assert any("Tecnologías de la Información" in finding.description for finding in findings)


def test_geursa_ai_enabled_orchestration_uses_fake_validator(monkeypatch):
    FixtureGeursaFetcher.detail_calls = 0
    validator_calls = []

    class FakeValidator:
        enabled = True

        def __init__(self):
            pass

        def validate_batch(self, announcements):
            validator_calls.append(announcements)
            return announcements[:1]

    monkeypatch.setattr(main, "GeursaFetcher", FixtureGeursaFetcher)
    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", FakeValidator)

    findings = main.run_scan(
        target_date=datetime.date(2026, 9, 9),
        sources=["GEURSA"],
        no_ai=False,
    )

    assert FixtureGeursaFetcher.detail_calls == 0
    assert len(validator_calls) == 1
    assert validator_calls[0]
    assert len(findings) == 1
    assert findings[0].source == "GEURSA"


def test_source_groups_include_geursa_and_keep_eu_unchanged(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [], ""

    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    main.run_scan(sources=["GEURSA"], no_ai=True)
    assert calls == ["GEURSA"]

    calls.clear()
    main.run_scan(sources=["ES"], no_ai=True)
    assert set(calls) == {
        "BOP",
        "BOC",
        "BOE",
        "SAGULPA",
        "GUAGUAS",
        "GEURSA",
        "GSC",
        "AENA",
        "INDRA",
    }
    assert len(calls) == 9

    calls.clear()
    main.run_scan(sources=["EU"], no_ai=True)
    assert set(calls) == {"EPSO", "EURES", "EULISA"}
    assert len(calls) == 3

    calls.clear()
    main.run_scan(sources=["ALL"], no_ai=True)
    assert set(calls) == {
        "BOP",
        "BOC",
        "BOE",
        "SAGULPA",
        "GUAGUAS",
        "GEURSA",
        "GSC",
        "AENA",
        "INDRA",
        "EPSO",
        "EURES",
        "EULISA",
    }
    assert len(calls) == 12

    calls.clear()
    main.run_scan(no_ai=True)
    assert set(calls) == {
        "BOP",
        "BOC",
        "BOE",
        "SAGULPA",
        "GUAGUAS",
        "GEURSA",
        "GSC",
        "AENA",
        "INDRA",
        "EPSO",
        "EURES",
        "EULISA",
    }
    assert len(calls) == 12


def test_offline_detection_supports_named_generic_long_header_and_htm_files(
    tmp_path, capsys
):
    named = tmp_path / "geursa_snapshot.html"
    named.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    main.run_scan(local_file=named, no_ai=True)
    assert "Scanning local GEURSA file" in capsys.readouterr().out

    generic = tmp_path / "board_snapshot.html"
    generic.write_text("x" * 5000 + FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    findings = main.run_scan(local_file=generic, no_ai=True)
    assert "Scanning local GEURSA file" in capsys.readouterr().out
    assert any(finding.source == "GEURSA" for finding in findings)

    generic_htm = tmp_path / "board_snapshot.htm"
    generic_htm.write_text(FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    main.run_scan(local_file=generic_htm, no_ai=True)
    assert "Scanning local GEURSA file" in capsys.readouterr().out


def test_offline_detection_rejects_generic_geursa_mention_and_preserves_neighbours(
    tmp_path, capsys
):
    generic = tmp_path / "employment.html"
    generic.write_text(
        "<html><body><p>GEURSA procesos de selección</p></body></html>",
        encoding="utf-8",
    )
    assert main.run_scan(local_file=generic, no_ai=True) == []
    assert "Scanning local SAGULPA file" in capsys.readouterr().out

    for filename, source in (
        ("guaguas_careers.html", "GUAGUAS"),
        ("eulisa_careers.html", "EULISA"),
        ("aena_careers.html", "AENA"),
    ):
        local_file = tmp_path / filename
        local_file.write_text("<html><body></body></html>", encoding="utf-8")
        main.run_scan(local_file=local_file, no_ai=True)
        assert f"Scanning local {source} file" in capsys.readouterr().out


def test_cli_accepts_explicit_geursa_source(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        main,
        "run_scan",
        lambda **kwargs: calls.append(kwargs) or [],
    )
    monkeypatch.setattr(main, "save_markdown_findings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", "GEURSA", "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()

    assert raised.value.code == 1
    assert calls[0]["sources"] == ["GEURSA"]
    assert calls[0]["no_ai"] is True
