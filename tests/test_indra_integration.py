import datetime
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from job_finder import main
from job_finder.indra_fetcher import IndraFetcher


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SEARCH_FIXTURE = FIXTURE_DIR / "indra_search_page.html"
REMOTE_FIXTURE = FIXTURE_DIR / "indra_detail_remote.html"
FLEXIBLE_FIXTURE = FIXTURE_DIR / "indra_detail_flexible.html"


class FixtureIndraFetcher(IndraFetcher):
    detail_calls = []
    search_calls = []

    def fetch_list(self):
        type(self).search_calls.append("")
        return SEARCH_FIXTURE.read_text(encoding="utf-8")

    def fetch_search(self, term):
        type(self).search_calls.append(term)
        return SEARCH_FIXTURE.read_text(encoding="utf-8")

    def fetch_page(self, url):
        return '<table id="searchresults"><tbody></tbody></table>'

    def fetch_detail(self, detail_url):
        type(self).detail_calls.append(detail_url)
        if detail_url.endswith("978243255/"):
            return FLEXIBLE_FIXTURE.read_text(encoding="utf-8")
        return REMOTE_FIXTURE.read_text(encoding="utf-8")


def _patch_fixture_fetcher(monkeypatch):
    FixtureIndraFetcher.detail_calls = []
    FixtureIndraFetcher.search_calls = []
    monkeypatch.setattr(main, "IndraFetcher", FixtureIndraFetcher)


def test_indra_runs_through_shared_filter_without_ai_or_network(monkeypatch, capsys):
    _patch_fixture_fetcher(monkeypatch)

    findings = main.run_scan(
        target_date=datetime.date(2026, 9, 15),
        sources=["INDRA"],
        no_ai=True,
    )

    assert {finding.source for finding in findings} == {"INDRA"}
    assert len(findings) == 2
    assert len(FixtureIndraFetcher.detail_calls) == 2
    assert all("Python" not in finding.matched_keywords for finding in findings)
    assert "geographic" in capsys.readouterr().out.casefold()


def test_indra_ai_receives_one_candidate_per_deduplicated_job_and_can_remove_one(monkeypatch):
    _patch_fixture_fetcher(monkeypatch)
    validator_calls = []

    class FakeValidator:
        enabled = True

        def __init__(self):
            pass

        def validate_batch(self, announcements):
            validator_calls.append(announcements)
            fake_verdicts = [True, False]
            return [
                announcement
                for announcement, is_tech_job in zip(announcements, fake_verdicts)
                if is_tech_job
            ]

    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", FakeValidator)
    findings = main.run_scan(sources=["INDRA"], no_ai=False)

    assert len(validator_calls) == 1
    assert len(validator_calls[0]) == 2
    assert len(findings) == 1


def test_indra_capture_fake_gemini_payload_keeps_ids_and_metadata_in_window(monkeypatch):
    _patch_fixture_fetcher(monkeypatch)
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
                                "job_title": "Indra role",
                                "organism": "Indra Group",
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

    findings = main.run_scan(sources=["INDRA"], no_ai=False)

    assert len(findings) == 2
    assert len(captured) == 1
    payload = json.loads(captured[0][1].split("<context>\n", 1)[1].split("\n</context>", 1)[0])
    assert [job["id"] for job in payload] == [0, 1]
    assert [job["source"] for job in payload] == ["INDRA", "INDRA"]
    assert all(len(job["text"]) <= 1503 for job in payload)
    assert all(job["text"].index("Requirements:") < 1500 for job in payload)
    assert all("Work mode:" in job["text"] and "Location:" in job["text"] for job in payload)


def test_indra_geographic_rejection_happens_before_ai(monkeypatch):
    class HybridFixtureFetcher(FixtureIndraFetcher):
        def fetch_detail(self, detail_url):
            return super().fetch_detail(detail_url).replace("Remoto", "Híbrido").replace(
                "Indiferente", "Híbrido"
            )

    monkeypatch.setattr(main, "IndraFetcher", HybridFixtureFetcher)

    import job_finder.gemini_validator as gemini_validator

    class ExplodingValidator:
        def __init__(self):
            raise AssertionError("geographic rejection must prevent AI construction")

    monkeypatch.setattr(gemini_validator, "GeminiValidator", ExplodingValidator)

    assert main.run_scan(sources=["INDRA"], no_ai=False) == []


