import io
import datetime
from pathlib import Path
import pytest

from job_finder.interfaces import BaseFetcher, BOPage
from job_finder.keyword_filter import KeywordFilter

# Import our future classes (they will fail to import in TDD Red Phase)
try:
    from job_finder.sagulpa_fetcher import SagulpaFetcher
    from job_finder.sagulpa_parser import SagulpaParser
except ImportError:
    # Allow imports to fail gracefully during initial TDD setup before files are written
    SagulpaFetcher = None
    SagulpaParser = None

@pytest.fixture
def sagulpa_list_html_path() -> Path:
    """Fixture that returns the path to the offline Sagulpa list view HTML fixture."""
    path = Path(__file__).parent / "fixtures" / "sagulpa_ofertas_empleo.html"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path

@pytest.fixture
def sagulpa_detail_html_path() -> Path:
    """Fixture that returns the path to the offline Sagulpa detail page HTML fixture."""
    path = Path(__file__).parent / "fixtures" / "sagulpa_pagina_oferta.html"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path

@pytest.fixture
def sagulpa_detail_2_html_path() -> Path:
    """Fixture that returns the path to the offline Sagulpa detail page 2 HTML fixture."""
    path = Path(__file__).parent / "fixtures" / "sagulpa_pagina_oferta_2.html"
    if not path.exists():
        pytest.fail(f"Fixture not found at {path}")
    return path


