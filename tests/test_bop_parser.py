import io
import datetime
from pathlib import Path
import pytest
import requests

from job_finder.text_cleaner import clean_text, remove_hyphenation, collapse_line_breaks
from job_finder.keyword_filter import KeywordFilter, strip_accents
from job_finder.bop_parser import BOPParser
from job_finder.bop_fetcher import BOPFetcher
from job_finder.interfaces import BOPage

# =====================================================================
# Text Cleaner Tests
# =====================================================================

def test_unicode_normalization():
    # Composed and decomposed accented characters should be normalized and cleaned properly
    decomposed = "informaci\u006f\u0301n"  # 'o' + combining acute accent
    cleaned = clean_text(decomposed)
    assert cleaned == "información"

def test_remove_hyphenation():
    hyphenated = "El técnico de infor-\nmática de la plaza..."
    cleaned = remove_hyphenation(hyphenated)
    assert "informática" in cleaned
    assert "infor-\nmática" not in cleaned

def test_collapse_line_breaks():
    spaced_text = "Esta es una línea.\nEsta es otra línea que continúa.\n\nEste es un nuevo párrafo."
    collapsed = collapse_line_breaks(spaced_text)
    # Single newlines are replaced with space, double newlines are preserved
    assert "Esta es una línea. Esta es otra línea que continúa." in collapsed
    assert "\n\n" in collapsed
    assert "Este es un nuevo párrafo." in collapsed

def test_remove_boilerplate():
    text = "BOLETÍN OFICIAL DE LA PROVINCIA DE LAS PALMAS\nN.º 60 - 20 de mayo de 2026\nContenido de la página"
    cleaned = clean_text(text)
    assert "BOLETÍN" not in cleaned
    assert "N.º 60" not in cleaned
    assert "Contenido de la página" in cleaned

# =====================================================================
# Keyword Filter Tests
# =====================================================================

def test_accent_stripping():
    assert strip_accents("informática") == "informatica"
    assert strip_accents("TÉCNICO") == "TECNICO"
    assert strip_accents("sistemas y redes") == "sistemas y redes"

def test_keyword_matching_step1_and_step2():
    kf = KeywordFilter()
    
    # 1. Matching IT keyword AND contest anchor (Should pass)
    page_pass = BOPage(
        page_number=1,
        text="Se convoca una plaza de técnico de sistemas microinformáticos y redes para el Ayuntamiento.",
        detected_organism="Ayuntamiento de Teror"
    )
    results = kf.search_page(page_pass)
    assert len(results) == 1
    assert results[0].organism == "Ayuntamiento de Teror"
    assert any("sistemas" in kw for kw in results[0].matched_keywords)
    
    # 2. Matching IT keyword but NO contest anchor (Should be filtered out as noise)
    page_noise = BOPage(
        page_number=2,
        text="Se ha actualizado el sistema informático de la oficina para mejorar la eficiencia interna.",
        detected_organism="Ayuntamiento de Teror"
    )
    results_noise = kf.search_page(page_noise)
    assert len(results_noise) == 0  # No anchor word (plaza, bases, convocatoria, etc.)

    # 3. No matching IT keyword (Should fail step 1)
    page_fail = BOPage(
        page_number=3,
        text="Se aprueban las bases para la contratación de un geógrafo.",
        detected_organism="Ayuntamiento de Teror"
    )
    results_fail = kf.search_page(page_fail)
    assert len(results_fail) == 0

def test_case_insensitive_matching():
    kf = KeywordFilter()
    page = BOPage(
        page_number=4,
        text="CONVOCATORIA PARA CUBRIR 1 PLAZA DE INGENIERO DE SOFTWARE.",
        detected_organism="CABILDO DE GRAN CANARIA"
    )
    results = kf.search_page(page)
    assert len(results) == 1
    assert "software" in results[0].matched_keywords[0]

