import datetime
import json
import time
from pathlib import Path
import pytest
from job_finder.interfaces import BOPage, BaseEUFetcher
from job_finder.epso_parser import EPSOParser
from job_finder.eures_parser import EURESParser
from job_finder.eulisa_parser import EULISAParser
from job_finder.keyword_filter import KeywordFilter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# =====================================================================
# Fixtures Loading Mock Data
# =====================================================================

@pytest.fixture
def epso_csv_content() -> bytes:
    csv_path = FIXTURES_DIR / "epso_sample.csv"
    with open(csv_path, "rb") as f:
        return f.read()

@pytest.fixture
def eures_json_content() -> str:
    json_path = FIXTURES_DIR / "eures_xhr_response.json"
    with open(json_path, "r", encoding="utf-8") as f:
        return f.read()

@pytest.fixture
def eulisa_html_content() -> str:
    html_path = FIXTURES_DIR / "eulisa_careers.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

from job_finder.epso_fetcher import EPSOFetcher
import httpx

# =====================================================================
# EPSO Source Tests
# =====================================================================

def test_epso_fetcher_distributions_parsing(monkeypatch):
    json_path = FIXTURES_DIR / "epso_ckan_response.json"
    with open(json_path, "r", encoding="utf-8") as f:
        mock_api_data = json.load(f)
        
    class MockResponse:
        def __init__(self, json_data, content=b"csv-data"):
            self._json_data = json_data
            self.content = content
            self.status_code = 200
            
        def json(self):
            return self._json_data
            
        def raise_for_status(self):
            pass
            
    def mock_get(url, *args, **kwargs):
        if "hub/repo/datasets" in url:
            return MockResponse(mock_api_data)
        elif "csv-opportunities" in url:
            return MockResponse(None, content=b"csv-header,csv-row-data")
        return MockResponse(None)
        
    monkeypatch.setattr(httpx, "get", mock_get)
    
    fetcher = EPSOFetcher()
    csv_bytes = fetcher.fetch_raw()
    assert csv_bytes == b"csv-header,csv-row-data"

def test_epso_parser_extraction(epso_csv_content):
    parser = EPSOParser()
    pages = parser.parse_raw(epso_csv_content)
    
    # Assert 3 rows parsed from mock CSV
    assert len(pages) == 3
    
    # Assert correct column normalization mapping
    assert pages[0].detected_organism == "European Commission"
    assert pages[0].source == "EPSO"
    assert "Applications Architect" in pages[0].text
    
    assert pages[1].detected_organism == "European Parliament"
    assert "Administrative Assistant" in pages[1].text
    
    assert pages[2].detected_organism == "eu-LISA"
    assert "Cybersecurity Specialist" in pages[2].text

def test_epso_parser_deadline_filtering(epso_csv_content):
    parser = EPSOParser()
    
    # Date 2026-08-01:
    # Row 1 (2026-12-31) -> Active (Keep)
    # Row 2 (2026-06-30) -> Expired (Skip)
    # Row 3 (2026-09-15) -> Active (Keep)
    target_date = datetime.date(2026, 8, 1)
    pages = parser.parse_raw(epso_csv_content, target_date=target_date)
    assert len(pages) == 2
    assert not any("European Parliament" in p.detected_organism for p in pages)

# =====================================================================
# EURES Source Tests
# =====================================================================

def test_eures_parser_extraction(eures_json_content):
    parser = EURESParser()
    pages = parser.parse_raw(eures_json_content)
    
    # Assert 2 rows parsed from mock JSON
    assert len(pages) == 2
    
    # Assert correct mapping and BeautifulSoup HTML stripping
    assert pages[0].detected_organism == "EURES Recruiting Agency"
    assert pages[0].source == "EURES"
    assert pages[0].url == "https://europa.eu/eures/apply-1"
    assert "Software Developer" in pages[0].text
    
    assert pages[1].detected_organism == "Brussels Finance Agency"
    assert "General Office Administrator" in pages[1].text

# =====================================================================
# eu-LISA Source Tests
# =====================================================================

