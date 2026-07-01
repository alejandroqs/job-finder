import io
import datetime
from pathlib import Path
import pytest
import requests

from job_finder.boe_fetcher import BOEFetcher, BOENotPublishedError, BOEFetchError
from job_finder.boe_parser import BOEParser
from job_finder.keyword_filter import KeywordFilter
from job_finder.interfaces import BaseFetcher, BOPage

# =====================================================================
# BOE Parser Integration Tests (Offline Mode)
# =====================================================================

def test_boe_parser_section_filtering(sample_xml_boe_stream):
    """
    Verifies that the BOEParser correctly parses BOE Open Data API XML and
    extracts only Section II.B items (and parses their department/epigraph structure).
    """
    parser = BOEParser()
    parsed_pages = parser.parse(sample_xml_boe_stream)

    # In our boe_sample.xml:
    # Section II.B has:
    #   - 2 items under PJC Ministerio (IT match, and No-IT match)
    #   - 1 item under ADMINISTRACIÓN LOCAL (IT match)
    #   - 2 items under UNIVERSIDAD (IT match, and IT-word-no-anchor)
    # Section III has:
    #   - 1 item (from Section III)
    # Total targets in Section II.B expected: 5
    assert len(parsed_pages) == 5

    # Check first item details (Ministerio, Técnico de Informática)
    first_item = parsed_pages[0]
    assert first_item.page_number == 1
    assert "Técnico de Informática" in first_item.text
    assert "[BOE-A-2026-10901]" in first_item.text
    assert first_item.section == "II.B. Oposiciones y concursos -> Personal funcionario. Oposiciones"
    assert first_item.detected_organism == "MINISTERIO DE LA PRESIDENCIA, JUSTICIA Y RELACIONES CON LAS CORTES"
    assert first_item.source == "BOE"
    assert first_item.url == "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-10901"

    # Check last item details (Universidad, Suministro de software)
    last_item = parsed_pages[4]
    assert last_item.page_number == 5
    assert "[BOE-A-2026-10905]" in last_item.text
    assert last_item.detected_organism == "UNIVERSIDAD DE LAS PALMAS DE GRAN CANARIA"
    assert last_item.section == "II.B. Oposiciones y concursos -> Personal de administración y servicios"
    assert last_item.url == "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-10905"


def test_boe_parser_empty_on_invalid_xml():
    """Verifies that the BOEParser returns an empty list if given invalid/malformed XML."""
    parser = BOEParser()
    assert parser.parse(io.BytesIO(b"Not XML")) == []
    assert parser.parse(io.BytesIO(b"<response><status><code>404</code></status></response>")) == []


def test_boe_keyword_and_noise_filtering(sample_xml_boe_stream):
    """
    Verifies that the KeywordFilter correctly isolates target IT job openings from
    the parsed BOE pages, filtering out unrelated jobs and non-employment noise.
    """
    parser = BOEParser()
    parsed_pages = parser.parse(sample_xml_boe_stream)

    kf = KeywordFilter()
    announcements = []
    for page in parsed_pages:
        announcements.extend(kf.search_page(page))

    # Expecting exactly 3 matches:
    # Match 1: Técnico de Informática (IT) + convocatoria (Anchor)
    # Match 2: Programador de Sistemas de Redes (IT) + bases (Anchor)
    # Match 3: Ingeniero Informático de Sistemas (IT) + bolsa de empleo (Anchor)
    assert len(announcements) == 3

    organisms = [ann.organism for ann in announcements]
    assert "MINISTERIO DE LA PRESIDENCIA, JUSTICIA Y RELACIONES CON LAS CORTES" in organisms
    assert "ADMINISTRACIÓN LOCAL" in organisms
    assert "UNIVERSIDAD DE LAS PALMAS DE GRAN CANARIA" in organisms


# =====================================================================
# Two-Tier Gatekeeper Heuristics Tests
# =====================================================================

