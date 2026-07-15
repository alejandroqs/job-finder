import io
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Union, List, Optional

@dataclass
class ParsedAnnouncement:
    """Represents a job opening or relevant announcement found in a gazette (BOP/BOC)."""
    organism: str
    description: str
    page_number: int
    matched_keywords: List[str] = field(default_factory=list)
    source: str = "BOP"
    url: str = ""

@dataclass
class BOPage:
    """Represents the raw/cleaned text extracted from a single page of a BOP PDF or RSS item."""
    page_number: int
    text: str
    section: str = ""
    detected_organism: str = ""
    source: str = "BOP"
    url: str = ""

class BaseFetcher(ABC):
    """Abstract Base Class for downloading BOP gazette PDFs."""
    
    @abstractmethod
    def fetch(self, target_date: date) -> io.BytesIO:
        """
        Downloads the BOP PDF for a specific date.
        
        Args:
            target_date: The date to download the bulletin for.
            
        Returns:
            A byte stream (BytesIO) containing the binary PDF content.
            
        Raises:
            Exception: If there's an error fetching the PDF.
        """
        pass

class BaseParser(ABC):
    """Abstract Base Class for parsing BOP gazettes."""
    
    @abstractmethod
    def parse(self, source: Union[Path, str, io.BytesIO]) -> List[BOPage]:
        """
        Parses a bulletin source and extracts text and metadata.
        
        Args:
            source: A file path (str/Path) or a byte stream (BytesIO) containing the bulletin.
            
        Returns:
            A list of BOPage objects containing the raw/cleaned text and metadata.
        """
        pass


class BaseWebBoardFetcher(ABC):
    """Abstract Base Class for downloading HTML-based corporate job boards."""
    
    @abstractmethod
    def fetch_list(self) -> str:
        """
        Downloads the main HTML list of job openings.
        
        Returns:
            The HTML content of the job openings page.
        """
        pass
        
    @abstractmethod
    def fetch_detail(self, detail_url: str) -> str:
        """
        Downloads the HTML detail page of a specific job opening.
        
        Args:
            detail_url: The absolute or relative URL to the detail page.
            
        Returns:
            The HTML content of the job detail page.
        """
        pass


class BaseWebBoardParser(ABC):
    """Abstract Base Class for parsing HTML-based corporate job boards."""
    
    @abstractmethod
    def parse_list(self, list_html: str, target_date: Optional[date] = None) -> List[dict]:
        """
        Parses the main list HTML, filtering out closed/inactive processes.
        
        Args:
            list_html: The raw HTML content of the list view.
            
        Returns:
            A list of dicts, where each dict represents an active job opening containing:
            - 'title': str
            - 'url': str (absolute)
            - 'date': datetime.date
        """
        pass
        
    @abstractmethod
    def parse_detail(self, detail_html: str) -> str:
        """
        Parses the detail page HTML to extract the full description text.
        
        Args:
            detail_html: The raw HTML content of the detail page.
            
        Returns:
            The cleaned description text extracted from the page.
        """
        pass


class BaseEUFetcher(ABC):
    """Abstract Base Class for downloading European Union IT job sources."""
    
    @abstractmethod
    def fetch_raw(self) -> Union[str, bytes]:
        """
        Fetches raw structured/unstructured feed data (CSV bytes, JSON string, or HTML string).
        
        Returns:
            The raw data content of the feed.
        """
        pass


class BaseEUParser(ABC):
    """Abstract Base Class for parsing European Union IT job sources."""
    
    @abstractmethod
    def parse_raw(self, raw_data: Union[str, bytes]) -> List[BOPage]:
        """
        Parses raw content into normalized BOPage domain models for downstream KeywordFilter scanning.
        
        Args:
            raw_data: A string or bytes block representing the raw response data.
            
        Returns:
            A list of BOPage objects.
        """
        pass


class BaseAIValidator(ABC):
    """Abstract Base Class for AI-powered announcement validation."""
    
    enabled: bool
    
    @abstractmethod
    def validate_batch(self, announcements: List[ParsedAnnouncement]) -> List[ParsedAnnouncement]:
        """
        Validates a batch of announcements and returns only the relevant ones.
        If validation is unavailable, returns the full list unchanged with a warning.
        """
        pass



