"""Tests for dep_inspector."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import respx
import httpx

from dep_inspector.inspector import DepInspector, InspectorOptions
from dep_inspector.parsers.base import (
    MissingOptionalDep,
    WrongContentType,
    detect_ecosystems,
)
from dep_inspector.network import _is_outdated, _version_key, _extract_severity, _extract_fixed
from dep_inspector.parsers.npm import _split_pnpm_key


def _inspect(path, **opts) -> object:
    return DepInspector(InspectorOptions(**opts)).inspect(path)


# ── Ecosystem detection ───────────────────────────────────────────────────────

class TestEcosystemDetection:
    def test_pypi_only(self, pypi_project):
        ecos = detect_ecosystems(pypi_project, None)
        assert [e for e, _ in ecos] == ["pypi"]

    def test_npm_only(self, npm_project):
        ecos = detect_ecosystems(npm_project, None)
        assert [e for e, _ in ecos] == ["npm"]

    def test_both_ecosystems(self, both_ecosystems_project):
        ecos = detect_ecosystems(both_ecosystems_project, None)
        eco_names = {e for e, _ in ecos}
        assert eco_names == {"pypi", "npm"}

    def test_empty_dir_returns_none(self, empty_dir):
        ecos = detect_ecosystems(empty_dir, None)
        assert ecos == []

    def test_ecosystem_hint_overrides(self, both_ecosystems_project):
        ecos = detect_ecosystems(both_ecosystems_project, "pypi")
        assert [e for e, _ in ecos] == ["pypi"]

    def test_single_file_path(self, pypi_project):
        ecos = detect_ecosystems(pypi_project / "pyproject.toml", None)
        assert [e for e, _ in ecos] == ["pypi"]


# ── PyPI parsers ──────────────────────────────────────────────────────────────

class TestPyPIParsers:
    def test_pyproject_pep621_dependencies(self, pypi_project):
        r = _inspect(pypi_project)
        e = r.ecosystems[0]
        names = {d.name for d in e.direct_deps}
        assert {"fastapi", "pydantic", "httpx", "pytest", "mypy"} <= names

    def test_dev_dependencies_marked(self, pypi_project):
        r = _inspect(pypi_project)
        by_name = {d.name: d for d in r.ecosystems[0].direct_deps}
        assert by_name["pytest"].dev is True
        assert by_name["fastapi"].dev is False

    def test_resolved_from_poetry_lock(self, pypi_project):
        r = _inspect(pypi_project)
        by_name = {d.name: d for d in r.ecosystems[0].direct_deps}
        assert by_name["fastapi"].resolved == "0.115.0"
        assert by_name["pydantic"].resolved == "2.9.0"

    def test_transitives(self, pypi_project):
        r = _inspect(pypi_project)
        e = r.ecosystems[0]
        names = {d.name for d in e.transitive_deps}
        assert "starlette" in names

    def test_starlette_parent_is_fastapi(self, pypi_project):
        r = _inspect(pypi_project)
        by_name = {d.name: d for d in r.ecosystems[0].transitive_deps}
        assert by_name["starlette"].parent == "fastapi"

    def test_requirements_txt_includes_followed(self, pypi_requirements_only):
        r = _inspect(pypi_requirements_only)
        names = {d.name for d in r.ecosystems[0].direct_deps}
        assert {"fastapi", "pydantic", "pytest", "mypy", "foobar", "django"} <= names

    def test_requirements_environment_markers_stripped(self, pypi_requirements_only):
        r = _inspect(pypi_requirements_only)
        django = next(d for d in r.ecosystems[0].direct_deps if d.name == "django")
        # The "; python_version" marker should NOT appear in declared
        if django.declared:
            assert ";" not in django.declared


# ── npm parsers ──────────────────────────────────────────────────────────────

class TestNPMParsers:
    def test_package_json_direct_deps(self, npm_project):
        r = _inspect(npm_project)
        names = {d.name for d in r.ecosystems[0].direct_deps}
        assert {"react", "lodash", "jest"} <= names

    def test_dev_dep_flagged(self, npm_project):
        r = _inspect(npm_project)
        by_name = {d.name: d for d in r.ecosystems[0].direct_deps}
        assert by_name["jest"].dev is True
        assert by_name["react"].dev is False

    def test_resolved_from_package_lock_v3(self, npm_project):
        r = _inspect(npm_project)
        by_name = {d.name: d for d in r.ecosystems[0].direct_deps}
        assert by_name["react"].resolved == "18.2.0"
        assert by_name["lodash"].resolved == "4.17.21"

    def test_transitives_found(self, npm_project):
        r = _inspect(npm_project)
        names = {d.name for d in r.ecosystems[0].transitive_deps}
        assert {"loose-envify", "js-tokens"} <= names

    def test_yarn_only_falls_back_to_declared(self, yarn_only_project):
        r = _inspect(yarn_only_project)
        e = r.ecosystems[0]
        # Resolved version should be None for react since yarn.lock isn't parsed
        react = next(d for d in e.direct_deps if d.name == "react")
        assert react.resolved is None
        # Note about yarn.lock should appear
        assert any("yarn.lock" in n for n in e.notes)


# ── Both ecosystems ───────────────────────────────────────────────────────────

class TestBothEcosystems:
    def test_both_summarized(self, both_ecosystems_project):
        r = _inspect(both_ecosystems_project)
        assert {e.ecosystem for e in r.ecosystems} == {"pypi", "npm"}


# ── Top transitives ───────────────────────────────────────────────────────────

class TestTopTransitives:
    def test_in_edges_counted(self, npm_project):
        r = _inspect(npm_project)
        top = dict(r.ecosystems[0].top_transitives)
        # loose-envify is required by react only in our fixture
        assert "loose-envify" in top

    def test_all_lists_full_transitives(self, npm_project):
        r = _inspect(npm_project, show_all_transitives=True)
        # fixture has loose-envify + js-tokens as transitives
        assert len(r.ecosystems[0].transitive_deps) == 2


# ── Renderers ────────────────────────────────────────────────────────────────

class TestRenderers:
    def test_markdown_has_sections(self, pypi_project):
        md = _inspect(pypi_project).to_markdown()
        assert "# Dependency Report:" in md
        assert "## Ecosystem: pypi" in md
        assert "### Direct Dependencies" in md

    def test_json_renderer(self, pypi_project):
        d = _inspect(pypi_project).to_json()
        json.dumps(d, default=str)
        assert d["ecosystems"][0]["ecosystem"] == "pypi"

    def test_text_renderer(self, pypi_project):
        t = _inspect(pypi_project).to_text()
        assert "fastapi" in t
        assert "[pypi]" in t


# ── Network: outdated ────────────────────────────────────────────────────────

class TestNetworkOutdated:
    @respx.mock
    def test_pypi_outdated_marked(self, pypi_project):
        respx.get("https://pypi.org/pypi/fastapi/json").respond(
            json={"info": {"version": "0.200.0"}}
        )
        respx.get("https://pypi.org/pypi/pydantic/json").respond(
            json={"info": {"version": "2.9.0"}}
        )
        # Catch-all for the rest so they don't hit real network
        respx.get(url__regex=r"https://pypi\.org/pypi/.*/json").respond(
            json={"info": {"version": "0.0.1"}}
        )
        r = _inspect(pypi_project, outdated=True)
        by_name = {d.name: d for d in r.ecosystems[0].direct_deps}
        assert by_name["fastapi"].latest == "0.200.0"
        assert by_name["fastapi"].outdated is True
        assert by_name["pydantic"].outdated is False

    @respx.mock
    def test_offline_degrades_gracefully(self, pypi_project):
        respx.get(url__regex=r".*").mock(side_effect=httpx.ConnectError("offline"))
        r = _inspect(pypi_project, outdated=True)
        assert any("lookups failed" in w for w in r.warnings)
        # No latest should have been set
        assert all(d.latest is None for d in r.ecosystems[0].direct_deps)


# ── Network: audit ───────────────────────────────────────────────────────────

class TestNetworkAudit:
    @respx.mock
    def test_osv_audit_attaches_advisory(self, pypi_project):
        respx.post("https://api.osv.dev/v1/querybatch").respond(
            json={
                "results": [
                    {"vulns": [{"id": "GHSA-fake-1234-xxxx"}]},
                    *({"vulns": []} for _ in range(20)),
                ]
            }
        )
        respx.get(url__regex=r"https://api\.osv\.dev/v1/vulns/.*").respond(
            json={
                "id": "GHSA-fake-1234-xxxx",
                "summary": "Fake vuln for testing",
                "aliases": ["CVE-2025-99999"],
                "severity": [{"score": 8.5}],
                "affected": [{"ranges": [{"events": [{"fixed": "0.116.0"}]}]}],
                "references": [{"type": "WEB", "url": "https://example.com/adv"}],
            }
        )
        r = _inspect(pypi_project, audit=True)
        fastapi = next(d for d in r.ecosystems[0].direct_deps if d.name == "fastapi")
        assert fastapi.advisories
        a = fastapi.advisories[0]
        assert a.id == "CVE-2025-99999"
        assert a.severity == "high"
        assert a.fixed_in == "0.116.0"


# ── Severity normalization ───────────────────────────────────────────────────

class TestSeverityNormalization:
    def test_high_at_threshold(self):
        assert _extract_severity({"severity": [{"score": 7.0}]}) == "high"

    def test_critical_at_threshold(self):
        assert _extract_severity({"severity": [{"score": 9.5}]}) == "critical"

    def test_medium(self):
        assert _extract_severity({"severity": [{"score": 5.0}]}) == "medium"

    def test_low(self):
        assert _extract_severity({"severity": [{"score": 2.0}]}) == "low"

    def test_unknown_when_no_score(self):
        assert _extract_severity({}) == "unknown"

    def test_database_specific_string(self):
        assert _extract_severity({"database_specific": {"severity": "HIGH"}}) == "high"


# ── Version comparison ──────────────────────────────────────────────────────

class TestVersionCompare:
    def test_simple(self):
        assert _is_outdated("1.0.0", "1.0.1") is True
        assert _is_outdated("2.0.0", "1.9.9") is False

    def test_equal(self):
        assert _is_outdated("1.0.0", "1.0.0") is False

    def test_v_prefix(self):
        assert _is_outdated("v1.0.0", "v1.0.1") is True

    def test_none(self):
        assert _is_outdated(None, "1.0") is None
        assert _is_outdated("1.0", None) is None


# ── Misc helpers ─────────────────────────────────────────────────────────────

class TestPnpmKeyParse:
    def test_simple(self):
        assert _split_pnpm_key("/react@18.2.0") == ("react", "18.2.0")

    def test_scoped(self):
        assert _split_pnpm_key("/@types/node@20.5.0") == ("@types/node", "20.5.0")

    def test_with_peer_suffix(self):
        assert _split_pnpm_key("/react-dom@18.2.0(react@18.2.0)") == ("react-dom", "18.2.0")


# ── CLI exit codes ───────────────────────────────────────────────────────────

class TestCLIExitCodes:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "dep_inspector.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, pypi_project):
        r = self._run(str(pypi_project))
        assert r.returncode == 0
        assert "# Dependency Report:" in r.stdout

    def test_one_on_missing_path(self):
        r = self._run("/no/such/path/anywhere")
        assert r.returncode == 1

    def test_three_when_no_manifest(self, empty_dir):
        r = self._run(str(empty_dir))
        assert r.returncode == 3

    def test_json_output_parses(self, pypi_project):
        r = self._run(str(pypi_project), "--format", "json")
        assert r.returncode == 0
        json.loads(r.stdout)


# ── MCP wrapper ─────────────────────────────────────────────────────────────

class TestMCPWrapper:
    def test_inspect_dependencies_returns_result(self, pypi_project):
        req = json.dumps({"name": "inspect_dependencies", "parameters": {"path": str(pypi_project)}})
        r = subprocess.run(
            [sys.executable, "-m", "dep_inspector.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        assert r.returncode == 0
        d = json.loads(r.stdout.strip())
        assert "result" in d
        assert "# Dependency Report:" in d["result"]

    def test_unknown_tool_returns_error(self):
        r = subprocess.run(
            [sys.executable, "-m", "dep_inspector.mcp_tool"],
            input='{"name":"nope","parameters":{}}\n', capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d


# ── Optional dep handling ───────────────────────────────────────────────────

class TestOptionalDeps:
    def test_pnpm_lock_without_pyyaml(self, monkeypatch, tmp_path):
        d = tmp_path / "pnpm"
        d.mkdir()
        (d / "package.json").write_text('{"dependencies": {"react": "^18"}}')
        (d / "pnpm-lock.yaml").write_text("packages: {/react@18.2.0: {}}\n")

        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("yaml not installed (simulated)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # Should NOT raise — should fall back to declared-only with a note
        r = _inspect(d)
        assert r.ecosystems[0].direct_deps
        assert any("pnpm" in n.lower() for n in r.ecosystems[0].notes)
