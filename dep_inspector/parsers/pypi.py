"""PyPI ecosystem parsers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..inspector import Dependency, EcosystemReport, InspectorOptions

try:
    import tomllib  # py 3.11+
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


# PEP 508 name: alnum + . _ -
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*?)\s*$")


def parse_pypi(files: dict, opts: InspectorOptions) -> EcosystemReport:
    manifest = files.get("manifest")
    lockfile = files.get("lockfile")

    declared: list[Dependency] = []
    notes: list[str] = []

    if manifest:
        if manifest.name == "pyproject.toml":
            declared, project_notes = _parse_pyproject(manifest, opts)
            notes.extend(project_notes)
        elif manifest.name == "requirements.txt":
            declared, req_notes = _parse_requirements(manifest, depth=0)
            notes.extend(req_notes)
        elif manifest.name == "Pipfile":
            notes.append("Pipfile declared-parser not implemented; ignoring")

    if opts.direct_only:
        return EcosystemReport(
            ecosystem="pypi",
            manifest_path=str(manifest) if manifest else "",
            lockfile_path=str(lockfile) if lockfile else None,
            direct_deps=_filter_dev(declared, opts),
            transitive_deps=[],
            top_transitives=[],
            transitive_count=0,
            notes=notes,
        )

    # Resolve via lockfile
    lock_entries: dict[str, dict[str, Any]] = {}
    if lockfile:
        if lockfile.name == "poetry.lock":
            lock_entries, lock_notes = _parse_poetry_lock(lockfile)
            notes.extend(lock_notes)
        elif lockfile.name == "uv.lock":
            lock_entries, lock_notes = _parse_uv_lock(lockfile)
            notes.extend(lock_notes)
        elif lockfile.name == "Pipfile.lock":
            lock_entries, lock_notes = _parse_pipfile_lock(lockfile)
            notes.extend(lock_notes)

    declared_names = {_norm(d.name) for d in declared}
    direct_deps: list[Dependency] = []
    transitive_deps: list[Dependency] = []
    seen_lock: set[str] = set()

    # Merge declared with lockfile resolved
    for d in declared:
        key = _norm(d.name)
        seen_lock.add(key)
        entry = lock_entries.get(key)
        if entry:
            d.resolved = entry.get("version")
            d.dev = d.dev or entry.get("dev", False)
            d.optional = d.optional or entry.get("optional", False)
        direct_deps.append(d)

    # Anything else in the lockfile is transitive
    for key, entry in lock_entries.items():
        if key in seen_lock:
            continue
        transitive_deps.append(
            Dependency(
                name=entry.get("name", key),
                resolved=entry.get("version"),
                direct=False,
                dev=entry.get("dev", False),
                optional=entry.get("optional", False),
                parent=entry.get("parent"),
            )
        )

    direct_deps = _filter_dev(direct_deps, opts)
    if not opts.include_dev:
        transitive_deps = [d for d in transitive_deps if not d.dev]

    top_transitives = _top_transitives(transitive_deps, lock_entries, opts.top_transitives_k)

    return EcosystemReport(
        ecosystem="pypi",
        manifest_path=str(manifest) if manifest else "",
        lockfile_path=str(lockfile) if lockfile else None,
        direct_deps=direct_deps,
        transitive_deps=transitive_deps,
        top_transitives=top_transitives,
        transitive_count=len(transitive_deps),
        notes=notes,
    )


def _top_transitives(
    deps: list[Dependency], lock_entries: dict, k: int,
) -> list[tuple[str, int]]:
    ranked = []
    for d in deps:
        entry = lock_entries.get(_norm(d.name), {})
        in_edges = entry.get("in_edges", 0)
        ranked.append((d.name, in_edges))
    ranked.sort(key=lambda t: (-t[1], t[0]))
    return ranked[:k]


def _norm(name: str) -> str:
    """PEP 503 normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _filter_dev(deps: list[Dependency], opts: InspectorOptions) -> list[Dependency]:
    if opts.include_dev:
        return deps
    return [d for d in deps if not d.dev]