def test_sagulpa_parser_list_extraction(sagulpa_list_html_path):
    """
    TDD Test 1: Verifies that the SagulpaParser correctly parses the list HTML,
    resolving relative links and extracting only active (non-closed) job openings.
    """
    if SagulpaParser is None:
        pytest.fail("SagulpaParser is not implemented yet (TDD Red Phase)")

    parser = SagulpaParser()
    with open(sagulpa_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    # Verify parser list parsing interface
    active_jobs = parser.parse_list(list_html)

    # In our sagulpa_ofertas_empleo.html fixture:
    # Total jobs listed: 30
    # Active jobs expected: exactly 3 (new processes added to fixture)
    # The others are closed or suspended (e.g. Proceso cerrado, Cerrado el plazo..., Proceso suspendido)
    assert len(active_jobs) == 3

    job = active_jobs[2]
    assert job["title"] == "BOLSA DE EMPLEO DE OPERARI@ DE BICICLETAS"
    assert job["url"] == "https://www.sagulpa.com/ofertas-empleo/bolsa-de-empleo-de-operari%40-de-bicicletas_6"
    assert isinstance(job["date"], datetime.date)
    assert job["date"] == datetime.date(2019, 5, 6) # From "06/05/2019"


def test_sagulpa_parser_detail_parsing(sagulpa_detail_html_path):
    """
    TDD Test 2: Verifies that the SagulpaParser correctly extracts the full description
    text from the detail page and validates that the KeywordFilter matches IT criteria.
    """
    if SagulpaParser is None:
        pytest.fail("SagulpaParser is not implemented yet (TDD Red Phase)")

    parser = SagulpaParser()
    with open(sagulpa_detail_html_path, "r", encoding="utf-8") as f:
        detail_html = f.read()

    description = parser.parse_detail(detail_html)

    # Verify basic text extraction
    assert "Técnico/a Especialista en Gestión de Proyectos Oficina Técnica" in description
    assert "Ingeniería Informática" in description
    assert "contratación" in description or "selección" in description

    # Verify standard KeywordFilter integration
    page = BOPage(
        page_number=1,
        text=description,
        section="Ofertas de Empleo",
        detected_organism="SAGULPA",
        source="SAGULPA",
        url="https://www.sagulpa.com/ofertas-empleo/test"
    )

    kf = KeywordFilter()
    matches = kf.search_page(page)
    
    # Verify that this high-value IT opportunity is successfully matched
    assert len(matches) == 1
    assert matches[0].organism == "SAGULPA"
    assert any("telecomunic" in k or "inform" in k for k in matches[0].matched_keywords)



def test_sagulpa_fetcher_list_and_detail_mock(sagulpa_list_html_path, sagulpa_detail_html_path):
    """
    TDD Test 3: Verifies the entire Sagulpa scraping flow (Two-Tier concurrent details deep scan)
    using a mock fetcher injected into SagulpaParser.
    """
    if SagulpaFetcher is None or SagulpaParser is None:
        pytest.fail("SagulpaFetcher or SagulpaParser is not implemented yet (TDD Red Phase)")

    with open(sagulpa_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    with open(sagulpa_detail_html_path, "r", encoding="utf-8") as f:
        detail_html = f.read()

    class MockSagulpaFetcher(BaseFetcher):
        def __init__(self):
            self.detail_calls = []

        def fetch(self, target_date):
            # BaseFetcher compatibility: return list HTML wrapped in BytesIO
            return io.BytesIO(list_html.encode("utf-8"))

        def fetch_list(self) -> str:
            return list_html

        def fetch_detail(self, url: str) -> str:
            self.detail_calls.append(url)
            # Return our high-value IT detail page
            return detail_html

    fetcher = MockSagulpaFetcher()
    parser = SagulpaParser(fetcher=fetcher)

    # In online mode (fetcher present), parsing the list stream runs the Two-Tier check
    pages = parser.parse(io.BytesIO(list_html.encode("utf-8")))

    # Verify that we fetched the detail page for the active jobs
    assert len(fetcher.detail_calls) == 3
    assert any("bolsa-de-empleo-de-operari" in call for call in fetcher.detail_calls)
 
    # Verify that a BOPage was generated containing the detail page text
    assert len(pages) == 3
    bo_page = pages[2]
    assert bo_page.page_number == 3
    assert bo_page.source == "SAGULPA"
    assert bo_page.detected_organism == "SAGULPA"
    assert bo_page.section == "Ofertas de Empleo"
    assert "Técnico/a Especialista" in bo_page.text

def test_sagulpa_data_ai_job_detection(sagulpa_list_html_path, sagulpa_detail_2_html_path):
    """
    Verifies that the parser extracts and filters data/AI jobs based on closing date boundary
    and that KeywordFilter successfully matches it as a candidate.
    """
    with open(sagulpa_list_html_path, "r", encoding="utf-8") as f:
        list_html = f.read()

    with open(sagulpa_detail_2_html_path, "r", encoding="utf-8") as f:
        detail_html = f.read()

    class MockDataAIFetcher(BaseFetcher):
        def __init__(self):
            self.detail_calls = []

        def fetch(self, target_date):
            return io.BytesIO(list_html.encode("utf-8"))

        def fetch_list(self) -> str:
            return list_html

        def fetch_detail(self, url: str) -> str:
            self.detail_calls.append(url)
            return detail_html

    fetcher = MockDataAIFetcher()
    parser = SagulpaParser(fetcher=fetcher)

    # The deadline for "Especialista en Ingeniería de Datos..." is 13/07/2026.
    # Set the target_date (current execution date) to 08/07/2026, which is before the deadline.
    target_date = datetime.date(2026, 7, 8)
    pages = parser.parse(io.BytesIO(list_html.encode("utf-8")), target_date=target_date)

    # Since the execution date is 08/07/2026:
    # 1. "Especialista en Ingeniería de Datos..." (deadline 13/07/2026) -> 2026-07-08 <= 2026-07-13: YES, active.
    # 2. "Operario/a de Movilidad..." (deadline 28/06/2026) -> 2026-07-08 <= 2026-06-28: NO, filtered out.
    # 3. "BOLSA DE EMPLEO DE OPERARI@..." (deadline 13/05/2019) -> 2026-07-08 <= 2019-05-13: NO, filtered out.
    # So we expect exactly 1 page to be returned.
    assert len(pages) == 1
    assert pages[0].source == "SAGULPA"
    assert "Especialista en Ingeniería de Datos e Inteligencia Artificial" in pages[0].text

    # Verify that KeywordFilter successfully detects this page as an IT job opportunity
    kf = KeywordFilter()
    matches = kf.search_page(pages[0])
    assert len(matches) == 1
    assert matches[0].organism == "SAGULPA"
    assert any("inteligencia" in k or "ingenier" in k for k in matches[0].matched_keywords)