def test_boe_parser_negative_filtering_heuristics():
    """Verifies that the gatekeeper negative filters reject entries immediately without downloading."""
    xml_data = """<?xml version="1.0" encoding="utf-8"?>
    <response>
      <data>
        <sumario>
          <diario numero="124">
            <seccion codigo="2B">
              <departamento nombre="TEST DEPARTAMENTO">
                <!-- Should be rejected by negative filter -->
                <item>
                  <identificador>BOE-A-2026-99991</identificador>
                  <titulo>Convocatoria para proveer plazas de Policía Local en Teruel.</titulo>
                  <url_pdf>https://www.boe.es/boe/dias/2026/05/21/pdfs/BOE-A-2026-99991.pdf</url_pdf>
                </item>
                <!-- Should be rejected by negative filter -->
                <item>
                  <identificador>BOE-A-2026-99992</identificador>
                  <titulo>Proceso selectivo para Cuerpo de Letrados de la Administración.</titulo>
                  <url_pdf>https://www.boe.es/boe/dias/2026/05/21/pdfs/BOE-A-2026-99992.pdf</url_pdf>
                </item>
                <!-- Should be accepted because it doesn't match negative filter -->
                <item>
                  <identificador>BOE-A-2026-99993</identificador>
                  <titulo>Bases para plaza de Administrador de Sistemas.</titulo>
                  <url_pdf>https://www.boe.es/boe/dias/2026/05/21/pdfs/BOE-A-2026-99993.pdf</url_pdf>
                </item>
              </departamento>
            </seccion>
          </diario>
        </sumario>
      </data>
    </response>
    """

    class MockTrackerFetcher(BaseFetcher):
        def __init__(self):
            self.download_calls = []
        def fetch(self, target_date):
            return io.BytesIO(b"")
        def fetch_pdf(self, pdf_url):
            self.download_calls.append(pdf_url)
            return io.BytesIO(b"") # triggers fallback to title

    fetcher = MockTrackerFetcher()
    parser = BOEParser(pdf_fetcher=fetcher)

    parsed = parser.parse(io.BytesIO(xml_data.encode("utf-8")))

    # Verify that police/letrados did not download and only BOE-A-2026-99993 downloaded
    assert len(fetcher.download_calls) == 1
    assert "BOE-A-2026-99993.pdf" in fetcher.download_calls[0]
    # We still have a fallback page returned for BOE-A-2026-99993
    assert len(parsed) == 1
    assert "Administrador de Sistemas" in parsed[0].text


def test_boe_parser_pdf_deep_scan_integration():
    """
    Verifies that the Two-Tier parser correctly downloads and deep-scans a PDF,
    extracting its text pages and finding matches inside it.
    """
    xml_data = """<?xml version="1.0" encoding="utf-8"?>
    <response>
      <data>
        <sumario>
          <diario numero="124">
            <seccion codigo="2B">
              <departamento nombre="AYUNTAMIENTO DE LAS PALMAS DE GRAN CANARIA">
                <item>
                  <identificador>BOE-A-2026-10903</identificador>
                  <titulo>Generic Container Title - OEP Procesos Selectivos</titulo>
                  <url_pdf>https://www.boe.es/boe/dias/2026/05/21/pdfs/BOE-A-2026-10903.pdf</url_pdf>
                  <url_html>https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-10903</url_html>
                </item>
              </departamento>
            </seccion>
          </diario>
        </sumario>
      </data>
    </response>
    """

    pdf_fixture_path = Path(__file__).parent / "fixtures" / "boe_sample.pdf"
    assert pdf_fixture_path.exists()

    with open(pdf_fixture_path, "rb") as f:
        pdf_bytes = f.read()

    class MockPDFStreamFetcher(BaseFetcher):
        def fetch(self, target_date):
            return io.BytesIO(b"")
        def fetch_pdf(self, pdf_url):
            return io.BytesIO(pdf_bytes)

    fetcher = MockPDFStreamFetcher()
    parser = BOEParser(pdf_fetcher=fetcher)

    parsed_pages = parser.parse(io.BytesIO(xml_data.encode("utf-8")))

    # Verify that multiple pages from the PDF were processed
    assert len(parsed_pages) > 0

    kf = KeywordFilter()
    announcements = []
    for page in parsed_pages:
        announcements.extend(kf.search_page(page))

    # Verify that our IT keywords matched inside the parsed PDF page content
    assert len(announcements) > 0
    # Verify the details match
    ann = announcements[0]
    assert ann.organism == "AYUNTAMIENTO DE LAS PALMAS DE GRAN CANARIA"
    assert ann.source == "BOE"
    assert len(ann.matched_keywords) > 0



