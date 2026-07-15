import os
import re
import unicodedata
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from job_finder.interfaces import BOPage, ParsedAnnouncement

DEFAULT_KEYWORDS_PATH = Path(__file__).parent / "keywords.yaml"

def strip_accents(text: str) -> str:
    """Removes accents from Spanish text for robust searching."""
    nfd_form = unicodedata.normalize('NFD', text)
    return "".join([c for c in nfd_form if unicodedata.category(c) != 'Mn'])

class KeywordFilter:
    """Filters BOP pages to find IT job announcements using a two-step validation pipeline."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_KEYWORDS_PATH
        self.it_patterns: List[re.Pattern] = []
        self.anchor_patterns: List[re.Pattern] = []
        self.exclusion_patterns: List[re.Pattern] = []
        self.raw_it_keywords: List[str] = []
        self.raw_anchors: List[str] = []
        self.raw_exclusions: List[str] = []
        self.raw_title_reject_absolute: List[str] = []
        self.raw_title_reject_relative: List[str] = []
        self.reject_absolute_patterns: List[re.Pattern] = []
        self.reject_relative_patterns: List[re.Pattern] = []
        
        # English ESCO/EuroVoc IT Keyword dictionary for EU job boards
        self.raw_eu_it_keywords = [
            r"\bSoftware Engineer\b",
            r"\bSoftware Developer\b",
            r"\bApplications Developer\b",
            r"\bApplications Architect\b",
            r"\bFull-Stack\b",
            r"\bFull\s+Stack\s+Developer\b",
            r"\bBackend Developer\b",
            r"\bFrontend Developer\b",
            r"\bCloud Architect\b",
            r"\bCloud Engineer\b",
            r"\bDevOps Engineer\b",
            r"\bDevOps Specialist\b",
            r"\bSystem Administrator\b",
            r"\bSystems Administrator\b",
            r"\bInfrastructure Engineer\b",
            r"\bNetwork Engineer\b",
            r"\bNetwork Specialist\b",
            r"\bData Scientist\b",
            r"\bData Analyst\b",
            r"\bData Engineer\b",
            r"\bDatabase Administrator\b",
            r"\bDBA\b",
            r"\bICT Expert\b",
            r"\bICT Specialist\b",
            r"\bInformation Systems Officer\b",
            r"\bSolution Architect\b",
            r"\bEnterprise Architect\b",
            r"\bCybersecurity Specialist\b",
            r"\bInformation Security Officer\b"
        ]
        self.eu_it_patterns = [
            re.compile(pat, re.IGNORECASE) for pat in self.raw_eu_it_keywords
        ]
        
        self.load_config()

    def load_config(self) -> None:
        """Loads keyword and anchor patterns from YAML configuration."""
        if not self.config_path.exists():
            # Fallback to defaults if file not found
            self.raw_it_keywords = [
                r"inform[aá]tico?s?",
                r"sistemas?\\s+(?:y\\s+)?(?:redes|microinform[aá]tic|comunicaciones)",
                r"telecomunicaciones?",
                r"\btic\b",
                r"ingenier[oa]\\s+(?:de\\s+)?(?:software|inform[aá]tic[ao]|telecomunicac|sistemas)",
                r"programador[a]?",
                r"desarrollador[a]?",
                r"ciberseguridad",
                r"tecnolog[ií]as?\\s+(?:de\\s+la\\s+)?informaci[oó]n",
                r"auxiliar\\s+t[eé]cnico\\s+inform[aá]tico"
            ]
            self.raw_anchors = [
                "plaza", "convocatoria", "bases", "bolsa\\s+de\\s+empleo",
                "bolsa\\s+de\\s+trabajo", "oposici[oó]n", "personal\\s+laboral",
                "selecci[oó]n", "contrataci[oó]n", "bolsa\\s+de\\s+reserva"
            ]
            self.raw_exclusions = [
                r"aplicaci[oó]n\s+inform[aá]tica",
                r"aplicaciones\s+inform[aá]ticas",
                r"medios\s+inform[aá]ticos",
                r"recursos\s+inform[aá]ticos",
                r"herramientas?\s+inform[aá]ticas?",
                r"plataformas?\s+inform[aá]ticas?",
                r"incidencias\s+inform[aá]ticas?",
                r"soportes?\s+inform[aá]ticos?"
            ]
            self.raw_title_reject_absolute = [
                r"formativ[oa]s?",
                r"formativ\."
            ]
            self.raw_title_reject_relative = [
                "mantenimiento",
                "bomber[oa]s?"
            ]
        else:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                self.raw_it_keywords = config.get("it_keywords", [])
                self.raw_anchors = config.get("contest_anchors", [])
                self.raw_exclusions = config.get("boilerplate_exclusions", [])
                self.raw_title_reject_absolute = config.get("title_reject_absolute", [])
                self.raw_title_reject_relative = config.get("title_reject_relative", [])

        # Compile accent-stripped versions of patterns for matching against accent-stripped text
        self.it_patterns = [
            re.compile(strip_accents(pat), re.IGNORECASE) for pat in self.raw_it_keywords
        ]
        self.anchor_patterns = [
            re.compile(strip_accents(pat), re.IGNORECASE) for pat in self.raw_anchors
        ]
        self.exclusion_patterns = [
            re.compile(strip_accents(pat), re.IGNORECASE) for pat in self.raw_exclusions
        ]
        self.reject_absolute_patterns = [
            re.compile(strip_accents(pat), re.IGNORECASE) for pat in self.raw_title_reject_absolute
        ]
        self.reject_relative_patterns = [
            re.compile(strip_accents(pat), re.IGNORECASE) for pat in self.raw_title_reject_relative
        ]

    def search_page(self, page: BOPage) -> List[ParsedAnnouncement]:
        """
         Scans a single BOP page for matching IT job announcements.
        Splits text into paragraphs and applies two-step validation per paragraph.
        """
        announcements = []
        if not page.text:
            return announcements

        # Split page text into paragraphs
        paragraphs = page.text.split("\n\n")
        
        # Check if source is an EU job board/portal
        is_eu = page.source in ("EPSO", "EURES", "EULISA")
        
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            if is_eu:
                # Step 1: Detect matches from EU ESCO IT keywords (case-insensitive, strict word boundaries)
                matched_keywords = []
                for i, pattern in enumerate(self.eu_it_patterns):
                    if pattern.search(paragraph):
                        matched_keywords.append(self.raw_eu_it_keywords[i])
                
                if not matched_keywords:
                    continue
                
                # Step 2: For EU dedicated job boards, bypass contest anchors check (always True)
                has_anchor = True
            else:
                # Strip accents for Spanish matching
                match_target = strip_accents(paragraph)
                
                # Create a stripped version where boilerplate exclusions are removed
                stripped_match_target = match_target
                for pattern in self.exclusion_patterns:
                    stripped_match_target = pattern.sub(" ", stripped_match_target)
                
                # Step 1: Detect matches from IT keywords using stripped text
                matched_keywords = []
                for i, pattern in enumerate(self.it_patterns):
                    if pattern.search(stripped_match_target):
                        # Use raw keyword string for reference
                        matched_keywords.append(self.raw_it_keywords[i])
                
                if not matched_keywords:
                    continue
                    
                # Step 2: Verify that paragraph contains employment/contest anchors
                has_anchor = False
                for pattern in self.anchor_patterns:
                    if pattern.search(match_target):
                        has_anchor = True
                        break
                        
            if not has_anchor:
                continue  # Noise filtered out!
                
            # Match succeeded! Construct ParsedAnnouncement
            # Determine organism: fall back to page's detected organism if not found in paragraph
            organism = page.detected_organism or "Administración Local (Desconocido)"
            
            announcements.append(ParsedAnnouncement(
                organism=organism,
                description=paragraph,
                page_number=page.page_number,
                matched_keywords=matched_keywords,
                source=page.source,
                url=page.url
            ))
            
        return announcements

    def should_reject_title(self, title: str) -> bool:
        """
        Determines if a job title should be rejected early to avoid I/O overhead.
        
        Rules:
        1. Reject if any pattern in title_reject_absolute matches.
        2. Reject if any pattern in title_reject_relative matches AND no pattern in it_keywords matches.
        """
        if not title:
            return False
            
        stripped_title = strip_accents(title)
        
        # Rule 1: Absolute rejection
        for pattern in self.reject_absolute_patterns:
            if pattern.search(stripped_title):
                return True
                
        # Rule 2: Relative rejection
        has_relative_match = False
        for pattern in self.reject_relative_patterns:
            if pattern.search(stripped_title):
                has_relative_match = True
                break
                
        if has_relative_match:
            # Check if any IT keyword matches to override relative rejection
            has_it_override = False
            for pattern in self.it_patterns:
                if pattern.search(stripped_title):
                    has_it_override = True
                    break
            if not has_it_override:
                return True
                
        return False