def test_eulisa_parser_extraction(eulisa_html_content):
    parser = EULISAParser()
    pages = parser.parse_raw(eulisa_html_content)
    
    # Assert 4 rows/links parsed from mock HTML table and list block
    assert len(pages) == 4
    
    # Assert correct organisms and resolved absolute URLs
    assert pages[0].detected_organism == "eu-LISA"
    assert pages[0].source == "EULISA"
    assert pages[0].url == "https://www.eulisa.europa.eu/vacancies/ICT-Expert-AD8.html"
    assert "ICT Expert" in pages[0].text
    
    assert pages[1].detected_organism == "eu-LISA"
    assert pages[1].url == "https://www.eulisa.europa.eu/vacancies/Legal-Advisor-FGIV.html"

    assert pages[2].detected_organism == "eu-LISA"
    assert pages[2].url == "https://recruitment.eulisa.europa.eu/jobs/Solution-Architect-AD9"
    assert "Solution Architect" in pages[2].text

    assert pages[3].detected_organism == "eu-LISA"
    assert pages[3].url == "https://www.eulisa.europa.eu/jobs/General-Admin-Assistant"

def test_eulisa_parser_deadline_filtering(eulisa_html_content):
    parser = EULISAParser()
    
    # Date 2026-08-01:
    # Row 1 (15/09/2026) -> Active (Keep)
    # Row 2 (30/06/2026) -> Expired (Skip)
    # Row 3 (20/10/2026) -> Active (Keep)
    # Row 4 (15/08/2026) -> Active (Keep)
    target_date = datetime.date(2026, 8, 1)
    pages = parser.parse_raw(eulisa_html_content, target_date=target_date)
    assert len(pages) == 3
    assert any("ICT Expert" in p.text for p in pages)
    assert any("Solution Architect" in p.text for p in pages)

# =====================================================================
# Keyword & ESCO Taxonomy Filter Integration Tests
# =====================================================================

def test_eu_keyword_filter_matching(epso_csv_content, eures_json_content, eulisa_html_content):
    kf = KeywordFilter()
    
    # 1. Test EPSO parsed pages through KeywordFilter
    epso_parser = EPSOParser()
    epso_pages = epso_parser.parse_raw(epso_csv_content)
    
    epso_it_jobs = []
    for page in epso_pages:
        epso_it_jobs.extend(kf.search_page(page))
        
    # Assert: Only Row 1 (Applications Architect) and Row 3 (Cybersecurity Specialist) match.
    # Row 2 (Administrative Assistant) must be discarded.
    assert len(epso_it_jobs) == 2
    assert epso_it_jobs[0].organism == "European Commission"
    assert any("Applications Architect" in kw for kw in epso_it_jobs[0].matched_keywords)
    assert epso_it_jobs[1].organism == "eu-LISA"
    assert any("Cybersecurity" in kw for kw in epso_it_jobs[1].matched_keywords)

    # 2. Test EURES parsed pages
    eures_parser = EURESParser()
    eures_pages = eures_parser.parse_raw(eures_json_content)
    
    eures_it_jobs = []
    for page in eures_pages:
        eures_it_jobs.extend(kf.search_page(page))
        
    # Assert: Only Row 1 (Software Developer) matches. Row 2 (General Office Administrator) discarded.
    assert len(eures_it_jobs) == 1
    assert eures_it_jobs[0].organism == "EURES Recruiting Agency"
    assert any("Software Developer" in kw for kw in eures_it_jobs[0].matched_keywords)

    # 3. Test eu-LISA parsed pages
    eulisa_parser = EULISAParser()
    eulisa_pages = eulisa_parser.parse_raw(eulisa_html_content)
    
    eulisa_it_jobs = []
    for page in eulisa_pages:
        eulisa_it_jobs.extend(kf.search_page(page))
        
    # Assert: Only Row 1 (ICT Expert) and Row 3 (Solution Architect) match. Rows 2 & 4 discarded.
    assert len(eulisa_it_jobs) == 2
    assert eulisa_it_jobs[0].organism == "eu-LISA"
    assert any("ICT Expert" in kw for kw in eulisa_it_jobs[0].matched_keywords)
    assert eulisa_it_jobs[1].organism == "eu-LISA"
    assert any("Solution Architect" in kw for kw in eulisa_it_jobs[1].matched_keywords)

