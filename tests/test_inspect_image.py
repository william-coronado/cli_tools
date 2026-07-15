"""Tests for inspect_image."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from inspect_image.inspector import (
    MissingOptionalDep,
    WrongContentType,
    inspect_image,
)


@pytest.fixture(scope="session")
def tiny_png(tmp_path_factory) -> Path:
    Image = pytest.importorskip("PIL.Image")
    d = tmp_path_factory.mktemp("inspect_image")
    p = d / "tiny.png"
    Image.new("RGB", (16, 9), color=(255, 0, 0)).save(p, format="PNG")
    return p


@pytest.fixture(scope="session")
def not_an_image(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("inspect_image_bad")
    p = d / "not_an_image.png"
    p.write_text("this is definitely not a png\n")
    return p


class TestInspectImage:
    def test_dimensions_and_mode(self, tiny_png):
        info = inspect_image(tiny_png)
        assert (info.width, info.height) == (16, 9)
        assert info.mode == "RGB"
        assert info.format == "PNG"

    def test_file_size_matches_disk(self, tiny_png):
        info = inspect_image(tiny_png)
        assert info.file_size_bytes == tiny_png.stat().st_size

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            inspect_image(tmp_path / "nope.png")

    def test_non_image_raises_wrong_content_type(self, not_an_image):
        with pytest.raises(WrongContentType):
            inspect_image(not_an_image)


class TestRenderers:
    def test_markdown_has_dimensions(self, tiny_png):
        info = inspect_image(tiny_png)
        md = info.to_markdown()
        assert "16 x 9" in md
        assert "PNG" in md

    def test_json_renderer_valid(self, tiny_png):
        info = inspect_image(tiny_png)
        data = info.to_json()
        assert data["width"] == 16
        assert data["height"] == 9

    def test_text_renderer(self, tiny_png):
        info = inspect_image(tiny_png)
        assert "16x9" in info.to_text()


class TestOptionalDep:
    def test_missing_pillow_raises(self, monkeypatch, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n")
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("no PIL")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(MissingOptionalDep):
            inspect_image(p)


class TestExitCodes:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "inspect_image.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, tiny_png):
        r = self._run(str(tiny_png))
        assert r.returncode == 0
        assert "16 x 9" in r.stdout

    def test_one_on_missing_file(self, tmp_path):
        r = self._run(str(tmp_path / "nope.png"))
        assert r.returncode == 1

    def test_three_on_wrong_content_type(self, not_an_image):
        r = self._run(str(not_an_image))
        assert r.returncode == 3

    def test_format_json_valid(self, tiny_png):
        r = self._run(str(tiny_png), "--format", "json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["width"] == 16


class TestMCPWrapper:
    def test_inspect_image_returns_result(self, tiny_png):
        from inspect_image.mcp_tool import _handle
        out = _handle({"path": str(tiny_png)})
        assert "16 x 9" in out

    def test_missing_path_raises(self):
        from inspect_image.mcp_tool import _handle
        with pytest.raises(FileNotFoundError):
            _handle({"path": "/nonexistent/path/x.png"})
