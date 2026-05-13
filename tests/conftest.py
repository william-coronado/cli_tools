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


# ── data_summarizer fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def tiny_csv(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data_csv")
    p = d / "tiny.csv"
    rows = [
        "order_id,customer_email,amount_usd,order_date,region",
        "1,alice@example.com,42.10,2023-01-01,NA",
        "2,bob@example.com,199.00,2023-01-02,EU",
        "3,carol@example.com,12.50,2023-01-03,EU",
        "4,dave@example.com,524.30,2023-01-04,NA",
        "5,eve@example.com,89.00,2023-01-05,APAC",
        "6,frank@example.com,1024.00,2023-01-06,APAC",
        "7,grace@example.com,,2023-01-07,",
        "8,heidi@example.com,33.00,2023-01-08,EU",
        "9,ivan@example.com,17.50,2023-01-09,NA",
        "10,judy@example.com,76.50,2023-01-10,NA",
    ]
    p.write_text("\n".join(rows) + "\n")
    return p


@pytest.fixture(scope="session")
def messy_csv(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data_csv_messy")
    p = d / "messy.csv"
    rows = [
        "id,note,mixed",
        '1,"hello, world",42',
        '2,"she said ""hi""",13',
        "3,,",
        "4,plain text,",
        "5,end,fish",
    ]
    p.write_text("\n".join(rows) + "\n")
    return p


@pytest.fixture(scope="session")
def tiny_jsonl(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("data_jsonl")
    p = d / "tiny.jsonl"
    records = [
        {"id": 1, "name": "alice", "score": 0.92},
        {"id": 2, "name": "bob", "score": 0.75},
        {"id": 3, "name": "carol", "score": 0.81, "region": "EU"},
        {"id": 4, "name": "dave", "score": None, "region": "NA"},
        {"id": 5, "name": "eve", "score": 0.66, "region": "NA"},
    ]
    p.write_text("\n".join(_json.dumps(r) for r in records) + "\n")
    return p


@pytest.fixture(scope="session")
def nested_json(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("data_json_nested")
    p = d / "nested.json"
    payload = {
        "version": "1.2.3",
        "users": [{"id": 1}, {"id": 2}],
        "config": {"timeout_seconds": 30, "endpoints": ["a", "b"]},
        "active": True,
        "owner": None,
    }
    p.write_text(_json.dumps(payload, indent=2))
    return p


@pytest.fixture(scope="session")
def array_json(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("data_json_array")
    p = d / "array.json"
    rows = [
        {"id": 1, "name": "alice", "score": 0.92},
        {"id": 2, "name": "bob", "score": 0.75},
        {"id": 3, "name": "carol", "score": 0.81, "region": "EU"},
    ]
    p.write_text(_json.dumps(rows))
    return p


@pytest.fixture(scope="session")
def multi_table_sqlite(tmp_path_factory) -> Path:
    import sqlite3
    d = tmp_path_factory.mktemp("data_sqlite")
    p = d / "multi.sqlite"
    conn = sqlite3.connect(str(p))
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, active BOOLEAN)")
    cur.executemany(
        "INSERT INTO users VALUES (?,?,?)",
        [(1, "alice", 1), (2, "bob", 1), (3, "carol", 0)],
    )
    cur.execute("CREATE TABLE orders (id INTEGER, user_id INTEGER, amount REAL)")
    cur.executemany(
        "INSERT INTO orders VALUES (?,?,?)",
        [(i, (i % 3) + 1, i * 10.0) for i in range(1, 11)],
    )
    cur.execute("CREATE TABLE events (id INTEGER, kind TEXT)")
    cur.executemany(
        "INSERT INTO events VALUES (?,?)",
        [(i, ["a", "b", "c"][i % 3]) for i in range(1, 31)],
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture(scope="session")
def sample_data_dir(tmp_path_factory, tiny_csv, tiny_jsonl, multi_table_sqlite) -> Path:
    """A directory containing several data files, plus a node_modules folder to verify exclusions."""
    d = tmp_path_factory.mktemp("data_dir")
    import shutil
    for src in (tiny_csv, tiny_jsonl, multi_table_sqlite):
        shutil.copy(src, d / src.name)
    (d / "node_modules").mkdir()
    (d / "node_modules" / "bad.csv").write_text("a,b\n1,2\n")
    return d


# ── dep_inspector fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pypi_project(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("dep_pypi")
    (d / "pyproject.toml").write_text(
        '[project]\n'
        'name = "demo"\n'
        'version = "0.1.0"\n'
        'dependencies = ["fastapi>=0.100", "pydantic>=2", "httpx[http2]~=0.27"]\n'
        '\n'
        '[project.optional-dependencies]\n'
        'dev = ["pytest>=7", "mypy"]\n'
    )
    (d / "poetry.lock").write_text(
        '[[package]]\n'
        'name = "fastapi"\n'
        'version = "0.115.0"\n'
        'category = "main"\n'
        'optional = false\n'
        '\n'
        '[package.dependencies]\n'
        'starlette = ">=0.40,<0.46"\n'
        '\n'
        '[[package]]\n'
        'name = "pydantic"\n'
        'version = "2.9.0"\n'
        'category = "main"\n'
        'optional = false\n'
        '\n'
        '[[package]]\n'
        'name = "starlette"\n'
        'version = "0.40.0"\n'
        'category = "main"\n'
        'optional = false\n'
        '\n'
        '[[package]]\n'
        'name = "httpx"\n'
        'version = "0.27.2"\n'
        'category = "main"\n'
        'optional = false\n'
        '\n'
        '[[package]]\n'
        'name = "pytest"\n'
        'version = "7.4.0"\n'
        'category = "dev"\n'
        'optional = false\n'
        '\n'
        '[[package]]\n'
        'name = "mypy"\n'
        'version = "1.5.0"\n'
        'category = "dev"\n'
        'optional = false\n'
    )
    return d


@pytest.fixture(scope="session")
def pypi_requirements_only(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("dep_pypi_req")
    (d / "requirements.txt").write_text(
        "# main deps\n"
        "fastapi>=0.100\n"
        "pydantic\n"
        "httpx[http2]~=0.27\n"
        "-r dev-requirements.txt\n"
        "git+https://github.com/foo/bar.git@v1#egg=foobar\n"
        "django ; python_version >= '3.10'\n"
    )
    (d / "dev-requirements.txt").write_text(
        "pytest>=7\n"
        "mypy\n"
    )
    return d


@pytest.fixture(scope="session")
def npm_project(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("dep_npm")
    (d / "package.json").write_text(_json.dumps({
        "name": "demo",
        "version": "1.0.0",
        "dependencies": {"react": "^18.2", "lodash": "^4.17"},
        "devDependencies": {"jest": "^29"},
    }))
    (d / "package-lock.json").write_text(_json.dumps({
        "name": "demo",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "demo", "version": "1.0.0"},
            "node_modules/react": {
                "version": "18.2.0",
                "dependencies": {"loose-envify": "^1.1.0"},
            },
            "node_modules/loose-envify": {
                "version": "1.4.0",
                "dependencies": {"js-tokens": "^4.0.0"},
            },
            "node_modules/js-tokens": {"version": "4.0.0"},
            "node_modules/lodash": {"version": "4.17.21"},
            "node_modules/jest": {"version": "29.7.0", "dev": True},
        },
    }))
    return d


@pytest.fixture(scope="session")
def both_ecosystems_project(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("dep_both")
    (d / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["requests"]\n'
    )
    (d / "package.json").write_text(_json.dumps({
        "name": "demo", "dependencies": {"react": "^18"}
    }))
    return d


@pytest.fixture(scope="session")
def yarn_only_project(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("dep_yarn")
    (d / "package.json").write_text(_json.dumps({
        "name": "demo", "dependencies": {"react": "^18"}
    }))
    (d / "yarn.lock").write_text("# yarn.lock\n# placeholder\n")
    return d


@pytest.fixture(scope="session")
def empty_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("dep_empty")


# ── notebook_extractor fixtures ───────────────────────────────────────────────

def _make_png_b64() -> str:
    """Return base64 of a minimal 40×30 PNG."""
    import base64, struct, zlib
    w, h = 40, 30
    ihdr_data = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    row = b'\x00' + b'\xff\x00\x00' * w
    idat_data = zlib.compress(row * h)
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data) & 0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr_data) + chunk(b'IDAT', idat_data) + chunk(b'IEND', b'')
    return base64.b64encode(raw).decode()


def _make_notebook(cells_spec: list[dict]) -> dict:
    """Build a minimal .ipynb dict from a simplified spec."""
    import json as _json
    cells = []
    for i, spec in enumerate(cells_spec):
        ctype = spec.get("type", "code")
        src = spec.get("source", "")
        tags = spec.get("tags", [])
        outputs = spec.get("outputs", [])
        cell: dict = {
            "cell_type": ctype,
            "metadata": {"tags": tags},
            "source": [src] if isinstance(src, str) else src,
        }
        if ctype == "code":
            cell["execution_count"] = i + 1
            cell["outputs"] = outputs
        cells.append(cell)
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10.0"},
        },
        "cells": cells,
    }


@pytest.fixture(scope="session")
def tiny_notebook(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("nb_tiny")
    p = d / "tiny.ipynb"
    png_b64 = _make_png_b64()
    stream_200 = [f"step {i}\n" for i in range(200)]
    nb = _make_notebook([
        {"type": "markdown", "source": "# Title\n\nIntro paragraph."},
        {"type": "code", "source": "import pandas as pd\ndf = pd.read_csv('f.csv')\ndf.head()",
         "outputs": [{"output_type": "execute_result", "execution_count": 1,
                      "data": {"text/plain": ["   a  b\n0  1  2\n"]}, "metadata": {}}]},
        {"type": "code", "source": "plt.plot()",
         "outputs": [{"output_type": "display_data",
                      "data": {"image/png": png_b64}, "metadata": {}}]},
        {"type": "code", "source": "for i in range(200): print(f'step {i}')",
         "outputs": [{"output_type": "stream", "name": "stdout", "text": stream_200}]},
        {"type": "markdown", "source": "## Results\n\nDone."},
    ])
    p.write_text(_json.dumps(nb))
    return p


@pytest.fixture(scope="session")
def tagged_notebook(tmp_path_factory) -> Path:
    import json as _json
    d = tmp_path_factory.mktemp("nb_tagged")
    p = d / "tagged.ipynb"
    nb = _make_notebook([
        {"type": "code", "tags": ["setup"], "source": "import os"},
        {"type": "code", "tags": ["training"], "source": "model.fit()"},
        {"type": "code", "tags": ["viz"], "source": "plt.show()"},
        {"type": "markdown", "tags": [], "source": "## Notes"},
    ])
    p.write_text(_json.dumps(nb))
    return p


@pytest.fixture(scope="session")
def notebook_dir(tmp_path_factory, tiny_notebook, tagged_notebook) -> Path:
    import shutil
    d = tmp_path_factory.mktemp("nb_dir")
    shutil.copy(tiny_notebook, d / tiny_notebook.name)
    shutil.copy(tagged_notebook, d / tagged_notebook.name)
    # node_modules should be excluded by walker
    (d / "node_modules").mkdir()
    shutil.copy(tiny_notebook, d / "node_modules" / "excluded.ipynb")
    return d
