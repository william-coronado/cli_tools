"""HTTP layer for outdated checks (PyPI/npm) and OSV vulnerability audit."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable

import httpx

from .inspector import Advisory, Dependency, EcosystemReport, InspectorOptions


_OSV_ENDPOINT = "https://api.osv.dev/v1/querybatch"
_PYPI_LATEST = "https://pypi.org/pypi/{name}/json"
_NPM_LATEST = "https://registry.npmjs.org/{name}/latest"

# OSV's ecosystem labels differ from ours
_OSV_ECOSYSTEM_MAP = {"pypi": "PyPI", "npm": "npm"}

_SEVERITY_ORDER = ["unknown", "low", "medium", "high", "critical"]


def enrich_with_network(
    reports: list[EcosystemReport], opts: InspectorOptions,
) -> list[str]:
    """Mutate reports with `.latest`, `.outdated`, and `.advisories` data.

    Returns a list of top-level warnings to surface (network failures, etc.).
    """
    warnings: list[str] = []

    if not (opts.outdated or opts.audit):
        return warnings

    with httpx.Client(timeout=opts.network_timeout_s) as client:
        for report in reports:
            deps = report.direct_deps + report.transitive_deps
            if opts.outdated:
                w = _enrich_outdated(client, report.ecosystem, deps, opts)
                warnings.extend(w)
            if opts.audit:
                w = _enrich_audit(client, report.ecosystem, deps, opts)
                warnings.extend(w)
    return warnings


# ── Outdated ──────────────────────────────────────────────────────────────────

def _enrich_outdated(
    client: httpx.Client, ecosystem: str, deps: list[Dependency], opts: InspectorOptions,
) -> list[str]:
    if ecosystem == "pypi":
        url_fn = lambda name: _PYPI_LATEST.format(name=name)
        extract_fn = _extract_pypi_latest
    elif ecosystem == "npm":
        url_fn = lambda name: _NPM_LATEST.format(name=name)
        extract_fn = _extract_npm_latest
    else:
        return []

    targets = [d for d in deps if d.name and d.resolved]
    if not targets:
        return []

    failures = 0
    with ThreadPoolExecutor(max_workers=opts.network_workers) as pool:
        futures = {
            pool.submit(_fetch_latest, client, url_fn(d.name), extract_fn): d
            for d in targets
        }
        for fut in as_completed(futures):
            d = futures[fut]
            try:
                latest = fut.result()
            except Exception:
                failures += 1
                latest = None
            if latest:
                d.latest = latest
                d.outdated = _is_outdated(d.resolved, latest)

    warnings: list[str] = []
    if failures:
        warnings.append(
            f"{ecosystem}: {failures}/{len(targets)} latest-version lookups failed"
        )
    return warnings


def _fetch_latest(client: httpx.Client, url: str, extract):
    resp = client.get(url, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return extract(resp.json())


def _extract_pypi_latest(data) -> str | None:
    return (data or {}).get("info", {}).get("version")


def _extract_npm_latest(data) -> str | None:
    return (data or {}).get("version")


def _is_outdated(resolved: str | None, latest: str | None) -> bool | None:
    if not resolved or not latest:
        return None
    if resolved == latest:
        return False
    try:
        from packaging.version import InvalidVersion, Version
        try:
            return Version(resolved.lstrip("v")) < Version(latest.lstrip("v"))
        except InvalidVersion:
            pass  # non-PEP440 string (e.g. odd semver build metadata)
    except ImportError:
        pass
    # Heuristic fallback: compare as version tuples (split on . and -)
    a = _version_key(resolved)
    b = _version_key(latest)
    return a < b


def _version_key(v: str) -> tuple:
    """Best-effort comparable key for version strings."""
    out = []
    # Strip leading 'v'
    if v.startswith("v"):
        v = v[1:]
    # Split off pre-release suffix (anything after '-')
    main, _, _ = v.partition("-")
    for chunk in main.split("."):
        try:
            out.append((0, int(chunk)))
        except ValueError:
            # mixed alphanumeric; sort lexically as fallback
            out.append((1, chunk))
    return tuple(out)


# ── OSV audit ─────────────────────────────────────────────────────────────────

def _enrich_audit(
    client: httpx.Client, ecosystem: str, deps: list[Dependency], opts: InspectorOptions,
) -> list[str]:
    osv_eco = _OSV_ECOSYSTEM_MAP.get(ecosystem)
    if not osv_eco:
        return []

    targets = [d for d in deps if d.name and d.resolved]
    if not targets:
        return []

    queries = [
        {"package": {"name": d.name, "ecosystem": osv_eco}, "version": d.resolved}
        for d in targets
    ]

    try:
        resp = client.post(_OSV_ENDPOINT, json={"queries": queries})
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        return [f"{ecosystem}: OSV audit failed ({e!s}); continuing without audit data"]

    # Pair results back with deps; OSV returns parallel array.
    # /querybatch returns lean entries (id only) — collect every id first so
    # the detail lookups run once per unique vuln, in parallel.
    dep_vuln_ids: list[tuple[Dependency, list[str]]] = []
    all_ids: set[str] = set()
    for d, result in zip(targets, results):
        vulns = result.get("vulns") or []
        if not vulns:
            continue
        ids = [v["id"] for v in vulns]
        dep_vuln_ids.append((d, ids))
        all_ids.update(ids)

    details = _fetch_osv_details(client, sorted(all_ids), opts.network_workers)

    for d, ids in dep_vuln_ids:
        ids_seen: set[str] = set()
        for vid in ids:
            adv = _normalize_advisory(details[vid], d.resolved)
            if adv.id in ids_seen:
                continue
            ids_seen.add(adv.id)
            if opts.severity_filter and not _passes_severity(adv.severity, opts.severity_filter):
                continue
            d.advisories.append(adv)

    return []


def _fetch_osv_details(
    client: httpx.Client, ids: Iterable[str], workers: int = 16,
) -> dict[str, dict]:
    """Look up vulnerability details by ID, in parallel. Keyed by OSV id."""
    ids = list(ids)
    out: dict[str, dict] = {}
    if not ids:
        return out

    def fetch(vid: str) -> dict:
        resp = client.get(f"https://api.osv.dev/v1/vulns/{vid}")
        resp.raise_for_status()
        return resp.json()

    with ThreadPoolExecutor(max_workers=min(workers, len(ids))) as pool:
        futures = {pool.submit(fetch, vid): vid for vid in ids}
        for fut in as_completed(futures):
            vid = futures[fut]
            try:
                out[vid] = fut.result()
            except Exception:
                # Synthesize minimal record so caller still sees the id
                out[vid] = {"id": vid, "summary": "(details unavailable)"}
    return out


def _normalize_advisory(vuln: dict, resolved: str | None) -> Advisory:
    aliases = vuln.get("aliases", []) or []
    # Prefer CVE > GHSA > original id
    primary_id = vuln.get("id", "?")
    for a in aliases:
        if a.startswith("CVE-"):
            primary_id = a
            break

    severity = _extract_severity(vuln)
    fixed_in = _extract_fixed(vuln, resolved)
    summary = vuln.get("summary") or (vuln.get("details", "")[:200].strip()) or "(no summary)"
    url = None
    refs = vuln.get("references") or []
    for r in refs:
        if r.get("type") in ("WEB", "ADVISORY"):
            url = r.get("url")
            break

    return Advisory(
        id=primary_id,
        severity=severity,
        summary=summary,
        fixed_in=fixed_in,
        url=url,
    )


def _extract_severity(vuln: dict) -> str:
    """Extract the highest CVSS-equivalent severity from an OSV vuln entry."""
    score: float | None = None
    # Top-level severity[] list with CVSS scores
    for entry in vuln.get("severity", []) or []:
        s = _cvss_score(entry)
        if s is not None and (score is None or s > score):
            score = s
    # Per-affected severity[]
    for aff in vuln.get("affected", []) or []:
        for entry in aff.get("severity", []) or []:
            s = _cvss_score(entry)
            if s is not None and (score is None or s > score):
                score = s
    # database_specific.severity (string like "HIGH"; GHSA uses "MODERATE")
    db_sev = vuln.get("database_specific", {}).get("severity")
    if score is None and isinstance(db_sev, str):
        label = {"moderate": "medium"}.get(db_sev.lower(), db_sev.lower())
        return label if label in _SEVERITY_ORDER else "unknown"

    if score is None:
        return "unknown"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    return "low"


def _cvss_score(entry: dict) -> float | None:
    if not isinstance(entry, dict):
        return None
    score = entry.get("score")
    if score is None:
        return None
    if isinstance(score, (int, float)):
        return float(score)
    if isinstance(score, str):
        # Vector strings: "CVSS:3.1/AV:N/AC:L/..." — extract numeric if present
        # OSV often includes raw score directly though; fall back to parsing
        try:
            return float(score)
        except ValueError:
            return None
    return None


def _extract_fixed(vuln: dict, resolved: str | None) -> str | None:
    """Find the first 'fixed' version listed in affected ranges."""
    for aff in vuln.get("affected", []) or []:
        for rng in aff.get("ranges", []) or []:
            for ev in rng.get("events", []) or []:
                fixed = ev.get("fixed")
                if fixed:
                    return fixed
    return None


def _passes_severity(severity: str, allow_list: list[str]) -> bool:
    return severity.lower() in {s.lower() for s in allow_list}
