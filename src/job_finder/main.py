import argparse
import datetime
import io
import re
import sys
import textwrap
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import List, Optional

# BOP Components
from job_finder.bop_fetcher import BOPFetcher, BOPNotPublishedError, BOPFetchError
from job_finder.bop_parser import BOPParser

# BOC Components
from job_finder.boc_fetcher import BOCFetcher, BOCFetchError
from job_finder.boc_parser import BOCParser

# BOE Components
from job_finder.boe_fetcher import BOEFetcher, BOENotPublishedError, BOEFetchError
from job_finder.boe_parser import BOEParser

# Sagulpa Components
from job_finder.sagulpa_fetcher import SagulpaFetcher
from job_finder.sagulpa_parser import SagulpaParser

# Guaguas Components
from job_finder.guaguas_fetcher import GuaguasFetcher
from job_finder.guaguas_parser import GuaguasParser

# GEURSA Components
from job_finder.geursa_fetcher import GeursaFetcher
from job_finder.geursa_parser import GeursaParser

# GSC Components
from job_finder.gsc_fetcher import GSCFetcher
from job_finder.gsc_parser import GSCParser

# Indra Group Components
from job_finder.indra_fetcher import IndraFetcher
from job_finder.indra_parser import IndraParser

# FULP Components
from job_finder.fulp_fetcher import FulpFetcher
from job_finder.fulp_parser import FulpParser

# Aena Components
from job_finder.aena_fetcher import AenaFetcher
from job_finder.aena_parser import AenaParser

# EU Components
from job_finder.epso_fetcher import EPSOFetcher
from job_finder.epso_parser import EPSOParser
from job_finder.eures_fetcher import EURESFetcher
from job_finder.eures_parser import EURESParser
from job_finder.eulisa_fetcher import EULISAFetcher
from job_finder.eulisa_parser import EULISAParser

# Common Components
from job_finder.keyword_filter import KeywordFilter
from job_finder.interfaces import ParsedAnnouncement, BOPage
from job_finder.notifier import send_notifications
from job_finder.sodetegc_fetcher import SODETEGCFetchError, SODETEGCFetcher
from job_finder.sodetegc_parser import (
    ObservationStatus,
    SODETEGCObservation,
    SODETEGCParser,
)
import threading


ES_SOURCES = (
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
    "SODETEGC",
)
EU_SOURCES = ("EPSO", "EURES", "EULISA")
ALL_SOURCES = ES_SOURCES + EU_SOURCES
SOURCE_GROUPS = ("EU", "ES", "ALL")
SOURCE_CHOICES = ALL_SOURCES + SOURCE_GROUPS


class ThreadLocalStream:
    def __init__(self, default_stream):
        self.default_stream = default_stream
        self.local = threading.local()

    def write(self, data):
        stream = getattr(self.local, "stream", None)
        if stream is not None:
            stream.write(data)
        else:
            self.default_stream.write(data)

    def flush(self):
        stream = getattr(self.local, "stream", None)
        if stream is not None:
            stream.flush()
        else:
            self.default_stream.flush()

    def __getattr__(self, name):
        return getattr(self.default_stream, name)


def get_temp_path(filename: str) -> Path:
    """Dynamically resolves a valid temporary file path for both AWS Lambda and local environments."""
    base_dir = "/tmp" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else tempfile.gettempdir()
    return Path(base_dir) / filename



def parse_date(date_str: str) -> datetime.date:
    """Parses a date string in YYYY-MM-DD format."""
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: '{date_str}'. Must be YYYY-MM-DD.")

def format_announcement(ann: ParsedAnnouncement) -> str:
    """Formats a parsed announcement into a beautiful, premium terminal output."""
    if ann.kind == "source_notice":
        description = _terminal_safe_text(ann.description)
        wrapper = textwrap.TextWrapper(width=76, initial_indent="   ", subsequent_indent="   ")
        parts = [f"⚠️ Source-page notice — {ann.source}", wrapper.fill(description)]
        if ann.url:
            parts.append(f"   🔗 Official page for review: {ann.url}")
        return "\n".join(parts)

    source_label = f"{ann.source} - Página" if ann.source == "BOP" else f"{ann.source} - Item"
    header = f"📌 {ann.organism.upper()} ({source_label} {ann.page_number})"
    
    # Wrap description paragraph to 76 characters, with a 3-space indent
    wrapper = textwrap.TextWrapper(width=76, initial_indent="   ", subsequent_indent="   ")
    wrapped_desc = wrapper.fill(ann.description)
    
    keywords_str = f"   🔑 Keywords matched: {', '.join(ann.matched_keywords)}"
    url_str = f"   🔗 URL: {ann.url}" if ann.url else ""
    
    parts = [header, wrapped_desc, keywords_str]
    if url_str:
        parts.append(url_str)
        
    return "\n".join(parts)


def _terminal_safe_text(value: str) -> str:
    """Remove control and bidi-format characters from untrusted visible text."""
    return "".join(
        " " if unicodedata.category(character) in {"Cc", "Cf"} else character
        for character in value
    )


def _markdown_escape(value: str) -> str:
    """Escape untrusted text before placing it in Markdown output."""
    special = "\\`*_{}[]<>#+-.!|()~"
    return "".join(f"\\{character}" if character in special else character for character in value)


