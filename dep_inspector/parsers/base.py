from __future__ import annotations

from pathlib import Path


class MissingOptionalDep(RuntimeError):
    """Raised when a parser requires an optional dep that isn't installed."""


class WrongContentType(RuntimeError):
    """Raised when no supported manifest is found."""


# Files that trigger ecosystem detection at a project root
PYPI_MANIFESTS = ("pyproject.toml", "requirements.txt", "Pipfile")
PYPI_LOCKFILES = ("poetry.lock", "uv.lock", "Pipfile.lock")
NPM_MANIFESTS = ("package.json",)
NPM_LOCKFILES = ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")


def _files_in(root: Path, names: tuple[str, ...]) -> list[Path]:
    return [root / n for n in names if (root / n).is_file()]


def _detect_pypi(root: Path) -> dict | None:
    manifests = _files_in(root, PYPI_MANIFESTS)
    lockfiles = _files_in(root, PYPI_LOCKFILES)
    if not manifests and not lockfiles:
        return None
    # Manifest preference: pyproject.toml > requirements.txt > Pipfile
    pref = {"pyproject.toml": 0, "requirements.txt": 1, "Pipfile": 2}
    primary_manifest = (
        sorted(manifests, key=lambda p: pref.get(p.name, 99))[0]
        if manifests else None
    )
    # Lockfile preference: poetry.lock > uv.lock > Pipfile.lock
    lock_pref = {"poetry.lock": 0, "uv.lock": 1, "Pipfile.lock": 2}
    primary_lockfile = (
        sorted(lockfiles, key=lambda p: lock_pref.get(p.name, 99))[0]
        if lockfiles else None
    )
    return {"manifest": primary_manifest, "lockfile": primary_lockfile}


def _detect_npm(root: Path) -> dict | None:
    manifests = _files_in(root, NPM_MANIFESTS)
    lockfiles = _files_in(root, NPM_LOCKFILES)
    if not manifests and not lockfiles:
        return None
    # Lockfile preference: package-lock.json > pnpm-lock.yaml > yarn.lock
    lock_pref = {"package-lock.json": 0, "pnpm-lock.yaml": 1, "yarn.lock": 2}
    primary_lockfile = (
        sorted(lockfiles, key=lambda p: lock_pref.get(p.name, 99))[0]
        if lockfiles else None
    )
    primary_manifest = manifests[0] if manifests else None
    return {"manifest": primary_manifest, "lockfile": primary_lockfile}


def _ecosystem_for_file(path: Path) -> str | None:
    name = path.name
    if name in PYPI_MANIFESTS or name in PYPI_LOCKFILES:
        return "pypi"
    if name in NPM_MANIFESTS or name in NPM_LOCKFILES:
        return "npm"
    return None


def detect_ecosystems(path: Path, ecosystem_hint: str | None) -> list[tuple[str, dict]]:
    """Return list of (ecosystem_name, files_dict) pairs.

    `path` can be a directory (scan for known files) or a file (use as primary).
    `ecosystem_hint` overrides auto-detection.
    """
    out: list[tuple[str, dict]] = []

    if path.is_file():
        eco = ecosystem_hint or _ecosystem_for_file(path)
        if not eco:
            return []
        if eco == "pypi" and path.name in PYPI_LOCKFILES:
            out.append((eco, {"manifest": None, "lockfile": path}))
        elif eco == "pypi":
            out.append((eco, {"manifest": path, "lockfile": None}))
        elif eco == "npm" and path.name in NPM_LOCKFILES:
            out.append((eco, {"manifest": None, "lockfile": path}))
        elif eco == "npm":
            out.append((eco, {"manifest": path, "lockfile": None}))
        return out

    # Directory scan
    if ecosystem_hint in (None, "pypi"):
        files = _detect_pypi(path)
        if files:
            out.append(("pypi", files))
    if ecosystem_hint in (None, "npm"):
        files = _detect_npm(path)
        if files:
            out.append(("npm", files))
    return out
