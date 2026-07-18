from pathlib import Path

from job_finder.html_exporter import generate_html_findings, save_html_findings
from job_finder.interfaces import ParsedAnnouncement


def test_generate_html_findings_with_announcements():
    ann = ParsedAnnouncement(
        organism="AYUNTAMIENTO DE LAS PALMAS",
        description="Convocatoria de plaza de Técnico/a de Sistemas e Informática.",
        page_number=12,
        matched_keywords=["técnico", "sistemas", "informática"],
        source="BOP",
        url="http://www.boplaspalmas.net/boletines/2026/8-4-26/8-4-26.pdf"
    )

    html_str = generate_html_findings([ann])

    assert "<!DOCTYPE html>" in html_str
    assert "AYUNTAMIENTO DE LAS PALMAS" in html_str
    assert "BOP - Página 12" in html_str
    assert "Convocatoria de plaza de Técnico/a de Sistemas e Informática." in html_str
    assert '<span class="chip">técnico</span>' in html_str
    assert '<span class="chip">sistemas</span>' in html_str
    assert 'href="http://www.boplaspalmas.net/boletines/2026/8-4-26/8-4-26.pdf"' in html_str
    assert "target=\"_blank\"" in html_str
    # Verify dark mode styles exist in head style tag
    assert "--bg-color: #121214;" in html_str
    assert "<script" not in html_str


def test_generate_html_findings_empty():
    html_str = generate_html_findings([])

    assert "<!DOCTYPE html>" in html_str
    assert "No IT-related jobs found" in html_str
    assert "Total Findings:</strong> 0" in html_str


def test_save_html_findings_overwrites(tmp_path: Path):
    out_file = tmp_path / "findings.html"
    out_file.write_text("Old content", encoding="utf-8")

    ann = ParsedAnnouncement(
        organism="CABILDO DE GRAN CANARIA",
        description="Bolsa de empleo para Ingenieros de Software.",
        page_number=1,
        matched_keywords=["software"],
        source="BOC",
        url="https://www.gobiernodecanarias.org/boc/test"
    )

    save_html_findings([ann], out_file)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "Old content" not in content
    assert "CABILDO DE GRAN CANARIA" in content
    assert "BOC - Item 1" in content