# ── requirements.txt ──────────────────────────────────────────────────────────

def _parse_requirements(path: Path, depth: int) -> tuple[list[Dependency], list[str]]:
    deps: list[Dependency] = []
    notes: list[str] = []
    seen_names: set[str] = set()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ValueError(f"Could not read {path}: {e}")

    base_dir = path.parent
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments
        if " #" in line:
            line = line.split(" #", 1)[0].rstrip()
        # -r includes
        if line.startswith("-r ") or line.startswith("--requirement "):
            include = line.split(" ", 1)[1].strip()
            if depth < 1:
                sub = base_dir / include
                if sub.exists():
                    sub_deps, sub_notes = _parse_requirements(sub, depth=depth + 1)
                    notes.append(f"Followed -r include: {include}")
                    notes.extend(sub_notes)
                    for d in sub_deps:
                        n = _norm(d.name)
                        if n not in seen_names:
                            deps.append(d)
                            seen_names.add(n)
                else:
                    notes.append(f"Missing -r include (not followed): {include}")
            else:
                notes.append(f"Skipped nested -r include (depth>1): {include}")
            continue
        # Skip pip options
        if line.startswith("-"):
            continue
        # Strip environment markers (anything after ';')
        if ";" in line:
            line = line.split(";", 1)[0].rstrip()
        # Editable installs / VCS URLs
        if line.startswith(("git+", "hg+", "svn+", "bzr+")) or "://" in line:
            egg = _egg_from_url(line)
            if egg:
                if _norm(egg) not in seen_names:
                    deps.append(Dependency(name=egg, declared=line, direct=True))
                    seen_names.add(_norm(egg))
            continue
        m = _REQ_NAME.match(line)
        if not m:
            continue
        name = m.group(1)
        rest = (m.group(2) or "") + (m.group(3) or "")
        rest = rest.strip()
        if _norm(name) in seen_names:
            continue
        deps.append(Dependency(name=name, declared=rest or None, direct=True))
        seen_names.add(_norm(name))

    return deps, notes


def _egg_from_url(line: str) -> str | None:
    if "#egg=" in line:
        return line.split("#egg=", 1)[1].split("&", 1)[0]
    return None


# ── pyproject.toml ────────────────────────────────────────────────────────────

def _parse_pyproject(path: Path, opts: InspectorOptions) -> tuple[list[Dependency], list[str]]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    notes: list[str] = []
    deps: list[Dependency] = []
    seen: set[str] = set()

    # PEP 621 [project]
    project = data.get("project", {})
    if isinstance(project, dict):
        for spec in project.get("dependencies", []):
            d = _parse_pep508(spec, dev=False)
            if d and _norm(d.name) not in seen:
                deps.append(d)
                seen.add(_norm(d.name))
        opt_deps = project.get("optional-dependencies", {})
        if isinstance(opt_deps, dict):
            for group_name, group in opt_deps.items():
                is_dev = group_name in ("dev", "test", "tests", "lint", "docs")
                for spec in group:
                    d = _parse_pep508(spec, dev=is_dev, optional=True)
                    if d and _norm(d.name) not in seen:
                        deps.append(d)
                        seen.add(_norm(d.name))

    # Poetry [tool.poetry.dependencies]
    poetry = data.get("tool", {}).get("poetry", {})
    if isinstance(poetry, dict):
        prod = poetry.get("dependencies", {})
        if isinstance(prod, dict):
            for name, val in prod.items():
                if name.lower() == "python":
                    continue
                if _norm(name) in seen:
                    continue
                deps.append(Dependency(name=name, declared=_poetry_constraint(val), direct=True))
                seen.add(_norm(name))
        # Old-style dev-dependencies
        dev = poetry.get("dev-dependencies", {})
        if isinstance(dev, dict):
            for name, val in dev.items():
                if _norm(name) in seen:
                    continue
                deps.append(Dependency(
                    name=name, declared=_poetry_constraint(val), direct=True, dev=True,
                ))
                seen.add(_norm(name))
        # New-style groups
        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for group_name, group_data in groups.items():
                is_dev = group_name in ("dev", "test", "tests", "lint", "docs")
                if not isinstance(group_data, dict):
                    continue
                gdeps = group_data.get("dependencies", {})
                if not isinstance(gdeps, dict):
                    continue
                for name, val in gdeps.items():
                    if _norm(name) in seen:
                        continue
                    deps.append(Dependency(
                        name=name, declared=_poetry_constraint(val),
                        direct=True, dev=is_dev,
                    ))
                    seen.add(_norm(name))

    return deps, notes


