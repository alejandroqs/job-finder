import re
import unicodedata

def normalize_unicode(text: str) -> str:
    """Normalizes Unicode characters to NFC form."""
    return unicodedata.normalize("NFC", text)

def remove_boilerplate(text: str) -> str:
    """Removes standard BOP page headers/footers and boilerplate text."""
    lines = text.splitlines()
    cleaned_lines = []
    
    # Common boilerplate regex patterns
    boilerplate_patterns = [
        re.compile(r"bolet[ií]n\s+oficial\s+de\s+la\s+provincia\s+de\s+las\s+palmas", re.IGNORECASE),
        re.compile(r"n[oº\.\s]*\d+\s+-\s+\d+\s+de\s+[a-z]+\s+de\s+\d{4}", re.IGNORECASE), # e.g. "N.º 60 - 20 de mayo de 2026"
        re.compile(r"bop\s+las\s+palmas\s+-\s+n[oº\.\s]*\d+", re.IGNORECASE),
        re.compile(r"c[oó]digo\s+de\s+verificaci[oó]n\s+electr[oó]nica", re.IGNORECASE),
        re.compile(r"firmado\s+digitalmente\s+por", re.IGNORECASE),
    ]
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue
            
        is_boilerplate = False
        for pattern in boilerplate_patterns:
            if pattern.search(stripped):
                is_boilerplate = True
                break
                
        if not is_boilerplate:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines)

def remove_hyphenation(text: str) -> str:
    """
    Removes hyphenation at line breaks.
    Example: "informá-\ntico" -> "informático"
    """
    # Matches a word character, followed by a hyphen, then a newline (possibly with surrounding whitespace),
    # followed by another word character.
    # Note: re.UNICODE is default in Python 3, so \w matches letters with accents (á, é, etc.)
    pattern = r"(\w+)-\s*\n\s*(\w+)"
    return re.sub(pattern, r"\1\2", text)

def collapse_line_breaks(text: str) -> str:
    """
    Collapses redundant line breaks that split sentences.
    Preserves paragraph breaks (double newlines or more).
    """
    # Replace triple/quadruple newlines with double newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    # Standardize double newlines to a temporary token
    token = "___PARAGRAPH_BREAK___"
    text = text.replace("\n\n", token)
    
    # Replace remaining single newlines with a space
    text = text.replace("\n", " ")
    
    # Replace multiple spaces with a single space
    text = re.sub(r"[ \t]+", " ", text)
    
    # Restore paragraph breaks
    text = text.replace(token, "\n\n")
    
    # Trim leading/trailing spaces on each paragraph
    paragraphs = [p.strip() for p in text.split("\n\n")]
    return "\n\n".join([p for p in paragraphs if p])

def clean_text(text: str, lowercase: bool = False) -> str:
    """
    Applies the full text cleaning pipeline:
    1. Unicode normalization
    2. Boilerplate removal
    3. Hyphenation stripping
    4. Line break collapsing
    5. Convert to lowercase (optional)
    """
    if not text:
        return ""
        
    text = normalize_unicode(text)
    text = remove_boilerplate(text)
    text = remove_hyphenation(text)
    text = collapse_line_breaks(text)
    
    if lowercase:
        text = text.lower()
        
    return text