# =====================================================================
# BOE Fetcher Tests
# =====================================================================

def test_boe_fetcher_api_url():
    """Verifies that the BOEFetcher contains the correct Open Data API URL template."""
    fetcher = BOEFetcher()
    assert fetcher.API_URL_TEMPLATE == "https://www.boe.es/datosabiertos/api/boe/sumario/{date_str}"


def test_boe_fetcher_fetch_monkeypatch(monkeypatch, sample_xml_boe_path):
    """Verifies that BOEFetcher downloads and returns the XML contents correctly on HTTP 200."""
    fetcher = BOEFetcher()

    class MockResponse:
        def __init__(self, content):
            self.content = content
            self.status_code = 200
            
        def raise_for_status(self):
            pass

    with open(sample_xml_boe_path, "rb") as f:
        mock_xml = f.read()

    def mock_get(url, *args, **kwargs):
        assert "Accept" in kwargs.get("headers", {})
        assert kwargs["headers"]["Accept"] == "application/xml"
        return MockResponse(mock_xml)

    monkeypatch.setattr(requests, "get", mock_get)

    result_stream = fetcher.fetch(datetime.date(2026, 5, 21))
    assert result_stream is not None
    assert b"<seccion codigo=\"2B\"" in result_stream.getvalue()


def test_boe_fetcher_404_raises(monkeypatch):
    """Verifies that BOEFetcher raises BOENotPublishedError on HTTP 404."""
    fetcher = BOEFetcher()

    class MockResponse:
        def __init__(self):
            self.status_code = 404
            
        def raise_for_status(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *a, **k: MockResponse())

    with pytest.raises(BOENotPublishedError):
        fetcher.fetch(datetime.date(2026, 5, 17))


def test_boe_fetcher_fetch_latest_fallback_probing(monkeypatch, sample_xml_boe_path):
    """
    Verifies that fetch_latest probes backwards day-by-day correctly,
    handling weekend/holiday gaps until it successfully fetches a bulletin.
    """
    fetcher = BOEFetcher()

    calls = []

    class MockResponse:
        def __init__(self, status_code, content=b""):
            self.status_code = status_code
            self.content = content
            
        def raise_for_status(self):
            if self.status_code != 200:
                raise requests.HTTPError("Error")

    with open(sample_xml_boe_path, "rb") as f:
        xml_content = f.read()

    def mock_get(url, *args, **kwargs):
        calls.append(url)
        if len(calls) < 3:
            return MockResponse(404)
        else:
            return MockResponse(200, xml_content)

    monkeypatch.setattr(requests, "get", mock_get)

    class MockDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 5, 24) # Sunday

    monkeypatch.setattr(datetime, "date", MockDate)
    monkeypatch.setattr("job_finder.boe_fetcher.date", MockDate)

    stream, resolved_date = fetcher.fetch_latest()

    assert resolved_date == datetime.date(2026, 5, 22) # Friday
    assert len(calls) == 3
    assert "20260524" in calls[0]
    assert "20260523" in calls[1]
    assert "20260522" in calls[2]
    assert b"<seccion codigo=\"2B\"" in stream.getvalue()
