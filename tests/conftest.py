"""Creates shared fixture directories programmatically."""
from __future__ import annotations
import pytest
from pathlib import Path


# ── PDF fixtures ───────────────────────────────────────────────────────────────

def _make_text_pdf(path: Path) -> None:
    """Generate a simple text-layer PDF using fpdf2."""
    try:
        from fpdf import FPDF  # type: ignore[import]
    except ImportError:
        pytest.skip("fpdf2 not installed — skipping PDF fixture generation")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, "Hello World\n\nThis is a test PDF with a text layer.\n")
    pdf.add_page()
    pdf.multi_cell(0, 10, "Page two content here.\n")
    pdf.output(str(path))


def _make_scanned_pdf(path: Path) -> None:
    """Generate an image-only (scanned) PDF: a white PNG embedded without text."""
    try:
        from fpdf import FPDF  # type: ignore[import]
        from PIL import Image as PILImage  # type: ignore[import]
        import io
    except ImportError:
        pytest.skip("fpdf2/Pillow not installed — skipping scanned PDF fixture")

    img_path = path.parent / "_blank_page.png"
    img = PILImage.new("RGB", (800, 1000), color=(255, 255, 255))
    img.save(str(img_path))

    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(img_path), x=0, y=0, w=210)
    pdf.output(str(path))
    img_path.unlink(missing_ok=True)


@pytest.fixture(scope="session")
def text_pdf(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("pdf_fixtures")
    p = d / "text_layer.pdf"
    _make_text_pdf(p)
    return p


@pytest.fixture(scope="session")
def scanned_pdf(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("pdf_scanned")
    p = d / "scanned.pdf"
    _make_scanned_pdf(p)
    return p


@pytest.fixture(scope="session")
def sample_tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("sample_tree")

    # Directories
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "node_modules" / "lodash").mkdir(parents=True)
    (root / "__pycache__").mkdir()

    # Source files
    (root / "src" / "main.py").write_text("def main(): pass\n")
    (root / "src" / "utils.py").write_text("def helper(): pass\n")
    (root / "tests" / "test_main.py").write_text("def test_main(): pass\n")
    (root / "README.md").write_text("# Sample\n")

    # Excluded dirs/files
    (root / "node_modules" / "lodash" / "index.js").write_text("module.exports = {};\n")
    (root / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"\x00" * 16)

    # Large binary file (2 MB zeros → binary + large flags)
    (root / "large_file.bin").write_bytes(b"\x00" * 2_097_152)

    # Empty file
    (root / "empty_file.txt").write_bytes(b"")

    # .gitignore
    (root / ".gitignore").write_text("*.log\n")

    # Should be excluded by .gitignore
    (root / "ignored.log").write_text("log line\n")

    return root


@pytest.fixture(scope="session")
def sample_python_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("sample_python_repo")

    # Noise directories that must be excluded
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\x00" * 32)
    (root / "node_modules" / "lodash").mkdir(parents=True)
    (root / "node_modules" / "lodash" / "index.js").write_text("module.exports = {};\n")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")

    # Package init
    (root / "__init__.py").write_text('"""Sample package."""\n')

    # Module with classes and methods
    (root / "models.py").write_text(
        '"""Data models."""\n'
        "from __future__ import annotations\n"
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "MAX_SIZE: int = 1024\n"
        "DEFAULT_NAME = 'unnamed'\n"
        "\n"
        "\n"
        "class Animal:\n"
        '    """Base animal class."""\n'
        "\n"
        "    def __init__(self, name: str, age: int = 0) -> None:\n"
        '        """Initialise the animal."""\n'
        "        self.name = name\n"
        "        self.age = age\n"
        "\n"
        "    def speak(self) -> str:\n"
        '        """Return the animal sound."""\n'
        "        return '...'\n"
        "\n"
        "    @staticmethod\n"
        "    def classify(weight: float) -> str:\n"
        '        """Classify by weight."""\n'
        "        return 'heavy' if weight > 100 else 'light'\n"
        "\n"
        "\n"
        "class Dog(Animal):\n"
        '    """Dog specialisation."""\n'
        "\n"
        "    def speak(self) -> str:\n"
        "        return 'woof'\n"
    )

    # Module with top-level functions and constants
    (root / "utils.py").write_text(
        '"""Utility helpers."""\n'
        "from typing import Optional\n"
        "\n"
        "RETRY_LIMIT = 3\n"
        "TIMEOUT_SECONDS = 30\n"
        "\n"
        "\n"
        "def add(x: int, y: int) -> int:\n"
        '    """Return x + y."""\n'
        "    return x + y\n"
        "\n"
        "\n"
        "async def fetch(url: str, timeout: int = TIMEOUT_SECONDS) -> Optional[str]:\n"
        '    """Fetch URL content."""\n'
        "    return None\n"
        "\n"
        "\n"
        "def _private(x: int) -> int:\n"
        "    return x * 2\n"
    )

    # Syntax-error file
    (root / "bad_syntax.py").write_text("def (\n    pass\n")

    # Binary file (minimal valid PNG header)
    png_header = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 100
    )
    (root / "logo.png").write_bytes(png_header)

    # Markdown file (generic parser)
    (root / "README.md").write_text("# Sample\n\nA test repository.\n")

    # .gitignore
    (root / ".gitignore").write_text("*.log\nbuild/\n")

    # File that should be ignored by .gitignore
    (root / "debug.log").write_text("some log\n")

    # .indexignore
    (root / ".indexignore").write_text("README.md\n")

    return root
