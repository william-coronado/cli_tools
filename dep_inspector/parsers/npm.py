"""npm ecosystem parsers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..inspector import Dependency, EcosystemReport, InspectorOptions
from .base import MissingOptionalDep


def parse_npm(files: dict, opts: InspectorOptions) -> EcosystemReport:
    manifest = files.get("manifest")
    lockfile = files.get("lockfile")
    notes: list[str] = []

    declared: list[Dependency] = []
    if manifest:
        declared, mnotes = _parse_package_json(manifest)
        notes.extend(mnotes)

    if opts.direct_only:
        direct_only_deps = declared if opts.include_dev else [d for d in declared if not d.dev]
        return EcosystemReport(
            ecosystem="npm",
            manifest_path=str(manifest) if manifest else "",
            lockfile_path=str(lockfile) if lockfile else None,
            direct_deps=direct_only_deps,
            transitive_deps=[],
            transitive_count=0,
            notes=notes,
        )

    lock_entries: dict[str, dict[str, Any]] = {}
    if lockfile:
        if lockfile.name == "package-lock.json":
            lock_entries, lnotes = _parse_package_lock(lockfile)
            notes.extend(lnotes)
        elif lockfile.name == "pnpm-lock.yaml":
            try:
                lock_entries, lnotes = _parse_pnpm_lock(lockfile)
                notes.extend(lnotes)
            except MissingOptionalDep as e:
                notes.append(f"pnpm-lock.yaml not parsed: {e}")
        elif lockfile.name == "yarn.lock":
            notes.append("yarn.lock parser not implemented in v1 — falling back to package.json declared-only")

    declared_names = {d.name for d in declared}
    direct_deps: list[Dependency] = []
    transitive_deps: list[Dependency] = []
    seen_lock: set[str] = set()

    for d in declared:
        seen_lock.add(d.name)
        entry = lock_entries.get(d.name)
        if entry:
            d.resolved = entry.get("version")
            d.dev = d.dev or entry.get("dev", False)
            d.optional = d.optional or entry.get("optional", False)
        direct_deps.append(d)

    for name, entry in lock_entries.items():
        if name in seen_lock:
            continue
        transitive_deps.append(
            Dependency(
                name=name,
                resolved=entry.get("version"),
                direct=False,
                dev=entry.get("dev", False),
                optional=entry.get("optional", False),
                parent=entry.get("parent"),
            )
        )

    if not opts.include_dev:
        direct_deps = [d for d in direct_deps if not d.dev]
        transitive_deps = [d for d in transitive_deps if not d.dev]

    ranked: list[tuple[str, int]] = []
    for d in transitive_deps:
        entry = lock_entries.get(d.name, {})
        ranked.append((d.name, entry.get("in_edges", 0)))
    ranked.sort(key=lambda t: (-t[1], t[0]))
    top_transitives = ranked[: opts.top_transitives_k]

    return EcosystemReport(
        ecosystem="npm",
        manifest_path=str(manifest) if manifest else "",
        lockfile_path=str(lockfile) if lockfile else None,
        direct_deps=direct_deps,
        transitive_deps=transitive_deps,
        top_transitives=top_transitives,
        transitive_count=len(transitive_deps),
        notes=notes,
    )


# ── package.json ──────────────────────────────────────────────────────────────

def _parse_package_json(path: Path) -> tuple[list[Dependency], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    deps: list[Dependency] = []
    seen: set[str] = set()
    notes: list[str] = []

    for section, dev, optional in (
        ("dependencies", False, False),
        ("devDependencies", True, False),
        ("peerDependencies", False, False),
        ("optionalDependencies", False, True),
    ):
        block = data.get(section, {})
        if not isinstance(block, dict):
            continue
        for name, constraint in block.items():
            if name in seen:
                continue
            deps.append(
                Dependency(
                    name=name,
                    declared=str(constraint) if constraint is not None else None,
                    direct=True,
                    dev=dev,
                    optional=optional,
                )
            )
            seen.add(name)

    return deps, notes


# ── package-lock.json ─────────────────────────────────────────────────────────

def _parse_package_lock(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    out: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    version = data.get("lockfileVersion", 1)

    if version >= 2 and isinstance(data.get("packages"), dict):
        # v2/v3 shape: "packages" keyed by path ("" = root, "node_modules/X" = dep)
        for key, entry in data["packages"].items():
            if key == "" or not isinstance(entry, dict):
                continue
            # Extract package name: last "node_modules/" segment
            name = key.split("node_modules/")[-1] if "node_modules/" in key else key
            if not name:
                continue
            out[name] = {
                "version": entry.get("version"),
                "dev": entry.get("dev", False),
                "optional": entry.get("optional", False),
                "parent": None,
                "in_edges": 0,
            }
        # Best-effort parent tracking + in-edge counting from each entry's dependencies
        for key, entry in data["packages"].items():
            if not isinstance(entry, dict):
                continue
            parent_name = (
                key.split("node_modules/")[-1] if "node_modules/" in key else "<root>"
            )
            reqs = entry.get("dependencies") or {}
            if isinstance(reqs, dict):
                for child_name in reqs:
                    if child_name in out:
                        if out[child_name]["parent"] is None:
                            out[child_name]["parent"] = parent_name
                        out[child_name]["in_edges"] += 1
    elif isinstance(data.get("dependencies"), dict):
        # v1 shape: nested "dependencies" tree
        notes.append(f"package-lock.json v{version} format — partial parent tracking")
        _walk_v1_deps(data["dependencies"], out, parent=None)
    else:
        notes.append(f"Unrecognized package-lock.json shape (lockfileVersion={version})")

    return out, notes


def _walk_v1_deps(tree: dict, out: dict, parent: str | None) -> None:
    for name, entry in tree.items():
        if not isinstance(entry, dict):
            continue
        out[name] = {
            "version": entry.get("version"),
            "dev": entry.get("dev", False),
            "optional": entry.get("optional", False),
            "parent": parent,
            "in_edges": out.get(name, {}).get("in_edges", 0) + (1 if parent else 0),
        }
        sub = entry.get("dependencies")
        if isinstance(sub, dict):
            _walk_v1_deps(sub, out, parent=name)


# ── pnpm-lock.yaml ────────────────────────────────────────────────────────────

def _parse_pnpm_lock(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        raise MissingOptionalDep(
            "pnpm-lock.yaml support requires pyyaml. Install with: pip install pyyaml"
        )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    out: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    packages = data.get("packages", {})
    if not isinstance(packages, dict):
        return out, ["pnpm-lock.yaml has no 'packages' map"]

    for key, entry in packages.items():
        # key is "<name>@<version>" or "/<name>@<version>(...)" depending on pnpm version
        name, version = _split_pnpm_key(str(key))
        if not name:
            continue
        if not isinstance(entry, dict):
            entry = {}
        out[name] = {
            "version": version or entry.get("version"),
            "dev": bool(entry.get("dev", False)),
            "optional": bool(entry.get("optional", False)),
            "parent": None,
            "in_edges": 0,
        }
    # in-edge tally from each entry's "dependencies"
    for key, entry in packages.items():
        if not isinstance(entry, dict):
            continue
        parent_name, _ = _split_pnpm_key(str(key))
        sub = entry.get("dependencies") or {}
        if isinstance(sub, dict):
            for child_name in sub:
                if child_name in out:
                    if out[child_name]["parent"] is None:
                        out[child_name]["parent"] = parent_name
                    out[child_name]["in_edges"] += 1
    return out, notes


def _split_pnpm_key(key: str) -> tuple[str, str | None]:
    # Strip leading slash (pnpm v5/v6 style)
    if key.startswith("/"):
        key = key[1:]
    # Strip trailing "(peer_deps...)" suffix
    if "(" in key:
        key = key.split("(", 1)[0]
    # Split at last "@" — handles scoped names like "@scope/foo@1.2.3"
    if "@" in key[1:]:
        idx = key.rfind("@")
        return key[:idx], key[idx + 1:]
    return key, None
