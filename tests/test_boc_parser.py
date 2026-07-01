import io
import datetime
import pytest
import requests

from job_finder.boc_fetcher import BOCFetcher, BOCFetchError
from job_finder.boc_parser import BOCParser
from job_finder.keyword_filter import KeywordFilter
from job_finder.interfaces import BOPage

# =====================================================================
# BOC Parser Integration Tests
# =====================================================================

def test_boc_parser_section_filtering(sample_xml_stream):
    """
    Verifies that the BOCParser correctly parses RSS XML and filters items
    based on their h5 section/subsection hierarchy.
    """
    parser = BOCParser()
    parsed_pages = parser.parse(sample_xml_stream)

    # In our boc_sample.xml:
    # 7 items total.
    # Item 1: II. Oposiciones y concursos -> Target (Pass)
    # Item 2: III. Otras Resoluciones -> Target (Pass)
    # Item 3: V. Administración Local -> Target (Pass)
    # Item 4: II. Nombramientos -> Non-target (Skip)
    # Item 5: V. Otros anuncios -> Non-target (Skip)
    # Item 6: V. Administración Local -> Target (Pass)
    # Item 7: V. Administración Local -> Target (Pass)
    # Total targets expected: 5
    assert len(parsed_pages) == 5

    # Check first item details
    first_item = parsed_pages[0]
    assert first_item.page_number == 1
    assert "Técnico de Sistemas Microinformáticos" in first_item.text
    assert first_item.section == "II. Autoridades y Personal -> Oposiciones y concursos"
    assert first_item.detected_organism == "Consejería de Presidencia"
    assert first_item.source == "BOC"
    assert first_item.url == "https://www.gobiernodecanarias.org/boc/2026/097/001.html"

    # Check last item details
    last_item = parsed_pages[4]
    assert last_item.page_number == 5
    assert "Ayuntamiento de Gáldar" in last_item.detected_organism
    assert last_item.section == "V. Anuncios -> Administración Local"


def test_boc_keyword_and_noise_filtering(sample_xml_stream):
    """
    Verifies that the KeywordFilter correctly isolates the 3 IT job openings
    from the parsed BOC pages, filtering out unrelated jobs and noise.
    """
    parser = BOCParser()
    parsed_pages = parser.parse(sample_xml_stream)

    kf = KeywordFilter()
    announcements = []
    for page in parsed_pages:
        announcements.extend(kf.search_page(page))

    # Expecting exactly 3 matches:
    # Match 1: Técnico de Sistemas (IT) + plaza (Anchor)
    # Match 2: ULPGC Ingeniera de Software (IT) + convocatoria (Anchor)
    # Match 3: Tenerife Programador (IT) + bases (Anchor)
    # Filtered:
    # - Geógrafo (No IT keyword)
    # - Ayuntamiento de Gáldar (IT keyword but NO employment/contest anchor)
    assert len(announcements) == 3

    organisms = [ann.organism for ann in announcements]
    assert "Consejería de Presidencia" in organisms
    assert "Universidad de Las Palmas de Gran Canaria" in organisms
    assert "Cabildo Insular de Tenerife" in organisms
    assert "Ayuntamiento de Arrecife" not in organisms
    assert "Ayuntamiento de Gáldar" not in organisms

    # Check fields are populated
    for ann in announcements:
        assert ann.source == "BOC"
        assert ann.url.startswith("https://")
        assert ann.page_number > 0
        assert len(ann.matched_keywords) > 0


# =====================================================================
# BOC Fetcher URL Tests
# =====================================================================

def test_boc_fetcher_urls():
    """Verifies that the BOCFetcher has configured correct feed URLs."""
    fetcher = BOCFetcher()
    assert len(fetcher.FEEDS) == 3
    assert "https://www.gobiernodecanarias.org/boc/feeds/capitulo/autoridades_personal_oposiciones.rss" in fetcher.FEEDS.values()
    assert "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otras_resoluciones.rss" in fetcher.FEEDS.values()
    assert "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otros_anuncios.rss" in fetcher.FEEDS.values()


# =====================================================================
# BOC Fetcher Mock Tests
# =====================================================================

def test_boc_fetcher_date_filtering(monkeypatch):
    """Verifies that BOCFetcher downloads and filters RSS items for the requested date."""
    fetcher = BOCFetcher()

    class MockResponse:
        def __init__(self, content):
            self.content = content
            self.status_code = 200
            
        def raise_for_status(self):
            pass

    # A simple mock RSS containing two items on different dates
    mock_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>IT opening 1</title>
          <pubDate>Thu, 21 May 2026 00:00:00 +0200</pubDate>
        </item>
        <item>
          <title>IT opening 2</title>
          <pubDate>Fri, 22 May 2026 00:00:00 +0200</pubDate>
        </item>
      </channel>
    </rss>
    """

    def mock_get(url, *args, **kwargs):
        return MockResponse(mock_xml)

    monkeypatch.setattr(requests, "get", mock_get)

    # 1. Fetching for 2026-05-21 should return only 1 item per feed (total 3 items)
    result_stream_21 = fetcher.fetch(datetime.date(2026, 5, 21))
    parser = BOCParser()
    
    # We can parse the merged feed to count items
    import xml.etree.ElementTree as ET
    root_21 = ET.fromstring(result_stream_21.getvalue())
    items_21 = root_21.findall(".//item")
    assert len(items_21) == 3
    assert items_21[0].find("title").text == "IT opening 1"

    # 2. Fetching for 2026-05-22 should return only 1 item per feed (total 3 items)
    result_stream_22 = fetcher.fetch(datetime.date(2026, 5, 22))
    root_22 = ET.fromstring(result_stream_22.getvalue())
    items_22 = root_22.findall(".//item")
    assert len(items_22) == 3
    assert items_22[0].find("title").text == "IT opening 2"

    # 3. Fetching for 2026-05-23 should return 0 items
    result_stream_23 = fetcher.fetch(datetime.date(2026, 5, 23))
    root_23 = ET.fromstring(result_stream_23.getvalue())
    items_23 = root_23.findall(".//item")
    assert len(items_23) == 0


def test_boc_fetcher_fetch_latest(monkeypatch):
    """Verifies that fetch_latest correctly identifies the most recent date available in feeds."""
    fetcher = BOCFetcher()

    class MockResponse:
        def __init__(self, content):
            self.content = content
            self.status_code = 200
            
        def raise_for_status(self):
            pass

    # A mock RSS with mixed publication dates
    mock_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Old Item</title>
          <pubDate>Mon, 18 May 2026 00:00:00 +0200</pubDate>
        </item>
        <item>
          <title>Newest Item</title>
          <pubDate>Wed, 20 May 2026 00:00:00 +0200</pubDate>
        </item>
        <item>
          <title>Middle Item</title>
          <pubDate>Tue, 19 May 2026 00:00:00 +0200</pubDate>
        </item>
      </channel>
    </rss>
    """

    def mock_get(url, *args, **kwargs):
        return MockResponse(mock_xml)

    monkeypatch.setattr(requests, "get", mock_get)

    # fetch_latest should scan all and discover 2026-05-20 as the latest date, 
    # then return only items from that date (1 item per feed, total 3 items)
    pdf_stream, latest_date = fetcher.fetch_latest()
    assert latest_date == datetime.date(2026, 5, 20)

    import xml.etree.ElementTree as ET
    root = ET.fromstring(pdf_stream.getvalue())
    items = root.findall(".//item")
    assert len(items) == 3
    assert items[0].find("title").text == "Newest Item"
