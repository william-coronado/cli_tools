"""Tests for codebase_indexer."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from codebase_indexer.indexer import CodebaseIndexer, CodebaseIndex
from codebase_indexer.walker import RepoWalker
from codebase_indexer.parsers.python_parser import PythonParser
from codebase_indexer.parsers.generic_parser import GenericParser


# ── Walker exclusions ─────────────────────────────────────────────────────────

def test_walker_excludes_git(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo).walk())
    names = [p.name for p in paths]
    assert "HEAD" not in names


def test_walker_excludes_pycache(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo).walk())
    names = [p.name for p in paths]
    assert "app.cpython-313.pyc" not in names


def test_walker_excludes_node_modules(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo).walk())
    names = [p.name for p in paths]
    assert "index.js" not in names


def test_walker_respects_gitignore(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo, respect_gitignore=True).walk())
    names = [p.name for p in paths]
    assert "debug.log" not in names


def test_walker_no_gitignore_flag(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo, respect_gitignore=False).walk())
    names = [p.name for p in paths]
    assert "debug.log" in names


def test_walker_respects_indexignore(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo).walk())
    names = [p.name for p in paths]
    assert "README.md" not in names


def test_walker_skips_binary(sample_python_repo):
    paths = list(RepoWalker(sample_python_repo).walk())
    names = [p.name for p in paths]
    assert "logo.png" not in names


def test_walker_skips_large_file(tmp_path):
    big = tmp_path / "huge.txt"
    big.write_bytes(b"x" * (600 * 1024))
    walker = RepoWalker(tmp_path, max_file_size_kb=500)
    paths = list(walker.walk())
    assert big not in paths
    assert any("huge.txt" in s for s in walker.skipped_files)


# ── Python parser — imports ───────────────────────────────────────────────────

def test_python_parser_imports(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    modules = {imp.module for imp in fi.imports}
    assert "__future__" in modules
    assert "os" in modules
    assert "pathlib" in modules


def test_python_parser_relative_import(tmp_path):
    (tmp_path / "mod.py").write_text("from . import sibling\nfrom ..pkg import util\n")
    parser = PythonParser()
    fi = parser.parse(tmp_path / "mod.py", tmp_path)
    relative = [imp for imp in fi.imports if imp.is_relative]
    assert len(relative) == 2
    # "from . import sibling" → module=".", names=["sibling"]
    assert relative[0].module == "."
    assert "sibling" in relative[0].names
    # "from ..pkg import util" → module="..pkg", names=["util"]
    assert relative[1].module == "..pkg"
    assert "util" in relative[1].names


# ── Python parser — functions ─────────────────────────────────────────────────

def test_python_parser_functions(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    names = [f.name for f in fi.functions]
    assert "add" in names
    assert "fetch" in names


def test_python_parser_function_signature(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    add = next(f for f in fi.functions if f.name == "add")
    assert "x: int" in add.signature
    assert "y: int" in add.signature
    assert "-> int" in add.signature


def test_python_parser_async_function(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    fetch = next(f for f in fi.functions if f.name == "fetch")
    assert fetch.is_async
    assert "async def" in fetch.signature


def test_python_parser_docstring(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    add = next(f for f in fi.functions if f.name == "add")
    assert add.docstring == "Return x + y."


def test_python_parser_includes_private_functions(sample_python_repo):
    # Private functions are included; callers decide what to render.
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    names = [f.name for f in fi.functions]
    assert "_private" in names


# ── Python parser — classes ───────────────────────────────────────────────────

def test_python_parser_classes(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    names = [c.name for c in fi.classes]
    assert "Animal" in names
    assert "Dog" in names


def test_python_parser_class_bases(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    dog = next(c for c in fi.classes if c.name == "Dog")
    assert "Animal" in dog.bases


def test_python_parser_methods(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    animal = next(c for c in fi.classes if c.name == "Animal")
    method_names = [m.name for m in animal.methods]
    assert "__init__" in method_names
    assert "speak" in method_names
    assert "classify" in method_names


def test_python_parser_static_method_decorator(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    animal = next(c for c in fi.classes if c.name == "Animal")
    classify = next(m for m in animal.methods if m.name == "classify")
    assert "@staticmethod" in classify.decorators


# ── Python parser — constants ─────────────────────────────────────────────────

def test_python_parser_constants(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "utils.py", sample_python_repo)
    assert "RETRY_LIMIT" in fi.constants
    assert "TIMEOUT_SECONDS" in fi.constants


def test_python_parser_annotated_constant(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "models.py", sample_python_repo)
    assert "MAX_SIZE" in fi.constants


# ── Python parser — error handling ───────────────────────────────────────────

def test_python_parser_syntax_error(sample_python_repo):
    parser = PythonParser()
    fi = parser.parse(sample_python_repo / "bad_syntax.py", sample_python_repo)
    assert fi.parse_error is not None
    assert "SyntaxError" in fi.parse_error
    assert fi.line_count > 0  # file still partially described


# ── Generic parser ────────────────────────────────────────────────────────────

def test_generic_parser_markdown(sample_python_repo):
    # README.md is excluded by .indexignore in sample_python_repo; use tmp
    tmp = Path(sample_python_repo).parent / "readme_test"
    tmp.mkdir(exist_ok=True)
    md = tmp / "README.md"
    md.write_text("# Hello\n\nWorld\n")
    parser = GenericParser()
    assert parser.can_parse(md)
    fi = parser.parse(md, tmp)
    assert fi.line_count == 3
    assert fi.language != ""
    assert fi.imports == []
    assert fi.functions == []
    assert fi.classes == []


def test_generic_parser_unknown_extension(tmp_path):
    f = tmp_path / "data.xyz"
    f.write_text("a\nb\nc\n")
    parser = GenericParser()
    assert not parser.can_parse(f)


# ── Full indexer ──────────────────────────────────────────────────────────────

def test_indexer_builds(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    assert isinstance(idx, CodebaseIndex)
    assert idx.total_files > 0


def test_indexer_contains_python_files(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    paths = [f.path for f in idx.files]
    assert any("models.py" in p for p in paths)
    assert any("utils.py" in p for p in paths)


def test_indexer_excludes_noise(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    paths = [f.path for f in idx.files]
    assert not any("__pycache__" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any("debug.log" in p for p in paths)


def test_indexer_syntax_error_file_included(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    bad = next((f for f in idx.files if "bad_syntax.py" in f.path), None)
    assert bad is not None
    assert bad.parse_error is not None


def test_indexer_language_stats(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    assert "python" in idx.languages


def test_indexer_skipped_files_large(tmp_path):
    big = tmp_path / "huge.dat"
    big.write_bytes(b"x" * (600 * 1024))
    (tmp_path / "small.py").write_text("x = 1\n")
    idx = CodebaseIndexer(tmp_path, max_file_size_kb=500, show_progress=False).build()
    assert any("huge.dat" in s for s in idx.skipped_files)


def test_indexer_root_not_exist():
    with pytest.raises(FileNotFoundError):
        CodebaseIndexer("/no/such/path/exists/xyz")


def test_indexer_root_is_file(tmp_path):
    f = tmp_path / "file.py"
    f.write_text("x = 1\n")
    with pytest.raises(ValueError):
        CodebaseIndexer(f)


def test_indexer_include_ext(sample_python_repo):
    idx = CodebaseIndexer(
        sample_python_repo, include_extensions=[".py"], show_progress=False
    ).build()
    for f in idx.files:
        assert f.path.endswith(".py")


def test_indexer_parallel_matches_sequential(sample_python_repo):
    idx1 = CodebaseIndexer(sample_python_repo, show_progress=False, workers=1).build()
    idx2 = CodebaseIndexer(sample_python_repo, show_progress=False, workers=4).build()
    assert [f.path for f in idx1.files] == [f.path for f in idx2.files]


# ── Renderer: to_markdown ─────────────────────────────────────────────────────

def test_to_markdown_contains_paths(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    md = idx.to_markdown()
    assert "models.py" in md
    assert "utils.py" in md


def test_to_markdown_contains_signatures(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    md = idx.to_markdown(detail="normal")
    assert "def add" in md or "add" in md


def test_to_markdown_low_smaller_than_normal(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    assert len(idx.to_markdown(detail="low")) < len(idx.to_markdown(detail="normal"))


def test_to_markdown_high_contains_constants(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    md = idx.to_markdown(detail="high")
    assert "RETRY_LIMIT" in md or "TIMEOUT_SECONDS" in md


# ── Renderer: to_outline ─────────────────────────────────────────────────────

def test_to_outline_compact(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    outline = idx.to_outline()
    assert "models.py" in outline
    assert "├──" in outline or "└──" in outline


def test_to_outline_shows_class_names(sample_python_repo):
    idx = CodebaseIndexer(sample_python_repo, show_progress=False).build()
    outline = idx.to_outline()
    assert "Animal" in outline


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_json_format(sample_python_repo, capsys):
    from codebase_indexer.cli import main
    rc = main([str(sample_python_repo), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "files" in data
    assert "total_files" in data


def test_cli_outline_format(sample_python_repo, capsys):
    from codebase_indexer.cli import main
    rc = main([str(sample_python_repo), "--format", "outline"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "models.py" in out


def test_cli_detail_low_smaller(sample_python_repo, capsys):
    from codebase_indexer.cli import main
    main([str(sample_python_repo), "--detail", "low"])
    low = capsys.readouterr().out
    main([str(sample_python_repo), "--detail", "normal"])
    normal = capsys.readouterr().out
    assert len(low) < len(normal)


def test_cli_nonexistent_path(capsys):
    from codebase_indexer.cli import main
    rc = main(["/no/such/path/xyz"])
    assert rc == 1


def test_cli_include_ext(sample_python_repo, capsys):
    from codebase_indexer.cli import main
    rc = main([str(sample_python_repo), "--format", "json", "--include-ext", ".py"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    for f in data["files"]:
        assert f["path"].endswith(".py")