def test_spanish_false_positives_exclusion():
    kf = KeywordFilter()
    
    # 1. Administrative boilerplate mentioning "aplicación informática" (Should be excluded)
    page_boilerplate = BOPage(
        page_number=10,
        text="Convocatoria de oposiciones para la cobertura de plazas de Auxiliar Administrativo. Las solicitudes se presentarán obligatoriamente por medios electrónicos a través de la aplicación informática habilitada en la sede electrónica de la Mancomunidad.",
        detected_organism="Mancomunidad de Municipios"
    )
    results = kf.search_page(page_boilerplate)
    assert len(results) == 0

    # 2. Genuine IT vacancy that happens to mention "aplicación informática" as well (Should match)
    page_genuine = BOPage(
        page_number=11,
        text="Convocatoria para proveer una plaza de Técnico/a de Informática. Las funciones principales incluyen el mantenimiento de la red local y el soporte al usuario. Las solicitudes se presentarán mediante la aplicación informática habilitada.",
        detected_organism="Ayuntamiento de Arucas"
    )
    results_genuine = kf.search_page(page_genuine)
    assert len(results_genuine) == 1
    assert results_genuine[0].organism == "Ayuntamiento de Arucas"
    assert any("inform" in kw for kw in results_genuine[0].matched_keywords)

# =====================================================================
# BOP Fetcher URL Generation Tests
# =====================================================================

def test_fetcher_url_building():
    fetcher = BOPFetcher()
    
    # Single-digit day and month
    date1 = datetime.date(2026, 4, 8)
    assert fetcher.get_download_url(date1) == "http://www.boplaspalmas.net/boletines/2026/8-4-26/8-4-26.pdf"
    
    # Double-digit day and single-digit month
    date2 = datetime.date(2026, 5, 20)
    assert fetcher.get_download_url(date2) == "http://www.boplaspalmas.net/boletines/2026/20-5-26/20-5-26.pdf"
    
    # Double-digit day and double-digit month
    date3 = datetime.date(2025, 12, 15)
    assert fetcher.get_download_url(date3) == "http://www.boplaspalmas.net/boletines/2025/15-12-25/15-12-25.pdf"

# =====================================================================
# PDF Parser Integration Tests (Using Fixture)
# =====================================================================

def test_parser_with_binary_fixture(sample_pdf_stream):
    """
    Integration test utilizing pytest.fixture with the binary PDF.
    Asserts no UnicodeDecodeError is raised and pages are parsed correctly.
    """
    parser = BOPParser()
    
    # This must parse the BytesIO stream without throwing UnicodeDecodeError or any other exception
    parsed_pages = parser.parse(sample_pdf_stream)
    
    # Since we are filtering by "III. ADMINISTRACIÓN LOCAL", if the sample PDF contains it, 
    # we should get some pages. Let's assert basic properties.
    assert isinstance(parsed_pages, list)
    
    # Let's assert that each page has a valid page number and non-empty text
    for page in parsed_pages:
        assert page.page_number > 0
        assert len(page.text.strip()) > 0
        assert page.section != ""
        assert page.detected_organism != ""

# =====================================================================
# BOP Fetcher Latest Available Fallback Tests
# =====================================================================

def test_fetch_latest_success(monkeypatch):
    """Verifies fetch_latest correctly parses index HTML and falls back successfully."""
    fetcher = BOPFetcher()
    
    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code
            
        def raise_for_status(self):
            pass
            
        def iter_content(self, chunk_size=8192):
            yield b"%PDF-mock-content"
            
    def mock_get(url, *args, **kwargs):
        if "main1.php" in url:
            html = """
            <html>
            <td width="33" height="22" bgcolor="#FFCC33">
              <a href="../boletines/2026/20-5-26/20-5-26.pdf">Descargar Boletín</a>
            </td>
            </html>
            """
            return MockResponse(html)
        elif "20-5-26.pdf" in url:
            return MockResponse("", status_code=200)
        return MockResponse("", status_code=404)
        
    monkeypatch.setattr(requests, "get", mock_get)
    
    pdf_stream, latest_date = fetcher.fetch_latest()
    assert latest_date == datetime.date(2026, 5, 20)
    assert pdf_stream.read() == b"%PDF-mock-content"
