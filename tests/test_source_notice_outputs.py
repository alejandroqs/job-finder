from pathlib import Path
from unittest.mock import Mock

from job_finder import main, notifier
from job_finder.html_exporter import generate_html_findings
from job_finder.interfaces import ParsedAnnouncement
from job_finder.sodetegc_parser import SODETEGCParser


FIXTURE = Path(__file__).parent / "fixtures" / "sodetegc_empleo_observed.html"
OBSERVED_HTML = FIXTURE.read_text(encoding="utf-8")
CHANGED_HTML = OBSERVED_HTML.replace(
    "<h2><strong>Convocatorias abiertas:</strong></h2>"
    "<ul><li>Actualmente no hay ninguna convocatoria abierta</li></ul>",
    "<h2><strong>Convocatorias abiertas:</strong></h2>"
    "<ul><li>Convocatoria para una plaza técnica</li></ul>",
    1,
)


def source_notice(description=None):
    return ParsedAnnouncement(
        organism="SODETEGC",
        description=description
        or main._sodetegc_notice(SODETEGCParser.parse(CHANGED_HTML)).description,
        page_number=0,
        matched_keywords=[],
        source="SODETEGC",
        url=SODETEGCParser.URL,
        kind="source_notice",
    )


def test_console_source_notice_is_not_formatted_as_a_job_or_keyword_match():
    notice = source_notice()

    output = main.format_announcement(notice)

    assert "Source-page notice" in output
    assert "Official page for review" in output
    assert "Keywords matched" not in output
    assert "Item 0" not in output


def test_markdown_source_notice_escapes_excerpt_and_uses_notice_counts(tmp_path):
    notice = source_notice("Revisión *urgente* <script>aviso</script> [link](javascript:alert(1))")
    output_path = tmp_path / "notices.md"

    main.save_markdown_findings([notice], output_path)
    output = output_path.read_text(encoding="utf-8")

    assert "# 🔎 Source-page Notices" in output
    assert "**Job Findings:** 0" in output
    assert "**Source Notices:** 1" in output
    assert "**Keywords:**" not in output
    assert "\\*urgente\\*" in output
    assert "\\<script\\>" in output
    assert "Review source page" in output
    assert SODETEGCParser.URL in output


def test_mixed_markdown_counts_jobs_and_notices_separately(tmp_path):
    notice = source_notice()
    job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta laboral de desarrollo de software",
        page_number=1,
        matched_keywords=["desarrollo"],
        source="BOP",
        url="https://example.test/job",
    )
    output_path = tmp_path / "mixed.md"

    main.save_markdown_findings([job, notice], output_path)
    output = output_path.read_text(encoding="utf-8")

    assert "IT Job Findings and Source-page Notices" in output
    assert "**Job Findings:** 1" in output
    assert "**Source Notices:** 1" in output
    assert "**Keywords:** `desarrollo`" in output
    assert "**Keywords:** ``" not in output


def test_job_only_markdown_keeps_existing_summary_and_keywords(tmp_path):
    job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta laboral de desarrollo de software",
        page_number=1,
        matched_keywords=["desarrollo"],
        source="BOP",
    )
    output_path = tmp_path / "jobs.md"

    main.save_markdown_findings([job], output_path)
    output = output_path.read_text(encoding="utf-8")

    assert "# 🔎 IT Job Findings" in output
    assert "**Total Findings:** 1" in output
    assert "**Keywords:** `desarrollo`" in output
    assert "Source Notices" not in output


def test_html_export_marks_notice_and_escapes_untrusted_text():
    notice = source_notice("Revisión <script>alert('x')</script> *manual*")

    output = generate_html_findings([notice])

    assert "Source-page Notices" in output
    assert "Total Source Notices: 1" in output
    assert 'class="job-card source-notice"' in output
    assert "Review Official Page" in output
    assert "Not a confirmed vacancy." in output
    assert "<script>alert" not in output
    assert "&lt;script&gt;" in output
    assert "Keywords Matched" not in output
    assert SODETEGCParser.URL in output


def test_html_mixed_results_count_job_findings_and_notices_separately():
    job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta de empleo",
        page_number=1,
        matched_keywords=["desarrollo"],
        source="BOP",
    )

    output = generate_html_findings([source_notice(), job])

    assert "Job Findings: 1" in output
    assert "Source Notices: 1" in output
    assert 'class="job-card source-notice"' in output
    assert 'class="chip">desarrollo</span>' in output


def test_discord_notice_payload_uses_manual_review_language_and_no_keywords(monkeypatch):
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notifier.requests, "post", lambda *args, **kwargs: payloads.append(kwargs["json"]) or Response())
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    notifier.send_notifications([source_notice("texto *visible* <b>raw</b>")])

    payload = payloads[0]
    embed = payload["embeds"][0]
    assert "Source-page notice" in payload["content"]
    assert "not a confirmed vacancy" in payload["content"]
    assert "\\*visible\\*" in embed["description"]
    assert "Keywords Matched" not in str(embed["fields"])
    assert embed["url"] == SODETEGCParser.URL
    assert "Not a confirmed vacancy" in embed["fields"][0]["value"]


def test_telegram_notice_escapes_html_and_omits_keyword_labels(monkeypatch):
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-for-mocked-call")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-for-mocked-call")
    monkeypatch.setattr(notifier.requests, "post", lambda *args, **kwargs: payloads.append(kwargs) or Response())
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    notifier.send_notifications([source_notice("texto <script>alert('x')</script> & revisión")])

    payload = payloads[0]["json"]
    assert payload["parse_mode"] == "HTML"
    assert "Source-page notice" in payload["text"]
    assert "&lt;script&gt;" in payload["text"]
    assert "&amp; revisión" in payload["text"]
    assert "Keywords:" not in payload["text"]
    assert "Manual review required" in payload["text"]
    assert "Review official page" in payload["text"]
    assert SODETEGCParser.URL in payload["text"]


def test_job_only_notification_payload_keeps_existing_job_labels(monkeypatch):
    payloads = []

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.invalid/webhook")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notifier.requests, "post", lambda *args, **kwargs: payloads.append(kwargs["json"]) or Response())
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)
    job = ParsedAnnouncement(
        organism="Organismo",
        description="Oferta de empleo",
        page_number=2,
        matched_keywords=["software"],
        source="BOP",
    )

    notifier.send_notifications([job])

    assert payloads[0]["content"] == "🚀 **New IT Job Opportunities Found!**"
    assert payloads[0]["embeds"][0]["fields"][1]["name"] == "Keywords Matched"
