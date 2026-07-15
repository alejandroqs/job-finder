import io
import datetime
from pathlib import Path
import pytest
from unittest.mock import MagicMock

from job_finder.interfaces import BOPage
from job_finder.keyword_filter import KeywordFilter
from job_finder.aena_fetcher import AenaFetcher
from job_finder.aena_parser import AenaParser

@pytest.fixture
def aena_list_html_path() -> Path:
    """Fixture that returns the path to the offline Aena list view HTML fixture."""
    path = Path(__file__).parent / "fixtures" / "aena_ofertas_empleo.html"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path

@pytest.fixture
def aena_detail_html_path() -> Path:
    """Fixture that returns the path to the offline Aena detail page HTML fixture."""
    path = Path(__file__).parent / "fixtures" / "aena_pagina_oferta.html"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path

@pytest.fixture
def aena_pdf_path() -> Path:
    """Fixture that returns the path to the offline Aena bases PDF fixture."""
    path = Path(__file__).parent / "fixtures" / "aena_bases_convocatoria_oferta.pdf"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path


def test_aena_parser_list_extraction(aena_list_html_path):
    """
    Verifies that the AenaParser correctly parses the list HTML,
    resolving links and extracting active job openings.
    """
    parser = AenaParser()
    with open(aena_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    active_jobs = parser.parse_list(list_html, target_date=datetime.date(2000, 1, 1))

    # In our aena_ofertas_empleo.html fixture:
    # 11 entries are present, but 5 are rejected by the fast-title filter:
    # - 2 formativo (Absolute)
    # - 2 mantenimiento (Relative)
    # - 1 bombero/a (Relative)
    # We expect 6 job entries to remain.
    assert len(active_jobs) == 6

    # First entry verification
    job = active_jobs[0]
    assert job["title"] == "24 PLAZAS TITULADOS/AS UNIVERSITARIOS/AS"
    assert job["url"] == "PFSrv?accion=avisos&codigo=20260630&titulo=24 PLAZAS TITULADOS/AS UNIVERSITARIOS/AS"
    assert isinstance(job["closing_date"], datetime.date)
    assert job["closing_date"] == datetime.date(2026, 7, 14)

    # Verify that skipped titles are not present
    titles = [j["title"] for j in active_jobs]
    assert not any("BOMBERO" in t for t in titles)
    assert not any("FORMATIV" in t for t in titles)
    assert not any("MANTENIMIENTO" in t for t in titles)


def test_aena_parser_expiration_filter(aena_list_html_path):
    """
    Verifies that the AenaParser correctly filters out expired job openings.
    """
    parser = AenaParser()
    with open(aena_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    # The fixture has jobs with closing dates around 2026-07-14.
    # If we set the target_date to 2026-07-15, all of them should be filtered out.
    active_jobs = parser.parse_list(list_html, target_date=datetime.date(2026, 7, 15))
    
    # We expect 0 job entries to remain.
    assert len(active_jobs) == 0

def test_aena_parser_detail_parsing(aena_detail_html_path):
    """
    Verifies that the AenaParser correctly extracts the bases PDF links.
    """
    parser = AenaParser()
    with open(aena_detail_html_path, "r", encoding="utf-8") as f:
        detail_html = f.read()

    pdf_urls = parser.parse_detail(detail_html)
    assert len(pdf_urls) > 0
    
    # Verify that we extracted at least the main bases document
    found_bases = any("docId=0050569EE56D1FE19DA64FB28EFE9382" in url for url in pdf_urls)
    assert found_bases
    
    # Verify the structure of the URLs
    for url in pdf_urls:
        assert "documentos?get" in url
        assert "secKey=" in url


def test_aena_parser_online_simulation(aena_list_html_path, aena_detail_html_path, aena_pdf_path):
    """
    Simulates the online scan where parser invokes the fetcher and deep-scans the PDF.
    """
    # Create a mock fetcher
    mock_fetcher = MagicMock(spec=AenaFetcher)
    with open(aena_detail_html_path, "r", encoding="utf-8") as f:
        detail_html = f.read()
    mock_fetcher.fetch_detail.return_value = detail_html
    mock_fetcher.fetch_pdf.return_value = aena_pdf_path.read_bytes()

    parser = AenaParser(fetcher=mock_fetcher)
    with open(aena_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    # Filter with target_date <= closing_date (Target: 2026-07-14)
    # The first 2 jobs in fixture have closing_date = 2026-07-14. Others are older.
    target_date = datetime.date(2026, 7, 14)
    pages = parser.parse(io.BytesIO(list_html.encode("utf-8")), target_date=target_date)

    # The mock fetcher is called for active jobs (1 job left since the other is rejected as Formativo)
    # Each PDF parses to several pages. Let's assert we get BOPage objects.
    assert len(pages) > 0
    assert mock_fetcher.fetch_detail.call_count == 1
    
    # 2 targeted PDFs (Bases, Requisitos) are found on the detail page, so 1 job * 2 PDFs = 2 fetch_pdf calls
    assert mock_fetcher.fetch_pdf.call_count == 2

    # Check first page properties
    first_page = pages[0]
    assert first_page.source == "AENA"
    assert first_page.detected_organism == "Aena"
    assert "CONVOCATORIA: 24 PLAZAS TITULADOS/AS UNIVERSITARIOS/AS" in first_page.text
    # pdfplumber should have extracted some content from aena_bases_convocatoria_oferta.pdf
    assert len(first_page.text) > 100
