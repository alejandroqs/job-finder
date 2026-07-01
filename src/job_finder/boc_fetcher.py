import io
import datetime
import email.utils
import xml.etree.ElementTree as ET
import requests
from datetime import date
from job_finder.interfaces import BaseFetcher

class BOCFetchError(Exception):
    """Base exception for BOC fetching errors."""
    pass

class BOCFetcher(BaseFetcher):
    """Downloads and merges RSS feeds from the Boletín Oficial de Canarias (BOC)."""

    FEEDS = {
        "II.B": "https://www.gobiernodecanarias.org/boc/feeds/capitulo/autoridades_personal_oposiciones.rss",
        "III": "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otras_resoluciones.rss",
        "V": "https://www.gobiernodecanarias.org/boc/feeds/capitulo/otros_anuncios.rss",
    }

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/xml,text/xml,application/rss+xml,*/*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

    def fetch(self, target_date: date) -> io.BytesIO:
        """
        Downloads and merges the BOC RSS feeds for a specific date.
        Filters feed items by the target_date and combines them into a single XML structure.

        Args:
            target_date: The date to filter the RSS feed items by.

        Returns:
            A byte stream (BytesIO) containing the merged RSS XML.

        Raises:
            BOCFetchError: If any error occurs during the fetching or parsing of the feeds.
        """
        merged_root = ET.Element("rss", version="2.0")
        channel = ET.SubElement(merged_root, "channel")
        
        ET.SubElement(channel, "title").text = "Merged BOC Feeds"
        ET.SubElement(channel, "link").text = "https://www.gobiernodecanarias.org/boc/feeds/"
        ET.SubElement(channel, "description").text = f"Combined BOC RSS feeds filtered for {target_date.isoformat()}"
        ET.SubElement(channel, "pubDate").text = email.utils.formatdate(usegmt=True)

        items_found = 0

        for section_name, feed_url in self.FEEDS.items():
            try:
                response = requests.get(feed_url, headers=self.headers, timeout=self.timeout)
                response.raise_for_status()
            except requests.RequestException as e:
                raise BOCFetchError(f"Failed to fetch feed '{section_name}' from {feed_url}: {e}") from e

            try:
                import re
                xml_str = response.content.decode("utf-8", errors="replace")
                # Sanitise raw ampersands (government feeds often contain unescaped '&')
                xml_str = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#[xX][a-fA-F0-9]+);)", "&amp;", xml_str)
                root = ET.fromstring(xml_str.encode("utf-8"))
            except ET.ParseError as e:
                raise BOCFetchError(f"Failed to parse XML from feed '{section_name}': {e}") from e

            # Extract items matching target_date
            for item in root.findall(".//item"):
                pub_date_elem = item.find("pubDate")
                if pub_date_elem is None or not pub_date_elem.text:
                    continue

                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_elem.text)
                    item_date = dt.date()
                except (ValueError, TypeError):
                    # Robust fallback or skip item if unparseable
                    continue

                if item_date == target_date:
                    # Deep copy the item to append to merged root
                    # Note: ET doesn't have direct copy, but we can serialize and parse, or construct a new element.
                    # Creating a copy of the XML element by serialization/re-parsing is simple and robust.
                    item_copy = ET.fromstring(ET.tostring(item, encoding="utf-8"))
                    channel.append(item_copy)
                    items_found += 1

        # Serialize merged XML to bytes
        output_stream = io.BytesIO()
        tree = ET.ElementTree(merged_root)
        tree.write(output_stream, encoding="utf-8", xml_declaration=True)
        output_stream.seek(0)

        return output_stream

    def fetch_latest(self) -> tuple[io.BytesIO, date]:
        """
        Scans all RSS feeds, finds the most recent publication date among all items,
        and fetches/filters for that date.

        Returns:
            A tuple of (BytesIO stream of the merged XML, date of the latest items).
        """
        latest_date = None
        for section_name, feed_url in self.FEEDS.items():
            try:
                response = requests.get(feed_url, headers=self.headers, timeout=self.timeout)
                if response.status_code == 200:
                    import re
                    xml_str = response.content.decode("utf-8", errors="replace")
                    xml_str = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#[xX][a-fA-F0-9]+);)", "&amp;", xml_str)
                    root = ET.fromstring(xml_str.encode("utf-8"))
                    for item in root.findall(".//item"):
                        pub_date_elem = item.find("pubDate")
                        if pub_date_elem is not None and pub_date_elem.text:
                            try:
                                dt = email.utils.parsedate_to_datetime(pub_date_elem.text)
                                item_date = dt.date()
                                if latest_date is None or item_date > latest_date:
                                    latest_date = item_date
                            except (ValueError, TypeError):
                                continue
            except Exception:
                continue

        if latest_date is None:
            latest_date = date.today()

        return self.fetch(latest_date), latest_date
