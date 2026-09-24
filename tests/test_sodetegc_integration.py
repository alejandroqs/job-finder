import io
import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from job_finder import main
from job_finder.interfaces import BOPage, ParsedAnnouncement
from job_finder.sodetegc_fetcher import SODETEGCFetchError
from job_finder.sodetegc_parser import SODETEGCParser


FIXTURE = Path(__file__).parent / "fixtures" / "sodetegc_empleo_observed.html"
OBSERVED_HTML = FIXTURE.read_text(encoding="utf-8")
GEURSA_FIXTURE = Path(__file__).parent / "fixtures" / "geursa_procesos_de_seleccion.html"
GEURSA_HTML = GEURSA_FIXTURE.read_text(encoding="utf-8")
REFERENCE_BLOCK = (
    "<h2><strong>Convocatorias abiertas:</strong></h2>"
    "<ul><li>Actualmente no hay ninguna convocatoria abierta</li></ul>"
)
CHANGED_HTML = OBSERVED_HTML.replace(
    REFERENCE_BLOCK,
    "<h2><strong>Convocatorias abiertas:</strong></h2>"
    "<ul><li>Convocatoria pública para una plaza técnica</li></ul>",
    1,
)


class FixtureFetcher:
    html = OBSERVED_HTML

    def fetch(self):
        return self.html


def use_html(monkeypatch, html):
    class SelectedFetcher:
        def fetch(self):
            return html

    monkeypatch.setattr(main, "SODETEGCFetcher", SelectedFetcher)


def test_baseline_online_scan_skips_keyword_filter_and_gemini(monkeypatch):
    use_html(monkeypatch, OBSERVED_HTML)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("not used by status monitor"))

    assert main.run_scan(sources=["SODETEGC"], no_ai=False) == []


def test_changed_online_scan_produces_typed_notice_without_filter_or_ai(monkeypatch):
    use_html(monkeypatch, CHANGED_HTML)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("notice bypasses keyword filter"))

    findings = main.run_scan(sources=["SODETEGC"], no_ai=False)

    assert len(findings) == 1
    notice = findings[0]
    assert notice.kind == "source_notice"
    assert notice.source == "SODETEGC"
    assert notice.organism == "SODETEGC · aviso de seguimiento"
    assert notice.url == SODETEGCParser.URL
    assert notice.matched_keywords == []
    assert "difiere" in notice.description
    assert "Revisión manual" in notice.description
    assert "no confirma una vacante" in notice.description
    assert "plaza técnica" in notice.description


def test_hidden_active_heading_is_unverifiable_and_produces_no_notice(monkeypatch, capsys):
    hidden_heading_html = CHANGED_HTML.replace(
        "<h2><strong>Convocatorias abiertas:</strong></h2>",
        '<h2><span hidden>Convocatorias abiertas:</span></h2>',
        1,
    )
    use_html(monkeypatch, hidden_heading_html)
    monkeypatch.setattr(
        main, "KeywordFilter", lambda **kwargs: pytest.fail("status monitor is not a job filter")
    )

    findings = main.run_scan(sources=["SODETEGC"], no_ai=False)

    assert findings == []
    assert "SODETEGC UNVERIFIABLE" in capsys.readouterr().err


def test_independent_scans_emit_every_changed_observation_without_state(monkeypatch):
    selected_html = {"value": OBSERVED_HTML}

    class SelectedFetcher:
        def fetch(self):
            return selected_html["value"]

    monkeypatch.setattr(main, "SODETEGCFetcher", SelectedFetcher)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("notice-only scan"))

    counts = []
    for current in (OBSERVED_HTML, CHANGED_HTML, CHANGED_HTML, OBSERVED_HTML):
        selected_html["value"] = current
        counts.append(len(main.run_scan(sources=["SODETEGC"], no_ai=False)))

    assert counts == [0, 1, 1, 0]


