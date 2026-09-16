import datetime
import io
import sys
from pathlib import Path

import pytest

from job_finder import main
from job_finder.guaguas_fetcher import GuaguasFetcher


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "guaguas_trabaja_con_nosotros.html"


class FixtureGuaguasFetcher(GuaguasFetcher):
    detail_calls = 0

    def fetch(self, target_date):
        del target_date
        return io.BytesIO(FIXTURE_PATH.read_bytes())

    def fetch_detail(self, detail_url):
        del detail_url
        type(self).detail_calls += 1
        raise AssertionError("Guaguas list parsing must not fetch one detail per card")


def test_guaguas_runs_through_pipeline_without_ai_or_network(monkeypatch):
    FixtureGuaguasFetcher.detail_calls = 0
    monkeypatch.setattr(main, "GuaguasFetcher", FixtureGuaguasFetcher)

    findings = main.run_scan(
        target_date=datetime.date(2026, 6, 15),
        sources=["GUAGUAS"],
        no_ai=True,
    )

    assert FixtureGuaguasFetcher.detail_calls == 0
    assert {finding.source for finding in findings} == {"GUAGUAS"}
    assert any("Sistemas y Redes" in finding.description for finding in findings)
    assert any("Programador/a" in finding.description for finding in findings)


def test_source_groups_include_guaguas_and_keep_eu_unchanged(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [], ""

    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    main.run_scan(sources=["GUAGUAS"], no_ai=True)
    assert calls == ["GUAGUAS"]

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
        "FULP",
    }
    assert len(calls) == 10

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
        "FULP",
        "EPSO",
        "EURES",
        "EULISA",
    }
    assert len(calls) == 13


def test_offline_detection_reads_beyond_header_prefix(tmp_path, capsys):
    local_file = tmp_path / "board_snapshot.html"
    local_file.write_text("x" * 5000 + FIXTURE_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    findings = main.run_scan(local_file=local_file, no_ai=True)

    output = capsys.readouterr().out
    assert "Scanning local GUAGUAS file" in output
    assert any(finding.source == "GUAGUAS" for finding in findings)


@pytest.mark.parametrize("container_class", ["contenido_seccion carnets", "contenido-seccion carnets"])
def test_offline_detection_supports_each_guaguas_container_variant(
    tmp_path, capsys, container_class
):
    html = FIXTURE_PATH.read_text(encoding="utf-8").replace(
        "contenido_seccion carnets", container_class
    )
    local_file = tmp_path / "board_snapshot.html"
    local_file.write_text(html, encoding="utf-8")

    findings = main.run_scan(local_file=local_file, no_ai=True)

    assert "Scanning local GUAGUAS file" in capsys.readouterr().out
    assert any(finding.source == "GUAGUAS" for finding in findings)


def test_generic_employment_phrases_do_not_trigger_guaguas_detection(tmp_path, capsys):
    local_file = tmp_path / "employment.html"
    local_file.write_text(
        """
        <html><body>
          <h1>Trabaja con nosotros</h1>
          <h2>Bases reguladoras</h2>
          <p>Vacantes disponibles en varios departamentos.</p>
        </body></html>
        """,
        encoding="utf-8",
    )

    findings = main.run_scan(local_file=local_file, no_ai=True)

    assert "Scanning local SAGULPA file" in capsys.readouterr().out
    assert findings == []


@pytest.mark.parametrize(
    ("filename", "source"),
    [("eulisa_careers.html", "EULISA"), ("aena_careers.html", "AENA")],
)
def test_neighbouring_named_html_routing_remains_stable(tmp_path, capsys, filename, source):
    local_file = tmp_path / filename
    local_file.write_text("<html><body></body></html>", encoding="utf-8")

    main.run_scan(local_file=local_file, no_ai=True)

    assert f"Scanning local {source} file" in capsys.readouterr().out
