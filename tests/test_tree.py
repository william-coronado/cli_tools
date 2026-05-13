"""Tests for smart_file_tree."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_file_tree.tree import build, TreeResult
from smart_file_tree.annotator import FileAnnotator
from smart_file_tree.renderer import Renderer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _names(result: TreeResult) -> list[str]:
    return [n.name for n in result.nodes]


def _file_names(result: TreeResult) -> list[str]:
    return [n.name for n in result.nodes if not n.is_dir]


def _dir_names(result: TreeResult) -> list[str]:
    return [n.name for n in result.nodes if n.is_dir]


# ── Exclusions ────────────────────────────────────────────────────────────────

def test_hard_excludes_node_modules(sample_tree):
    result = build(sample_tree)
    assert "node_modules" not in _dir_names(result)
    assert "index.js" not in _file_names(result)


def test_hard_excludes_pycache(sample_tree):
    result = build(sample_tree)
    assert "__pycache__" not in _dir_names(result)
    assert "main.cpython-311.pyc" not in _file_names(result)


def test_gitignore_respected(sample_tree):
    result = build(sample_tree)
    assert "ignored.log" not in _file_names(result)


def test_no_gitignore_flag(sample_tree):
    result = build(sample_tree, respect_gitignore=False)
    assert "ignored.log" in _file_names(result)


# ── File counts ───────────────────────────────────────────────────────────────

def test_file_count(sample_tree):
    result = build(sample_tree)
    # Default hides dotfiles: src/main.py, src/utils.py, tests/test_main.py,
    #   README.md, large_file.bin, empty_file.txt  (no .gitignore)
    assert result.total_files == 6


def test_show_hidden_includes_dotfiles(sample_tree):
    result_default = build(sample_tree)
    result_shown = build(sample_tree, show_hidden=True)
    names_default = {n.name for n in result_default.nodes if not n.is_dir}
    names_shown = {n.name for n in result_shown.nodes if not n.is_dir}
    assert ".gitignore" not in names_default
    assert ".gitignore" in names_shown
    assert result_shown.total_files > result_default.total_files


# ── Annotations ───────────────────────────────────────────────────────────────

def test_large_flag(sample_tree):
    result = build(sample_tree)
    large = [n for n in result.nodes if n.name == "large_file.bin"]
    assert large, "large_file.bin should be in tree"
    ann = large[0].annotation
    assert ann is not None
    assert "large" in ann.flags
    assert ann.is_large


def test_binary_flag(sample_tree):
    result = build(sample_tree)
    binary = [n for n in result.nodes if n.name == "large_file.bin"]
    assert binary
    assert "binary" in binary[0].annotation.flags


def test_empty_flag(sample_tree):
    result = build(sample_tree)
    empty = [n for n in result.nodes if n.name == "empty_file.txt"]
    assert empty, "empty_file.txt should be in tree"
    assert "empty" in empty[0].annotation.flags
    assert empty[0].annotation.is_empty


def test_language_detection(sample_tree):
    result = build(sample_tree)
    py_files = [n for n in result.nodes if n.name == "main.py"]
    assert py_files
    assert py_files[0].annotation.language == "Python"


# ── Depth ─────────────────────────────────────────────────────────────────────

def test_depth_1(sample_tree):
    result = build(sample_tree, max_depth=1)
    depths = [n.depth for n in result.nodes]
    assert max(depths) <= 1


def test_depth_1_dirs_have_child_count(sample_tree):
    result = build(sample_tree, max_depth=1)
    src = next((n for n in result.nodes if n.name == "src" and n.is_dir), None)
    assert src is not None
    # child_count is set when depth-limited
    assert src.child_count is not None


# ── Display filters ───────────────────────────────────────────────────────────

def test_dirs_only(sample_tree):
    result = build(sample_tree, dirs_only=True)
    assert all(n.is_dir for n in result.nodes)


def test_files_only(sample_tree):
    result = build(sample_tree, files_only=True)
    assert all(not n.is_dir for n in result.nodes)


# ── Focus ─────────────────────────────────────────────────────────────────────

def test_focus_subdir(sample_tree):
    result = build(sample_tree, focus_path=sample_tree / "src")
    names = _file_names(result)
    assert "main.py" in names
    assert "utils.py" in names
    assert "README.md" not in names


# ── Modified-after filter ────────────────────────────────────────────────────

def test_modified_after_future(sample_tree):
    # Filter to files modified after 'now' → should return nothing
    result = build(sample_tree, modified_after=time.time() + 3600)
    assert result.total_files == 0


def test_modified_after_past(sample_tree):
    # Filter to files modified after epoch → all non-hidden files visible
    result = build(sample_tree, modified_after=0.0)
    assert result.total_files == 6


# ── Extension filter ──────────────────────────────────────────────────────────

def test_include_ext_py(sample_tree):
    result = build(sample_tree, include_extensions=[".py"])
    for n in result.nodes:
        if not n.is_dir:
            assert n.path.suffix.lower() == ".py"


# ── Renderer formats ──────────────────────────────────────────────────────────

def test_format_compact(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    output = renderer.render(result, fmt="compact")
    # No tree-drawing characters
    assert "├──" not in output
    assert "└──" not in output


def test_format_json(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    raw = renderer.render(result, fmt="json")
    data = json.loads(raw)
    assert "nodes" in data
    assert "total_files" in data
    assert isinstance(data["nodes"], list)


def test_format_tree_characters(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    output = renderer.render(result, fmt="tree")
    assert "├──" in output or "└──" in output


# ── Summary block ─────────────────────────────────────────────────────────────

def test_summary_block(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    output = renderer.render(result, fmt="tree")
    assert "**Summary**" in output
    assert "Python" in output  # language count


def test_no_summary(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    output = renderer.render(result, fmt="tree", no_summary=True)
    assert "**Summary**" not in output


# ── Plain vs markdown ─────────────────────────────────────────────────────────

def test_no_ansi_in_plain(sample_tree):
    result = build(sample_tree)
    renderer = Renderer(use_ansi=False)
    output = renderer.render(result, fmt="tree")
    assert "\x1b[" not in output


# ── Annotator unit tests ──────────────────────────────────────────────────────

def test_human_size():
    a = FileAnnotator()
    assert a._human_size(0) == "0 B"
    assert a._human_size(512) == "512 B"
    assert a._human_size(1_024) == "1.0 KB"
    assert a._human_size(10_240) == "10.0 KB"
    assert a._human_size(1_048_576) == "1.0 MB"
    assert a._human_size(2_097_152) == "2.0 MB"


def test_modified_ago():
    now = time.time()
    a = FileAnnotator(now=now)
    assert a._modified_ago(now - 30) == "just now"
    assert a._modified_ago(now - 120) == "2m"
    assert a._modified_ago(now - 7200) == "2h"
    assert a._modified_ago(now - 86400 * 2) == "2d"
    assert a._modified_ago(now - 86400 * 10) == "1w"
    assert a._modified_ago(now - 86400 * 60) == "2mo"
    assert a._modified_ago(now - 86400 * 400) == "1y"


def test_is_binary(sample_tree):
    a = FileAnnotator()
    assert a._is_binary(sample_tree / "large_file.bin") is True
    assert a._is_binary(sample_tree / "src" / "main.py") is False


# ── CLI smoke test ────────────────────────────────────────────────────────────

def test_cli_smoke(sample_tree, capsys):
    from smart_file_tree.cli import main
    rc = main([str(sample_tree)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "main.py" in captured.out


def test_cli_json(sample_tree, capsys):
    from smart_file_tree.cli import main
    rc = main([str(sample_tree), "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_files"] == 6


def test_cli_show_hidden(sample_tree, capsys):
    from smart_file_tree.cli import main
    rc = main([str(sample_tree), "--show-hidden", "--format", "json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total_files"] == 7  # includes .gitignore


def test_cli_nonexistent_path(capsys):
    from smart_file_tree.cli import main
    rc = main(["/does/not/exist"])
    assert rc == 1


# ── Symlink handling ──────────────────────────────────────────────────────────

def test_relative_symlink_valid(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("hello")
    link = tmp_path / "link.txt"
    import os
    os.symlink("real.txt", link)   # relative target
    result = build(tmp_path, show_hidden=True)
    names = [n.name for n in result.nodes if not n.is_dir]
    assert any("link.txt" in n and "broken" not in n for n in names)


def test_relative_symlink_broken(tmp_path):
    link = tmp_path / "broken.txt"
    import os
    os.symlink("nonexistent.txt", link)  # relative, dangling
    result = build(tmp_path, show_hidden=True)
    names = [n.name for n in result.nodes if not n.is_dir]
    assert any("broken symlink" in n for n in names)