def _sodetegc_notice(observation: SODETEGCObservation) -> Optional[ParsedAnnouncement]:
    if observation.status is not ObservationStatus.CHANGED:
        return None

    excerpt = _terminal_safe_text(observation.owned_text).strip()
    excerpt = " ".join(excerpt.split())[:500]
    if excerpt:
        description = (
            "El contenido visible de la sección «Convocatorias abiertas» difiere "
            "del texto de referencia. Revisión manual necesaria. "
            f"Extracto: «{excerpt}». Este aviso no confirma una vacante ni la elegibilidad."
        )
    else:
        description = (
            "La sección «Convocatorias abiertas» está vacía y el texto de referencia "
            "no aparece. Revisión manual necesaria. Este aviso no confirma una vacante "
            "ni la elegibilidad."
        )
    return ParsedAnnouncement(
        organism="SODETEGC · aviso de seguimiento",
        description=description,
        page_number=0,
        matched_keywords=[],
        source="SODETEGC",
        url=SODETEGCParser.URL,
        kind="source_notice",
    )


def _announcement_key(announcement: ParsedAnnouncement) -> tuple:
    return (
        announcement.kind,
        announcement.source,
        announcement.organism,
        announcement.description,
        announcement.page_number,
        tuple(announcement.matched_keywords),
        announcement.url,
    )