def _poetry_constraint(val: Any) -> str | None:
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        # {version="^1.0", optional=true, extras=[...]}
        return val.get("version")
    return None


def _parse_pep508(spec: str, dev: bool = False, optional: bool = False) -> Dependency | None:
    spec = spec.strip()
    if ";" in spec:
        spec = spec.split(";", 1)[0].rstrip()
    m = _REQ_NAME.match(spec)
    if not m:
        return None
    name = m.group(1)
    rest = (m.group(2) or "") + (m.group(3) or "")
    return Dependency(
        name=name, declared=rest.strip() or None,
        direct=True, dev=dev, optional=optional,
    )


# ── poetry.lock ───────────────────────────────────────────────────────────────

def _parse_poetry_lock(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    out: dict[str, dict[str, Any]] = {}
    in_edges: dict[str, int] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        key = _norm(name)
        if not key:
            continue
        category = pkg.get("category", "main")
        out[key] = {
            "name": name,
            "version": pkg.get("version"),
            "dev": category in ("dev", "test"),
            "optional": pkg.get("optional", False),
            "parent": None,
            "in_edges": 0,
        }
    for pkg in data.get("package", []):
        sub = pkg.get("dependencies", {})
        if not isinstance(sub, dict):
            continue
        for child_name in sub:
            child_key = _norm(child_name)
            if child_key in out:
                if out[child_key]["parent"] is None:
                    out[child_key]["parent"] = pkg.get("name")
                out[child_key]["in_edges"] += 1
    return out, []


# ── uv.lock ───────────────────────────────────────────────────────────────────

def _parse_uv_lock(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    out: dict[str, dict[str, Any]] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        key = _norm(name)
        if not key:
            continue
        out[key] = {
            "name": name,
            "version": pkg.get("version"),
            "dev": False,
            "optional": False,
            "parent": None,
            "in_edges": 0,
        }
    for pkg in data.get("package", []):
        sub = pkg.get("dependencies", [])
        if not isinstance(sub, list):
            continue
        for entry in sub:
            if not isinstance(entry, dict):
                continue
            child_key = _norm(entry.get("name", ""))
            if child_key in out:
                if out[child_key]["parent"] is None:
                    out[child_key]["parent"] = pkg.get("name")
                out[child_key]["in_edges"] += 1
    return out, []


# ── Pipfile.lock ──────────────────────────────────────────────────────────────

def _parse_pipfile_lock(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    out: dict[str, dict[str, Any]] = {}
    for section, is_dev in (("default", False), ("develop", True)):
        block = data.get(section, {})
        if not isinstance(block, dict):
            continue
        for name, val in block.items():
            key = _norm(name)
            version = None
            if isinstance(val, dict):
                v = val.get("version", "")
                if isinstance(v, str) and v.startswith("=="):
                    version = v[2:]
                else:
                    version = v or None
            out[key] = {
                "name": name,
                "version": version,
                "dev": is_dev,
                "optional": False,
                "parent": None,
                "in_edges": 0,
            }
    return out, []