def test_eu_keyword_word_boundaries():
    kf = KeywordFilter()
    
    # DBA is an EU ESCO keyword.
    # Matches "DBA" as a standalone word.
    page_match = BOPage(
        page_number=1,
        text="Vacancy for an expert Database Administrator or DBA at the agency.",
        source="EPSO"
    )
    results_match = kf.search_page(page_match)
    assert len(results_match) == 1
    assert any("DBA" in kw for kw in results_match[0].matched_keywords)
    
    # Does NOT match "DBA" embedded inside other words (e.g. "handbag" or "databases")
    page_no_match = BOPage(
        page_number=2,
        text="This role involves general feedback and database operations in Brussels.",
        source="EPSO"
    )
    results_no_match = kf.search_page(page_no_match)
    assert len(results_no_match) == 0


# =====================================================================
# Gemini AI Validator Tests
# =====================================================================

from job_finder.gemini_validator import GeminiValidator
from job_finder.interfaces import ParsedAnnouncement

def test_validator_filters_non_it_jobs(monkeypatch):
    from google import genai
    
    announcements = [
        ParsedAnnouncement(organism="Org A", description="Técnico de Sistemas", page_number=1, matched_keywords=["sistemas"], url="http://a"),
        ParsedAnnouncement(organism="Org B", description="Limpieza", page_number=2, matched_keywords=["limpieza"], url="http://b"),
        ParsedAnnouncement(organism="Org C", description="Desarrollador", page_number=3, matched_keywords=["desarrollador"], url="http://c")
    ]
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            return MockResponse(
                '{"results": ['
                '  {"id": 0, "is_tech_job": true, "job_title": "Técnico de Sistemas", "organism": "Org A", "confidence": "high"},'
                '  {"id": 1, "is_tech_job": false, "job_title": null, "organism": "Org B", "confidence": "high"},'
                '  {"id": 2, "is_tech_job": true, "job_title": "Desarrollador", "organism": "Org C", "confidence": "high"}'
                ']}'
            )
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    
    validator = GeminiValidator(api_key="mock-key")
    result = validator.validate_batch(announcements)
    
    assert len(result) == 2
    assert result[0].organism == "Org A"
    assert result[1].organism == "Org C"


def test_validator_fallback_on_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    validator = GeminiValidator(api_key="")
    assert not validator.enabled
    
    announcements = [
        ParsedAnnouncement(organism="Org A", description="Técnico", page_number=1, matched_keywords=["técnico"], url="http://a")
    ]
    result = validator.validate_batch(announcements)
    assert len(result) == 1
    assert result[0].organism == "Org A"


def test_validator_fallback_on_api_error(monkeypatch):
    from google import genai
    
    class MockModels:
        def generate_content(self, model, contents, config):
            raise Exception("API Connection failure")
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    
    validator = GeminiValidator(api_key="mock-key")
    announcements = [
        ParsedAnnouncement(organism="Org A", description="Técnico", page_number=1, matched_keywords=["técnico"], url="http://a")
    ]
    result = validator.validate_batch(announcements)
    assert len(result) == 1
    assert result[0].organism == "Org A"


def test_validator_deduplication(monkeypatch):
    from google import genai
    
    announcements = [
        ParsedAnnouncement(organism="Org A", description="Sistemas Cat 1", page_number=1, matched_keywords=["sistemas"], url="http://dup"),
        ParsedAnnouncement(organism="Org A", description="Sistemas Cat 2", page_number=2, matched_keywords=["sistemas"], url="http://dup"),
        ParsedAnnouncement(organism="Org B", description="Administrativo", page_number=3, matched_keywords=["administrativo"], url="http://other")
    ]
    
    captured_calls = []
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            captured_calls.append((model, contents, config))
            return MockResponse('{"results": [{"id": 0, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}, {"id": 1, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}]}')
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    
    validator = GeminiValidator(api_key="mock-key")
    result = validator.validate_batch(announcements)
    
    assert len(captured_calls) == 1
    assert len(result) == 3