def test_repeated_source_selection_emits_at_most_one_sodetegc_notice(monkeypatch):
    use_html(monkeypatch, CHANGED_HTML)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("notice-only scan"))

    findings = main.run_scan(sources=["SODETEGC", "SODETEGC"], no_ai=True)

    assert len(findings) == 1
    assert findings[0].kind == "source_notice"


@pytest.mark.parametrize(
    ("html", "expected_count"),
    [(OBSERVED_HTML, 0), (CHANGED_HTML, 1)],
    ids=["baseline", "changed"],
)
def test_offline_signature_routes_with_online_detector_and_zero_http(
    monkeypatch, tmp_path, html, expected_count
):
    path = tmp_path / "employment.snapshot"
    path.write_text(html, encoding="utf-8")
    monkeypatch.setattr(
        "job_finder.sodetegc_fetcher.requests.get",
        lambda *args, **kwargs: pytest.fail("offline evaluation must not send HTTP"),
    )
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("not a job page"))

    findings = main.run_scan(local_file=path, no_ai=False)

    assert len(findings) == expected_count
    if findings:
        assert findings[0].kind == "source_notice"
        assert findings[0].url == SODETEGCParser.URL


@pytest.mark.parametrize("suffix", [".html", ".htm", ".snapshot"])
def test_filename_alone_does_not_select_sodetegc(monkeypatch, tmp_path, capsys, suffix):
    path = tmp_path / f"sodetegc_snapshot{suffix}"
    path.write_text(
        "<!doctype html><html><head><title>Generic page</title></head>"
        "<body><p>Convocatorias abiertas: aviso</p></body></html>",
        encoding="utf-8",
    )
    class EmptyKeywordFilter:
        def __init__(self, **kwargs):
            pass

        def search_page(self, page):
            return []

    class EmptySagulpaParser:
        def parse(self, source):
            return []

    monkeypatch.setattr(main, "KeywordFilter", EmptyKeywordFilter)
    monkeypatch.setattr(main, "SagulpaParser", EmptySagulpaParser)
    monkeypatch.setattr(
        "job_finder.sodetegc_fetcher.requests.get",
        lambda *args, **kwargs: pytest.fail("offline evaluation must not send HTTP"),
    )

    assert main.run_scan(local_file=path, no_ai=False) == []
    output = capsys.readouterr().out
    assert "Scanning local SODETEGC file" not in output


@pytest.mark.parametrize(
    "suffix", [".html", ".htm", ".snapshot"], ids=["html", "htm", "unknown-extension"]
)
def test_sodetegc_filename_does_not_shadow_other_official_structure(
    monkeypatch, tmp_path, capsys, suffix
):
    path = tmp_path / f"sodetegc_snapshot{suffix}"
    path.write_text(GEURSA_HTML, encoding="utf-8")

    class EmptyKeywordFilter:
        def __init__(self, **kwargs):
            pass

        def search_page(self, page):
            return []

    monkeypatch.setattr(main, "KeywordFilter", EmptyKeywordFilter)
    monkeypatch.setattr(
        "job_finder.sodetegc_fetcher.requests.get",
        lambda *args, **kwargs: pytest.fail("offline evaluation must not send HTTP"),
    )

    main.run_scan(local_file=path, no_ai=True)

    output = capsys.readouterr().out
    assert "Scanning local GEURSA file" in output
    assert "Scanning local SODETEGC file" not in output


def test_fetch_failure_is_diagnostic_and_never_a_change_notice(monkeypatch, capsys):
    class FailedFetcher:
        def fetch(self):
            raise SODETEGCFetchError("Employment-page request timed out.")

    monkeypatch.setattr(main, "SODETEGCFetcher", FailedFetcher)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: pytest.fail("not used by status monitor"))

    assert main.run_scan(sources=["SODETEGC"], no_ai=False) == []
    assert "SODETEGC UNVERIFIABLE" in capsys.readouterr().err


