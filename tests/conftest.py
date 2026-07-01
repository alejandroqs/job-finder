import io
import pytest
from pathlib import Path

@pytest.fixture
def sample_pdf_path() -> Path:
    """Fixture that returns the path to the real bop_sample.pdf fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "bop_sample.pdf"
    if not fixture_path.exists():
        pytest.fail(f"Mock PDF fixture not found at expected location: {fixture_path}")
    return fixture_path

@pytest.fixture
def sample_pdf_stream(sample_pdf_path: Path) -> io.BytesIO:
    """Fixture that returns an in-memory BytesIO stream of the bop_sample.pdf fixture."""
    with open(sample_pdf_path, "rb") as f:
        return io.BytesIO(f.read())

@pytest.fixture
def sample_xml_path() -> Path:
    """Fixture that returns the path to the boc_sample.xml fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "boc_sample.xml"
    if not fixture_path.exists():
        pytest.fail(f"Mock XML fixture not found at expected location: {fixture_path}")
    return fixture_path

@pytest.fixture
def sample_xml_stream(sample_xml_path: Path) -> io.BytesIO:
    """Fixture that returns an in-memory BytesIO stream of the boc_sample.xml fixture."""
    with open(sample_xml_path, "rb") as f:
        return io.BytesIO(f.read())

@pytest.fixture
def sample_xml_boe_path() -> Path:
    """Fixture that returns the path to the boe_sample.xml fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "boe_sample.xml"
    if not fixture_path.exists():
        pytest.fail(f"Mock BOE XML fixture not found at expected location: {fixture_path}")
    return fixture_path

@pytest.fixture
def sample_xml_boe_stream(sample_xml_boe_path: Path) -> io.BytesIO:
    """Fixture that returns an in-memory BytesIO stream of the boe_sample.xml fixture."""
    with open(sample_xml_boe_path, "rb") as f:
        return io.BytesIO(f.read())