def save_markdown_findings(announcements: List[ParsedAnnouncement], output_path: Path) -> None:
    """Saves the scanning findings to a human-readable markdown file, overwriting it."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    source_notices = [ann for ann in announcements if ann.kind == "source_notice"]
    job_findings = [ann for ann in announcements if ann.kind == "job"]
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            if source_notices:
                title = (
                    "# 🔎 Source-page Notices"
                    if not job_findings
                    else "# 🔎 IT Job Findings and Source-page Notices"
                )
            else:
                title = "# 🔎 IT Job Findings"
            f.write(f"{title}\n\n")
            f.write(f"**Scan Date:** {now_str}\n")
            if source_notices:
                f.write(f"**Job Findings:** {len(job_findings)}\n")
                f.write(f"**Source Notices:** {len(source_notices)}\n\n")
            else:
                f.write(f"**Total Findings:** {len(announcements)}\n\n")
            f.write("---\n\n")

            if not announcements:
                f.write("ℹ️ No IT-related jobs found matching your filters in any source.\n")
            else:
                for i, ann in enumerate(announcements, 1):
                    if ann.kind == "source_notice":
                        f.write(f"## ⚠️ Source-page notice: {_markdown_escape(ann.source)}\n\n")
                        f.write("**Review required:**\n\n")
                        f.write(f"{_markdown_escape(ann.description.strip())}\n\n")
                        if ann.url:
                            f.write(f"**Official page:** [Review source page]({ann.url})\n\n")
                        if i < len(announcements):
                            f.write("---\n\n")
                        continue

                    source_label = f"{ann.source} - Página" if ann.source == "BOP" else f"{ann.source} - Item"
                    f.write(f"## 📌 {ann.organism.upper()} ({source_label} {ann.page_number})\n\n")
                    f.write("**Description:**\n")
                    f.write(f"{ann.description.strip()}\n\n")

                    keywords_formatted = ", ".join(f"`{k}`" for k in ann.matched_keywords)
                    f.write(f"**Keywords:** {keywords_formatted}\n\n")

                    if ann.url:
                        f.write(f"**URL:** [Link to announcement]({ann.url})\n\n")

                    if i < len(announcements):
                        f.write("---\n\n")
        print(f"💾 Findings successfully saved to {output_path}")
    except Exception as e:
        print(f"⚠️ Warning: Could not save findings to {output_path}: {e}", file=sys.stderr)


def print_source_header(source_name: str) -> None:
    """Prints a beautiful, box-drawn header for the given source."""
    if source_name == "BOP":
        title = "BOP LAS PALMAS"
    elif source_name == "BOC":
        title = "BOC - GOBIERNO DE CANARIAS"
    elif source_name == "BOE":
        title = "BOE - BOLETÍN OFICIAL DEL ESTADO"
    elif source_name == "SAGULPA":
        title = "SAGULPA - MUNICIPAL JOB BOARD"
    elif source_name == "GUAGUAS":
        title = "GUAGUAS - MUNICIPAL JOB BOARD"
    elif source_name == "GEURSA":
        title = "GEURSA - EMPLOYMENT SELECTION PROCESSES"
    elif source_name == "GSC":
        title = "GSC - HEALTH AND SAFETY EMPLOYMENT PROCESSES"
    elif source_name == "INDRA":
        title = "INDRA GROUP - CAREERS PORTAL"
    elif source_name == "FULP":
        title = "FULP - UNIVERSITY EMPLOYMENT BOARD"
    elif source_name == "SODETEGC":
        title = "SODETEGC - EMPLOYMENT PAGE STATUS"
    elif source_name == "EPSO":
        title = "EPSO - EUROPEAN UNION OPEN DATA"
    elif source_name == "EURES":
        title = "EURES - EUROPEAN JOB MOBILITY PORTAL"
    elif source_name == "EULISA":
        title = "eu-LISA - LARGE-SCALE IT SYSTEMS AGENCY"
    else:
        title = f"{source_name} SOURCE SCAN"
    print("\n" + "╔" + "═" * 58 + "╗")
    print(f"║{title.center(58)}║")
    print("╚" + "═" * 58 + "╝")


def _is_guaguas_html(html: str) -> bool:
    """Recognize Guaguas HTML using the same structural containers as its parser."""
    return GuaguasParser.has_supported_container(html)


def _is_geursa_html(html: str) -> bool:
    """Recognize GEURSA HTML using its active accordion structure."""
    return GeursaParser.has_supported_structure(html)


def _is_gsc_html(html: str) -> bool:
    """Recognize GSC HTML using its bounded selection holder."""
    return GSCParser.has_supported_structure(html)


def _is_indra_html(html: str) -> bool:
    """Recognize Indra detail HTML using bounded fields and official identity."""
    return IndraParser.has_supported_structure(html)


def _is_fulp_html(html: str) -> bool:
    """Recognize FULP HTML using its bounded list/detail structures."""
    return FulpParser.has_supported_structure(html)


def _is_sodetegc_html(html: str) -> bool:
    """Recognize SODETEGC only from its official identity and page structure."""
    return SODETEGCParser.has_page_signature(html)


def _has_bounded_gsc_filename(filename: str) -> bool:
    """Recognize a GSC filename token without matching words such as ``gscout``."""
    return re.search(r"(?<![a-z0-9])gsc(?![a-z0-9])", filename.casefold()) is not None


def _has_bounded_indra_filename(filename: str) -> bool:
    """Recognize an explicitly named Indra snapshot without matching indradar."""
    return re.search(r"(?<![a-z0-9])indra(?![a-z0-9])", filename.casefold()) is not None


def _has_bounded_fulp_filename(filename: str) -> bool:
    """Recognize an explicitly named FULP snapshot without matching fulpout."""
    return re.search(r"(?<![a-z0-9])fulp(?![a-z0-9])", filename.casefold()) is not None


def _scan_single_source(
    src: str,
    resolved_date: datetime.date,
    target_date: Optional[datetime.date],
    is_default_date: bool,
    is_lambda: bool,
    kf: Optional[KeywordFilter]
) -> tuple[List[ParsedAnnouncement], str]:
    """Scrapes and scans a single source, capturing all console output to a buffer."""
    import io
    buffer = io.StringIO()
    
    # Only set local stream if the proxy is actually active
    if hasattr(sys.stdout, "local"):
        sys.stdout.local.stream = buffer
    if hasattr(sys.stderr, "local"):
        sys.stderr.local.stream = buffer

    try:
        print_source_header(src)
        pages: List[BOPage] = []
        
        if src == "BOP":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d')} (BOP format: {resolved_date.day}-{resolved_date.month}-{resolved_date.year % 100})")
            fetcher = BOPFetcher()
            bop_parser = BOPParser()
            tmp_pdf_path = get_temp_path("bop_bulletin.pdf")
            
            try:
                print("🌐 Connecting to www.boplaspalmas.net...")
                pdf_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Offloading to disk buffer...")
                tmp_pdf_path.write_bytes(pdf_stream.getvalue())
                print("🔎 Parsing PDF from ephemeral storage...")
                pages = bop_parser.parse(tmp_pdf_path)
            except BOPNotPublishedError as e:
                if is_default_date:
                    print(f"⚠️  No BOP bulletin found for today ({resolved_date.strftime('%Y-%m-%d')}).")
                    print("🔄 Falling back to the latest available bulletin on the website...")
                    try:
                        pdf_stream, latest_date = fetcher.fetch_latest()
                        if is_lambda and latest_date < resolved_date:
                            print(f"⚠️  Lambda Mode: Skipping fallback bulletin dated {latest_date.strftime('%Y-%m-%d')} to avoid duplicate notifications.")
                        else:
                            print(f"📥 Found and downloaded latest BOP bulletin from: {latest_date.strftime('%Y-%m-%d')}")
                            tmp_pdf_path.write_bytes(pdf_stream.getvalue())
                            pages = bop_parser.parse(tmp_pdf_path)
                    except Exception as fallback_err:
                        print(f"❌ BOP fallback failed: {fallback_err}", file=sys.stderr)
                    finally:
                        if tmp_pdf_path.exists():
                            tmp_pdf_path.unlink(missing_ok=True)
                else:
                    print(f"⚠️  {e}")
            except BOPFetchError as e:
                print(f"❌ BOP download failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"❌ Unexpected BOP error: {e}", file=sys.stderr)
            finally:
                if tmp_pdf_path.exists():
                    tmp_pdf_path.unlink(missing_ok=True)
                
        elif src == "BOC":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d')}")
            fetcher = BOCFetcher()
            boc_parser = BOCParser()
            
            try:
                print("🌐 Connecting to www.gobiernodecanarias.org RSS feeds...")
                xml_stream = fetcher.fetch(resolved_date)
                pages = boc_parser.parse(xml_stream)
                
                if not pages and is_default_date:
                    print(f"⚠️  No BOC announcements found for today ({resolved_date.strftime('%Y-%m-%d')}).")
                    print("🔄 Falling back to the latest date present in the RSS feed...")
                    try:
                        xml_stream, latest_date = fetcher.fetch_latest()
                        if is_lambda and latest_date < resolved_date:
                            print(f"⚠️  Lambda Mode: Skipping fallback announcements dated {latest_date.strftime('%Y-%m-%d')} to avoid duplicate notifications.")
                        else:
                            print(f"📥 Found and downloaded latest BOC announcements from: {latest_date.strftime('%Y-%m-%d')}")
                            pages = boc_parser.parse(xml_stream)
                    except Exception as fallback_err:
                        print(f"❌ BOC fallback failed: {fallback_err}", file=sys.stderr)
            except BOCFetchError as e:
                print(f"❌ BOC download failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"❌ Unexpected BOC error: {e}", file=sys.stderr)

        elif src == "BOE":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d')}")
            fetcher = BOEFetcher()
            boe_parser = BOEParser(pdf_fetcher=fetcher)
            
            try:
                print("🌐 Connecting to www.boe.es Open Data API...")
                xml_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing XML in memory...")
                pages = boe_parser.parse(xml_stream)
                
                if not pages and is_default_date:
                    print(f"⚠️  No BOE announcements found for today ({resolved_date.strftime('%Y-%m-%d')}).")
                    print("🔄 Falling back to the latest available bulletin...")
                    try:
                        xml_stream, latest_date = fetcher.fetch_latest()
                        if is_lambda and latest_date < resolved_date:
                            print(f"⚠️  Lambda Mode: Skipping fallback announcements dated {latest_date.strftime('%Y-%m-%d')} to avoid duplicate notifications.")
                        else:
                            print(f"📥 Found and downloaded latest BOE bulletin from: {latest_date.strftime('%Y-%m-%d')}")
                            pages = boe_parser.parse(xml_stream)
                    except Exception as fallback_err:
                        print(f"❌ BOE fallback failed: {fallback_err}", file=sys.stderr)
            except BOENotPublishedError as e:
                if is_default_date:
                    print(f"⚠️  No BOE bulletin found for today ({resolved_date.strftime('%Y-%m-%d')}).")
                    print("🔄 Falling back to the latest available bulletin...")
                    try:
                        xml_stream, latest_date = fetcher.fetch_latest()
                        if is_lambda and latest_date < resolved_date:
                            print(f"⚠️  Lambda Mode: Skipping fallback announcements dated {latest_date.strftime('%Y-%m-%d')} to avoid duplicate notifications.")
                        else:
                            print(f"📥 Found and downloaded latest BOE bulletin from: {latest_date.strftime('%Y-%m-%d')}")
                            pages = boe_parser.parse(xml_stream)
                    except Exception as fallback_err:
                        print(f"❌ BOE fallback failed: {fallback_err}", file=sys.stderr)
                else:
                    print(f"⚠️  {e}")
            except BOEFetchError as e:
                print(f"❌ BOE download failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"❌ Unexpected BOE error: {e}", file=sys.stderr)
        
        elif src == "GUAGUAS":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d')}")
            fetcher = GuaguasFetcher()
            guaguas_parser = GuaguasParser()

            try:
                print("🌐 Connecting to www.guaguas.com employment board...")
                list_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing Guaguas employment cards...")
                pages = guaguas_parser.parse(list_stream, target_date=resolved_date)
            except Exception as e:
                print(f"❌ Guaguas download/parse failed: {e}", file=sys.stderr)

        elif src == "GEURSA":
            print("📅 GEURSA inclusion: every card under 'Convocatorias en vigor'")
            fetcher = GeursaFetcher()
            geursa_parser = GeursaParser()

            try:
                print("🌐 Connecting to www.geursa.es employment selection board...")
                list_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing GEURSA active-process cards...")
                pages = geursa_parser.parse(list_stream, target_date=resolved_date)
            except Exception as e:
                print(f"❌ GEURSA download/parse failed: {e}", file=sys.stderr)

        elif src == "GSC":
            print(
                "📅 GSC inclusion: publication date through publication + 7 days "
                "(inclusive; synthetic monitoring window)"
            )
            fetcher = GSCFetcher()
            gsc_parser = GSCParser()

            try:
                print("🌐 Connecting to www.gsccanarias.com GSC selection board...")
                list_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing GSC selection cards...")
                pages = gsc_parser.parse(list_stream, target_date=resolved_date)
            except Exception as e:
                print(f"❌ GSC download/parse failed: {e}", file=sys.stderr)

        elif src == "INDRA":
            print(
                "📅 Indra discovery: full blank catalogue search by default; "
                "configured portal_search_keywords narrow discovery only"
            )
            fetcher = IndraFetcher()
            indra_parser = IndraParser(fetcher=fetcher, keyword_filter=kf)

            try:
                print("🌐 Connecting to careers.indragroup.com search...")
                pages = indra_parser.scan(kf.portal_search_keywords)
            except Exception as e:
                print(f"❌ Indra discovery/detail scan failed: {e}", file=sys.stderr)

        elif src == "FULP":
            print(
                "📅 FULP discovery: one current public listing, then one detail request "
                "per deduplicated numeric offer ID"
            )
            fetcher = FulpFetcher()
            fulp_parser = FulpParser(fetcher=fetcher)

            try:
                print("🌐 Connecting to www.fulp.es public offers...")
                pages = fulp_parser.scan(target_date=target_date)
            except Exception as e:
                print(f"❌ FULP discovery/detail scan failed: {e}", file=sys.stderr)

        elif src == "SAGULPA":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d') if (target_date or is_lambda) else 'ALL ACTIVE OPENINGS'}")
            fetcher = SagulpaFetcher()
            sagulpa_parser = SagulpaParser(fetcher=fetcher)
            
            try:
                print("🌐 Connecting to www.sagulpa.com job board...")
                list_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing HTML and deep-scanning active details...")
                pages = sagulpa_parser.parse(list_stream, target_date=resolved_date if is_lambda else target_date)
            except Exception as e:
                print(f"❌ Sagulpa download/parse failed: {e}", file=sys.stderr)
        
        elif src == "AENA":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d') if (target_date or is_lambda) else 'ALL ACTIVE OPENINGS'}")
            fetcher = AenaFetcher()
            aena_parser = AenaParser(fetcher=fetcher, keyword_filter=kf)
            
            try:
                print("🌐 Connecting to Aena Employment Portal...")
                list_stream = fetcher.fetch(resolved_date)
                print("📥 Download complete! Parsing HTML and deep-scanning active details...")
                pages = aena_parser.parse(list_stream, target_date=resolved_date if is_lambda else target_date)
            except Exception as e:
                print(f"❌ Aena download/parse failed: {e}", file=sys.stderr)
        
        elif src == "EPSO":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d') if (target_date or is_lambda) else 'ALL ACTIVE OPENINGS'}")
            fetcher = EPSOFetcher()
            epso_parser = EPSOParser()
            
            try:
                print("🌐 Connecting to EU Open Data CKAN API...")
                raw_data = fetcher.fetch_raw()
                print("📥 Download complete! Parsing CSV...")
                pages = epso_parser.parse_raw(raw_data, target_date=resolved_date if is_lambda else target_date)
            except Exception as e:
                print(f"❌ EPSO download/parse failed: {e}", file=sys.stderr)
                
        elif src == "EURES":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d') if (target_date or is_lambda) else 'ALL ACTIVE OPENINGS'}")
            fetcher = EURESFetcher()
            eures_parser = EURESParser()
            
            try:
                raw_data = fetcher.fetch_raw()
                if raw_data:
                    print("📥 Download complete! Parsing JSON...")
                    pages = eures_parser.parse_raw(raw_data, target_date=resolved_date if is_lambda else target_date)
                else:
                    print("⚠️ Skipping EURES scanning due to live fetch bypass/failure.")
            except Exception as e:
                print(f"❌ EURES download/parse failed: {e}", file=sys.stderr)
                
        elif src == "EULISA":
            print(f"📅 Target Date: {resolved_date.strftime('%Y-%m-%d') if (target_date or is_lambda) else 'ALL ACTIVE OPENINGS'}")
            fetcher = EULISAFetcher()
            eulisa_parser = EULISAParser()
            
            try:
                print("🌐 Connecting to eu-LISA Careers Portal...")
                raw_data = fetcher.fetch_raw()
                print("📥 Download complete! Parsing HTML...")
                pages = eulisa_parser.parse_raw(raw_data, target_date=resolved_date if is_lambda else target_date)
            except Exception as e:
                print(f"❌ eu-LISA download/parse failed: {e}", file=sys.stderr)

        elif src == "SODETEGC":
            print(
                "📅 SODETEGC evaluates the current employment-page response; "
                "target_date does not reconstruct historical page state."
            )
            try:
                html = SODETEGCFetcher().fetch()
            except SODETEGCFetchError as e:
                observation = SODETEGCObservation(
                    status=ObservationStatus.UNVERIFIABLE,
                    diagnostic=str(e),
                )
            else:
                observation = SODETEGCParser.parse(html)

            if observation.status is ObservationStatus.UNVERIFIABLE:
                print(f"⚠️ SODETEGC UNVERIFIABLE: {observation.diagnostic}", file=sys.stderr)
                return [], buffer.getvalue()
            if observation.status is ObservationStatus.BASELINE:
                print("ℹ️ SODETEGC active section matches its reference text; no source notice.")
                return [], buffer.getvalue()

            notice = _sodetegc_notice(observation)
            if notice is not None:
                print("⚠️ SODETEGC source-page notice created for manual review.")
                return [notice], buffer.getvalue()
            return [], buffer.getvalue()

        # Scan the pages/items for this source
        src_announcements = []
        if src == "GSC":
            print(f"📊 GSC included records: {len(pages)}")
        if pages:
            print(f"🔎 Scanning {len(pages)} pages/entries in this bulletin...")
            if kf is None:
                raise RuntimeError(f"Keyword filter is unavailable for ordinary source {src}.")
            for page in pages:
                src_announcements.extend(kf.search_page(page))

            if src == "INDRA":
                print(f"📊 INDRA first-filter matches: {len(src_announcements)}")
            
            if src_announcements:
                print(f"🎉 Success: Found {len(src_announcements)} matching announcement(s)!")
            else:
                print("ℹ️  No matching IT jobs found in this source for this date.")
        else:
            print("ℹ️  No target pages were fetched or parsed for this source.")

        return src_announcements, buffer.getvalue()

    except Exception as e:
        print(f"❌ Critical thread error scanning source {src}: {e}", file=sys.stderr)
        return [], buffer.getvalue()

    finally:
        if hasattr(sys.stdout, "local"):
            sys.stdout.local.stream = None
        if hasattr(sys.stderr, "local"):
            sys.stderr.local.stream = None


def run_scan(
    target_date: Optional[datetime.date] = None,
    sources: Optional[List[str]] = None,
    config_path: Optional[Path] = None,
    no_ai: bool = False,
    is_lambda: bool = False,
    local_file: Optional[Path] = None
) -> List[ParsedAnnouncement]:
    """
    Core execution logic for scanning.
    Extracts IT job announcements from designated Spanish & European bulletins.
    """
    kf: Optional[KeywordFilter] = None

    def get_keyword_filter() -> KeywordFilter:
        nonlocal kf
        if kf is None:
            try:
                kf = KeywordFilter(config_path=config_path)
            except Exception as e:
                print(f"❌ Error loading keyword configuration: {e}", file=sys.stderr)
                raise
        return kf
        
    all_announcements: List[ParsedAnnouncement] = []
    
    # CASE 1: Scan a local file
    if local_file:
        if not local_file.exists():
            print(f"❌ Error: Local file '{local_file}' does not exist.", file=sys.stderr)
            return []
            
        # Detect source type by extension or signature
        suffix = local_file.suffix.lower()
        if suffix == ".pdf":
            source_type = "BOP"
        elif suffix in (".xml", ".rss"):
            # Distinguish between BOC and BOE by checking for RSS tag vs sumario/response tag
            try:
                with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                    head = f.read(1000)
                if "<rss" in head:
                    source_type = "BOC"
                elif "<response" in head or "<sumario" in head:
                    source_type = "BOE"
                else:
                    source_type = "BOE" if "boe" in local_file.name.lower() else "BOC"
            except Exception:
                source_type = "BOC"
        elif suffix in (".html", ".htm"):
            # Distinguish between bounded source layouts and named HTML snapshots.
            file_name = local_file.name.lower()
            try:
                local_html = local_file.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                local_html = ""
            if _is_sodetegc_html(local_html):
                source_type = "SODETEGC"
            elif "geursa" in file_name:
                source_type = "GEURSA"
            elif "guaguas" in file_name:
                source_type = "GUAGUAS"
            elif _has_bounded_gsc_filename(file_name):
                source_type = "GSC"
            elif _has_bounded_indra_filename(file_name):
                source_type = "INDRA"
            elif _has_bounded_fulp_filename(file_name):
                source_type = "FULP"
            elif "eulisa" in file_name:
                source_type = "EULISA"
            elif "aena" in file_name:
                source_type = "AENA"
            else:
                try:
                    with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                        html = f.read()
                    html_lower = html.lower()
                    if _is_sodetegc_html(html):
                        source_type = "SODETEGC"
                    elif _is_geursa_html(html):
                        source_type = "GEURSA"
                    elif _is_guaguas_html(html):
                        source_type = "GUAGUAS"
                    elif _is_gsc_html(html):
                        source_type = "GSC"
                    elif _is_indra_html(html):
                        source_type = "INDRA"
                    elif _is_fulp_html(html):
                        source_type = "FULP"
                    elif "eulisa" in html_lower:
                        source_type = "EULISA"
                    elif "aena" in html_lower:
                        source_type = "AENA"
                    else:
                        source_type = "SAGULPA"
                except Exception:
                    source_type = "SAGULPA"
        elif suffix == ".csv":
            source_type = "EPSO"
        elif suffix == ".json":
            source_type = "EURES"
        else:
            # Check file signature
            try:
                with open(local_file, "rb") as f:
                    sig = f.read(4)
                if sig.startswith(b"%PDF"):
                    source_type = "BOP"
                elif sig.startswith(b"<?xml") or sig.startswith(b"<rss") or b"<" in sig:
                    with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    content_lower = content.lower()
                    if _is_sodetegc_html(content):
                        source_type = "SODETEGC"
                    elif _is_geursa_html(content):
                        source_type = "GEURSA"
                    elif _is_guaguas_html(content):
                        source_type = "GUAGUAS"
                    elif _is_gsc_html(content):
                        source_type = "GSC"
                    elif _is_indra_html(content):
                        source_type = "INDRA"
                    elif _is_fulp_html(content):
                        source_type = "FULP"
                    elif "<rss" in content_lower:
                        source_type = "BOC"
                    elif "<html" in content_lower or "<!doctype" in content_lower:
                        if "geursa" in local_file.name.lower():
                            source_type = "GEURSA"
                        elif _has_bounded_gsc_filename(local_file.name):
                            source_type = "GSC"
                        elif _has_bounded_indra_filename(local_file.name):
                            source_type = "INDRA"
                        elif _has_bounded_fulp_filename(local_file.name):
                            source_type = "FULP"
                        elif "eulisa" in local_file.name.lower():
                            source_type = "EULISA"
                        elif "aena" in local_file.name.lower():
                            source_type = "AENA"
                        else:
                            source_type = "SAGULPA"
                    else:
                        source_type = "BOE"
                elif sig.startswith(b"<!DO") or sig.startswith(b"<htm") or b"<html" in sig.lower():
                    with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    content_lower = content.lower()
                    if _is_sodetegc_html(content):
                        source_type = "SODETEGC"
                    elif "geursa" in local_file.name.lower() or _is_geursa_html(content):
                        source_type = "GEURSA"
                    elif "guaguas" in local_file.name.lower() or _is_guaguas_html(content):
                        source_type = "GUAGUAS"
                    elif _has_bounded_gsc_filename(local_file.name) or _is_gsc_html(content):
                        source_type = "GSC"
                    elif _has_bounded_indra_filename(local_file.name) or _is_indra_html(content):
                        source_type = "INDRA"
                    elif _has_bounded_fulp_filename(local_file.name) or _is_fulp_html(content):
                        source_type = "FULP"
                    elif "eulisa" in local_file.name.lower():
                        source_type = "EULISA"
                    elif "aena" in local_file.name.lower():
                        source_type = "AENA"
                    elif "eulisa" in content_lower:
                        source_type = "EULISA"
                    elif "aena" in content_lower:
                        source_type = "AENA"
                    else:
                        source_type = "SAGULPA"
                elif sig.startswith(b"{") or sig.startswith(b"["):
                    source_type = "EURES"
                elif b"," in sig or b";" in sig:
                    source_type = "EPSO"
                else:
                    with open(local_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if _is_sodetegc_html(content):
                        source_type = "SODETEGC"
                    elif _is_gsc_html(content):
                        source_type = "GSC"
                    elif _is_indra_html(content):
                        source_type = "INDRA"
                    elif _is_fulp_html(content):
                        source_type = "FULP"
                    else:
                        print(f"❌ Error: Unrecognized file type for '{local_file.name}'. Must be PDF, XML, HTML, CSV, or JSON.", file=sys.stderr)
                        return []
            except Exception as e:
                print(f"❌ Error detecting file type: {e}", file=sys.stderr)
                return []
                
        print(f"📂 Scanning local {source_type} file: {local_file.name}")
        print_source_header(source_type)

        if source_type == "SODETEGC":
            try:
                local_html = local_file.read_bytes().decode("utf-8-sig", errors="strict")
                observation = SODETEGCParser.parse(local_html)
            except UnicodeDecodeError:
                observation = SODETEGCObservation(
                    status=ObservationStatus.UNVERIFIABLE,
                    diagnostic="local HTML is not valid UTF-8",
                )
            except OSError as e:
                observation = SODETEGCObservation(
                    status=ObservationStatus.UNVERIFIABLE,
                    diagnostic=f"could not read local HTML ({type(e).__name__})",
                )

            if observation.status is ObservationStatus.UNVERIFIABLE:
                print(f"⚠️ SODETEGC UNVERIFIABLE: {observation.diagnostic}", file=sys.stderr)
                return []
            if observation.status is ObservationStatus.BASELINE:
                print("ℹ️ SODETEGC active section matches its reference text; no source notice.")
                return []
            notice = _sodetegc_notice(observation)
            return [notice] if notice is not None else []

        kf = get_keyword_filter()
        
        try:
            if source_type == "BOP":
                parser_inst = BOPParser()
            elif source_type == "BOC":
                parser_inst = BOCParser()
            elif source_type == "BOE":
                parser_inst = BOEParser()
            elif source_type == "GUAGUAS":
                parser_inst = GuaguasParser()
            elif source_type == "GEURSA":
                parser_inst = GeursaParser()
            elif source_type == "GSC":
                parser_inst = GSCParser()
            elif source_type == "INDRA":
                parser_inst = IndraParser(keyword_filter=kf)
            elif source_type == "FULP":
                parser_inst = FulpParser()
            elif source_type == "SAGULPA":
                parser_inst = SagulpaParser()
            elif source_type == "AENA":
                parser_inst = AenaParser(keyword_filter=kf)
            elif source_type == "EPSO":
                parser_inst = EPSOParser()
            elif source_type == "EURES":
                parser_inst = EURESParser()
            elif source_type == "EULISA":
                parser_inst = EULISAParser()
            else:
                raise ValueError(f"Unknown source type: {source_type}")
                
            if source_type in {"GSC", "FULP"}:
                source_reference_date = target_date or datetime.date.today()
                pages = parser_inst.parse(local_file, target_date=source_reference_date)
                print(f"📊 {source_type} parsed/included records: {len(pages)}")
            else:
                pages = parser_inst.parse(local_file)
            print(f"🔎 Scanning {len(pages)} parsed sections for IT opportunities...")
            
            for page in pages:
                all_announcements.extend(kf.search_page(page))
        except Exception as e:
            print(f"❌ Error processing local file: {e}", file=sys.stderr)
            return []
            
    # CASE 2: Scan live online streams
    else:
        is_default_date = target_date is None
        resolved_date = datetime.date.today() if is_default_date else target_date
        
        # Decide which sources to run
        if not sources or "ALL" in sources:
            sources_to_run = list(ALL_SOURCES)
        elif "EU" in sources:
            sources_to_run = list(EU_SOURCES)
        elif "ES" in sources:
            sources_to_run = list(ES_SOURCES)
        else:
            sources_to_run = list(sources)

        if any(source != "SODETEGC" for source in sources_to_run):
            get_keyword_filter()
        
        # Ensure stdout/stderr are wrapped in ThreadLocalStream for parallel thread buffering if running multiple
        if len(sources_to_run) > 1:
            if not isinstance(sys.stdout, ThreadLocalStream):
                sys.stdout = ThreadLocalStream(sys.stdout)
            if not isinstance(sys.stderr, ThreadLocalStream):
                sys.stderr = ThreadLocalStream(sys.stderr)
                
        # Run sources concurrently
        from concurrent.futures import ThreadPoolExecutor
        results_by_source = {}

        def run_thread(src):
            results_by_source[src] = _scan_single_source(
                src=src,
                resolved_date=resolved_date,
                target_date=target_date,
                is_default_date=is_default_date,
                is_lambda=is_lambda,
                kf=kf
            )

        if len(sources_to_run) > 1:
            with ThreadPoolExecutor(max_workers=len(sources_to_run)) as executor:
                list(executor.map(run_thread, sources_to_run))
        else:
            run_thread(sources_to_run[0])

        # Print all buffered outputs sequentially and collect announcements
        sodetegc_notice_added = False
        for src in sources_to_run:
            if src in results_by_source:
                src_announcements, log_output = results_by_source[src]
                if log_output:
                    print(log_output, end="")
                for announcement in src_announcements:
                    if (
                        announcement.kind == "source_notice"
                        and announcement.source == "SODETEGC"
                    ):
                        if sodetegc_notice_added:
                            continue
                        sodetegc_notice_added = True
                    all_announcements.append(announcement)

    if all_announcements and not no_ai:
        job_candidates = [ann for ann in all_announcements if ann.kind == "job"]
        source_notices = [ann for ann in all_announcements if ann.kind == "source_notice"]
        if job_candidates:
            from job_finder.gemini_validator import GeminiValidator

            validator = GeminiValidator()
            if validator.enabled:
                print(f"\n🤖 Running AI validation on {len(job_candidates)} job candidate(s)...")
                validated_jobs = validator.validate_batch(job_candidates)
                if source_notices:
                    remaining = {}
                    for announcement in validated_jobs:
                        key = _announcement_key(announcement)
                        remaining[key] = remaining.get(key, 0) + 1
                    merged = []
                    for announcement in all_announcements:
                        if announcement.kind == "source_notice":
                            merged.append(announcement)
                            continue
                        key = _announcement_key(announcement)
                        if remaining.get(key, 0):
                            merged.append(announcement)
                            remaining[key] -= 1
                    all_announcements = merged
                    print(
                        f"✅ AI validation complete. {len(validated_jobs)} job finding(s) retained; "
                        f"{len(source_notices)} source notice(s) retained for manual review."
                    )
                else:
                    all_announcements = validated_jobs
                    print(f"✅ AI validation complete. {len(all_announcements)} confirmed as relevant.")

    return all_announcements



def lambda_handler(event, context):
    """
    AWS Lambda entrypoint triggered by EventBridge (Cron) or custom invocation.
    Event payload parameters (optional):
      - sources: List of source names or groups to scan (e.g. ["ES", "EULISA"])
      - no_ai: Set to True to bypass Gemini AI validation
    """
    print("🚀 AWS Lambda Job Finder trigger started!")
    
    # Load sources and arguments from event payload, default to ALL
    sources = event.get("sources", ["ALL"]) if isinstance(event, dict) else ["ALL"]
    no_ai = event.get("no_ai", False) if isinstance(event, dict) else False

    # Execute core scanning with is_lambda=True to activate stateless filtering
    findings = run_scan(
        target_date=None,  # Defaults to today
        sources=sources,
        no_ai=no_ai,
        is_lambda=True
    )
    
    # Send notifications via Discord and/or Telegram if configured in Env Variables
    job_count = sum(announcement.kind == "job" for announcement in findings)
    notice_count = len(findings) - job_count
    if findings:
        send_notifications(findings)
        if notice_count and job_count:
            print(
                f"📢 AWS Lambda finished. Submitted {job_count} job finding(s) and "
                f"{notice_count} source notice(s) for notification."
            )
        elif notice_count:
            print(
                f"📢 AWS Lambda finished. Submitted {notice_count} source notice(s) "
                "for notification; no vacancy was confirmed."
            )
        else:
            print(f"📢 AWS Lambda finished. Sent notifications for {len(findings)} job offers.")
    else:
        print("📢 AWS Lambda finished. No job offers matched today.")
        
    description = (
        f"Successfully processed. Found {job_count} relevant jobs and "
        f"{notice_count} source notice(s)."
        if notice_count
        else f"Successfully processed. Found {len(findings)} relevant jobs."
    )
    return {
        "statusCode": 200,
        "body": description
    }


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Boletín Oficial Monitor (BOP & BOC) - IT & Software Engineering Job Scanner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--date",
        type=parse_date,
        default=None,
        help="Target date to scan (format: YYYY-MM-DD)"
    )
    group.add_argument(
        "--file",
        type=Path,
        help="Local file path to scan (.pdf for BOP, .xml/.rss for BOC/BOE, .csv for EPSO, .json for EURES, .html for FULP/INDRA/GSC/GEURSA/Guaguas/Sagulpa/Aena/eu-LISA)"
    )
    parser.add_argument(
        "--source",
        "-s",
        choices=SOURCE_CHOICES,
        default="ALL",
        help="Target official source(s) to scan (use 'EU' for European Union, 'ES' for Spanish, or an individual source such as FULP, INDRA, GSC or GEURSA)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to custom keywords.yaml configuration file"
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        default=False,
        help="Disable optional Gemini AI validation of candidate announcements"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("findings.md"),
        help="Path to the file where findings will be saved (overwritten on each run)"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "html"],
        default="markdown",
        help="Output format for saved findings (markdown or html)"
    )
    
    args = parser.parse_args()
    
    print("═" * 60)
    print("  BOLETÍN OFICIAL - IT JOB SCANNER  ".center(60, "═"))
    print("═" * 60)
    
    # Run scan
    all_announcements = run_scan(
        target_date=args.date,
        sources=[args.source],
        config_path=args.config,
        no_ai=args.no_ai,
        is_lambda=False,
        local_file=args.file
    )

    print("\n" + "═" * 60)
    print("  SCAN COMPLETED - RESULTS SUMMARY  ".center(60, "═"))
    print("═" * 60)
    
    output_format = args.format.lower()
    if args.output.suffix.lower() == ".html":
        output_format = "html"

    if output_format == "html":
        from job_finder.html_exporter import save_html_findings
        save_html_findings(all_announcements, args.output)
    else:
        save_markdown_findings(all_announcements, args.output)

    # Print final aggregated findings to console
    if all_announcements:
        job_count = sum(announcement.kind == "job" for announcement in all_announcements)
        notice_count = len(all_announcements) - job_count
        if notice_count and job_count:
            print(
                f"📋 SCAN COMPLETE: {job_count} job finding(s) and {notice_count} "
                "source notice(s); notices require manual review.\n"
            )
        elif notice_count:
            print(
                f"⚠️ SCAN COMPLETE: {notice_count} source notice(s) require manual review; "
                "no vacancy was confirmed.\n"
            )
        else:
            print(f"🎉 TOTAL SUCCESS: Found {len(all_announcements)} IT job opening(s) across all active sources!\n")
        for i, ann in enumerate(all_announcements, 1):
            print(format_announcement(ann))
            if i < len(all_announcements):
                print("─" * 60)
        print("═" * 60)
        
        # Trigger notifications locally if env vars are present (useful for CLI execution or local testing)
        send_notifications(all_announcements)
        sys.exit(0)
    else:
        print("ℹ️  Finished searching. No IT-related jobs found matching your filters in any source.")
        print("═" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()