def test_mixed_scan_filters_jobs_and_ai_rejection_cannot_remove_notice(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    use_html(monkeypatch, CHANGED_HTML)
    ordinary_job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta de empleo para desarrollo de software",
        page_number=1,
        matched_keywords=["desarrollo"],
        source="BOP",
        url="https://example.test/job",
    )
    keyword_pages = []

    class FakeKeywordFilter:
        def __init__(self, config_path=None):
            pass

        def search_page(self, page):
            keyword_pages.append(page)
            return [ordinary_job]

    monkeypatch.setattr(main, "KeywordFilter", FakeKeywordFilter)
    original_scan = main._scan_single_source

    def mixed_scan(src, **kwargs):
        if src == "BOP":
            page = BOPage(page_number=1, text="employment", source="BOP")
            return kwargs["kf"].search_page(page), "ordinary scan\n"
        return original_scan(src, **kwargs)

    monkeypatch.setattr(main, "_scan_single_source", mixed_scan)
    ai_calls = []

    class RejectingValidator:
        enabled = True

        def validate_batch(self, announcements):
            ai_calls.append(list(announcements))
            return []

    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", RejectingValidator)

    findings = main.run_scan(sources=["BOP", "SODETEGC"], no_ai=False)

    assert len(keyword_pages) == 1
    assert len(ai_calls) == 1
    assert ai_calls[0] == [ordinary_job]
    assert len(findings) == 1
    assert findings[0].kind == "source_notice"


def test_mixed_scan_preserves_order_of_ai_survivors_and_notice(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    use_html(monkeypatch, CHANGED_HTML)
    ordinary_job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta de empleo para desarrollo de software",
        page_number=1,
        matched_keywords=["desarrollo"],
        source="BOP",
        url="https://example.test/job",
    )

    class FakeKeywordFilter:
        def __init__(self, config_path=None):
            pass

        def search_page(self, page):
            return [ordinary_job]

    monkeypatch.setattr(main, "KeywordFilter", FakeKeywordFilter)
    original_scan = main._scan_single_source

    def mixed_scan(src, **kwargs):
        if src == "BOP":
            return kwargs["kf"].search_page(BOPage(page_number=1, text="employment")), ""
        return original_scan(src, **kwargs)

    monkeypatch.setattr(main, "_scan_single_source", mixed_scan)

    class AcceptingValidator:
        enabled = True

        def validate_batch(self, announcements):
            assert announcements == [ordinary_job]
            return list(announcements)

    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", AcceptingValidator)

    findings = main.run_scan(sources=["SODETEGC", "BOP"], no_ai=False)

    assert [finding.kind for finding in findings] == ["source_notice", "job"]
    assert findings[1] is ordinary_job


def test_cli_accepts_sodetegc_source_and_summarises_notice(monkeypatch, tmp_path, capsys):
    notice = main._sodetegc_notice(SODETEGCParser.parse(CHANGED_HTML))
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: [notice])
    monkeypatch.setattr(main, "save_markdown_findings", Mock())
    notifications = Mock()
    monkeypatch.setattr(main, "send_notifications", notifications)
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", "SODETEGC", "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()

    output = capsys.readouterr().out
    assert raised.value.code == 0
    assert "source notice(s) require manual review" in output
    assert "IT job opening(s)" not in output
    assert notifications.call_count == 1
    assert main.SOURCE_CHOICES.index("SODETEGC") < main.SOURCE_CHOICES.index("EPSO")
    assert "SODETEGC" in main.ES_SOURCES
    assert "SODETEGC" not in main.EU_SOURCES


def test_lambda_summary_counts_notices_separately(monkeypatch):
    notice = main._sodetegc_notice(SODETEGCParser.parse(CHANGED_HTML))
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: [notice])
    notifications = Mock()
    monkeypatch.setattr(main, "send_notifications", notifications)

    result = main.lambda_handler({"sources": ["SODETEGC"]}, None)

    assert result["statusCode"] == 200
    assert result["body"] == "Successfully processed. Found 0 relevant jobs and 1 source notice(s)."
    assert notifications.call_count == 1