def test_validator_context_inversion(monkeypatch):
    from google import genai
    
    captured_contents = []
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            captured_contents.append(contents)
            return MockResponse('{"results": [{"id": 0, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}]}')
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    
    validator = GeminiValidator(api_key="mock-key")
    ann = ParsedAnnouncement(organism="Org A", description="This is my special posting content", page_number=1, matched_keywords=[], url="http://a")
    validator.validate_batch([ann])
    
    assert len(captured_contents) == 1
    prompt = captured_contents[0]
    
    assert "<context>" in prompt
    assert "This is my special posting content" in prompt
    assert "</context>" in prompt
    assert "<task>" in prompt
    
    context_idx = prompt.find("<context>")
    task_idx = prompt.find("<task>")
    assert context_idx != -1 and task_idx != -1
    assert context_idx < task_idx


def test_validator_prompts_loaded_from_yaml(monkeypatch):
    from google import genai
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            return MockResponse('{"results": [{"id": 0, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}]}')
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    
    validator = GeminiValidator(api_key="mock-key")
    
    assert validator.system_prompt
    assert "You are a strict classifier" in validator.system_prompt
    assert validator.user_prompt_template
    assert "<context>" in validator.user_prompt_template


def test_validator_structured_output_config(monkeypatch):
    from google import genai
    from job_finder.gemini_validator import JobOfferValidationBatch
    
    captured_configs = []
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            captured_configs.append(config)
            return MockResponse('{"results": [{"id": 0, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}]}')
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    
    validator = GeminiValidator(api_key="mock-key")
    ann = ParsedAnnouncement(organism="Org A", description="Test", page_number=1, matched_keywords=[], url="http://a")
    validator.validate_batch([ann])
    
    assert len(captured_configs) == 1
    config = captured_configs[0]
    
    assert config.response_mime_type == "application/json"
    assert config.response_schema == JobOfferValidationBatch
    assert str(config.thinking_config.thinking_level).lower().endswith("low")


def test_validator_default_true_on_parse_failure(monkeypatch):
    from google import genai
    
    class MockResponse:
        def __init__(self, text):
            self.text = text
            
    class MockModels:
        def generate_content(self, model, contents, config):
            return MockResponse('{"invalid": "json"}')
            
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    monkeypatch.setattr(time, "sleep", lambda x: None)
    
    validator = GeminiValidator(api_key="mock-key")
    ann = ParsedAnnouncement(organism="Org A", description="Test", page_number=1, matched_keywords=[], url="http://a")
    result = validator.validate_batch([ann])
    
    assert len(result) == 1


def test_validator_retry_on_429(monkeypatch):
    from google import genai
    
    sleep_calls = []
    def mock_sleep(seconds):
        sleep_calls.append(seconds)
    monkeypatch.setattr(time, "sleep", mock_sleep)
    
    post_calls = 0
    
    class MockModels:
        def generate_content(self, model, contents, config):
            nonlocal post_calls
            post_calls += 1
            if post_calls == 1:
                class MockAPIError(Exception):
                    def __init__(self):
                        self.code = 429
                        super().__init__("429 Resource Exhausted")
                raise MockAPIError()
            else:
                class MockResponse:
                    def __init__(self, text):
                        self.text = text
                return MockResponse('{"results": [{"id": 0, "is_tech_job": true, "job_title": "IT", "organism": "Org", "confidence": "high"}]}')
                
    class MockClient:
        def __init__(self, api_key):
            self.models = MockModels()
            
    monkeypatch.setattr(genai, "Client", MockClient)
    
    validator = GeminiValidator(api_key="mock-key")
    ann = ParsedAnnouncement(organism="Org A", description="Test", page_number=1, matched_keywords=[], url="http://a")
    result = validator.validate_batch([ann])
    
    assert post_calls == 2
    assert 60.0 in sleep_calls
    assert len(result) == 1



