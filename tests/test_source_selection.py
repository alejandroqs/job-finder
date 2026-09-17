import io
import sys
from unittest.mock import Mock

import pytest

from job_finder import main

@pytest.fixture
def fake_live_scan(monkeypatch):
    calls = []

    def fake_scan_single_source(src, **kwargs):
        calls.append(src)
        return [Mock(source=src)], ""

    monkeypatch.setattr(main, "KeywordFilter", lambda config_path=None: object())
    monkeypatch.setattr(main, "_scan_single_source", fake_scan_single_source)
    monkeypatch.setattr(main, "send_notifications", Mock())
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    return calls


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (
            None,
            [
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
            ],
        ),
        (
            [],
            [
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
            ],
        ),
        (
            ["ALL"],
            [
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
            ],
        ),
        (
            ["BOP", "ALL", "EULISA"],
            [
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
            ],
        ),
        (["ES", "EU"], ["EPSO", "EURES", "EULISA"]),
        (["BOP", "EU"], ["EPSO", "EURES", "EULISA"]),
        (["EU", "ES"], ["EPSO", "EURES", "EULISA"]),
        (
            ["ES", "BOP"],
            [
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
            ],
        ),
        (["FULP", "BOE"], ["FULP", "BOE"]),
    ],
)
def test_run_scan_selection_preserves_precedence_and_result_order(
    fake_live_scan, selected, expected
):
    kwargs = {"no_ai": True}
    if selected is not None:
        kwargs["sources"] = selected

    findings = main.run_scan(**kwargs)

    assert [finding.source for finding in findings] == expected
    assert sorted(fake_live_scan) == sorted(expected)


@pytest.mark.parametrize("source", ["BOP", "EULISA", "EU", "ES", "ALL"])
def test_cli_accepts_sources_and_groups(monkeypatch, tmp_path, source):
    calls = []
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setattr(main, "run_scan", lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(main, "save_markdown_findings", Mock())
    monkeypatch.setattr(main, "send_notifications", Mock())
    monkeypatch.setattr(
        sys,
        "argv",
        ["job-finder", "--source", source, "--no-ai", "--output", str(tmp_path / "out.md")],
    )

    with pytest.raises(SystemExit) as raised:
        main.main()

    assert raised.value.code == 1
    assert calls[0]["sources"] == [source]