def test_indra_country_rejection_happens_before_shared_filter_even_with_no_ai(monkeypatch):
    class PortugalFixtureFetcher(FixtureIndraFetcher):
        def fetch_detail(self, detail_url):
            detail = super().fetch_detail(detail_url)
            return detail.replace(
                '<div data-careersite-propertyid="description">',
                '<div class="country-field"><span class="joblayouttoken-label">País:</span>'
                '<span>PT</span></div>'
                '<div data-careersite-propertyid="description">',
            )

    class ExplodingKeywordFilter:
        portal_search_keywords = []

        @staticmethod
        def should_reject_title(title):
            del title
            return False

        @staticmethod
        def search_page(page):
            del page
            raise AssertionError("country-rejected offers must not reach the shared filter")

    monkeypatch.setattr(main, "IndraFetcher", PortugalFixtureFetcher)
    monkeypatch.setattr(main, "KeywordFilter", lambda **kwargs: ExplodingKeywordFilter())

    assert main.run_scan(sources=["INDRA"], no_ai=True) == []


def test_indra_no_ai_skips_validator_construction(monkeypatch):
    _patch_fixture_fetcher(monkeypatch)

    class ExplodingValidator:
        def __init__(self):
            raise AssertionError("Gemini must not be constructed")

    import job_finder.gemini_validator as gemini_validator

    monkeypatch.setattr(gemini_validator, "GeminiValidator", ExplodingValidator)
    assert main.run_scan(sources=["INDRA"], no_ai=True)


def test_search_term_does_not_create_shared_keyword_match(monkeypatch, tmp_path):
    _patch_fixture_fetcher(monkeypatch)
    config = tmp_path / "keywords.yaml"
    config.write_text(
        """
it_keywords:
  - 'cobol'
contest_anchors:
  - 'selección'
boilerplate_exclusions: []
title_reject_absolute: []
title_reject_relative: []
portal_search_keywords:
  - Python
""",
        encoding="utf-8",
    )

    import job_finder.gemini_validator as gemini_validator

    class ExplodingValidator:
        def __init__(self):
            raise AssertionError("first-filter rejection must prevent AI")

    monkeypatch.setattr(gemini_validator, "GeminiValidator", ExplodingValidator)
    findings = main.run_scan(sources=["INDRA"], config_path=config, no_ai=False)

    assert findings == []
    assert FixtureIndraFetcher.search_calls == ["Python"]


def test_indra_source_groups_include_it_once_and_leave_eu_unchanged(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [], ""

    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    for selected, expected, count in (
        ("INDRA", {"INDRA"}, 1),
        ("ES", {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "INDRA", "FULP", "SODETEGC"}, 11),
        ("EU", {"EPSO", "EURES", "EULISA"}, 3),
        (
            "ALL",
            {"BOP", "BOC", "BOE", "SAGULPA", "GUAGUAS", "GEURSA", "GSC", "AENA", "INDRA", "FULP", "SODETEGC", "EPSO", "EURES", "EULISA"},
            14,
        ),
    ):
        calls.clear()
        main.run_scan(sources=[selected], no_ai=True)
        assert set(calls) == expected
        assert len(calls) == count


def test_cli_accepts_indra_source(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(main, "save_markdown_findings", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", "INDRA", "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()

    assert raised.value.code == 1
    assert calls[0]["sources"] == ["INDRA"]


@pytest.mark.parametrize("suffix", [".html", ".htm"])
def test_offline_indra_detection_uses_bounded_structure_and_long_headers(
    tmp_path, capsys, suffix
):
    local_file = tmp_path / f"career_snapshot{suffix}"
    local_file.write_text(
        "x" * 5000 + REMOTE_FIXTURE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    findings = main.run_scan(local_file=local_file, no_ai=True)

    assert "Scanning local INDRA file" in capsys.readouterr().out
    assert findings


def test_offline_indra_filename_token_and_listing_limit(tmp_path, capsys):
    named = tmp_path / "indra_snapshot.html"
    named.write_text(SEARCH_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert main.run_scan(local_file=named, no_ai=True) == []
    assert "Scanning local INDRA file" in capsys.readouterr().out

    generic = tmp_path / "employment.html"
    generic.write_text(
        "<html><body><p>Indra Group careers mention only.</p></body></html>",
        encoding="utf-8",
    )
    assert main.run_scan(local_file=generic, no_ai=True) == []
    assert "Scanning local SAGULPA file" in capsys.readouterr().out


def test_indra_offline_detail_does_not_call_fetcher(monkeypatch, tmp_path):
    class ExplodingFetcher:
        def __init__(self):
            raise AssertionError("offline parsing must not construct a network fetcher")

    monkeypatch.setattr(main, "IndraFetcher", ExplodingFetcher)
    local_file = tmp_path / "indra_detail.html"
    local_file.write_text(REMOTE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    findings = main.run_scan(local_file=local_file, no_ai=True)

    assert findings
