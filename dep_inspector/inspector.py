from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Advisory:
    id: str
    severity: str            # "critical" | "high" | "medium" | "low" | "unknown"
    summary: str
    fixed_in: str | None
    url: str | None


@dataclass
class Dependency:
    name: str
    declared: str | None = None
    resolved: str | None = None
    direct: bool = False
    dev: bool = False
    optional: bool = False
    parent: str | None = None
    latest: str | None = None
    outdated: bool | None = None
    advisories: list[Advisory] = field(default_factory=list)


@dataclass
class EcosystemReport:
    ecosystem: str           # "pypi" | "npm"
    manifest_path: str
    lockfile_path: str | None
    direct_deps: list[Dependency] = field(default_factory=list)
    transitive_deps: list[Dependency] = field(default_factory=list)
    top_transitives: list[tuple[str, int]] = field(default_factory=list)
    transitive_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class DepReport:
    source: str
    ecosystems: list[EcosystemReport] = field(default_factory=list)
    audit_requested: bool = False
    outdated_requested: bool = False
    show_all_transitives: bool = False
    parse_duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer().render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import Renderer
        return Renderer().render_json(self)

    def to_text(self) -> str:
        from .renderer import Renderer
        return Renderer().render_text(self)


@dataclass
class InspectorOptions:
    direct_only: bool = False
    outdated: bool = False
    audit: bool = False
    ecosystem: str | None = None
    show_all_transitives: bool = False
    top_transitives_k: int = 10
    network_timeout_s: float = 10.0
    network_workers: int = 16
    include_dev: bool = True
    severity_filter: list[str] | None = None


class DepInspector:
    def __init__(self, options: InspectorOptions | None = None) -> None:
        self.options = options or InspectorOptions()

    def inspect(self, path: str | Path) -> DepReport:
        from .parsers.base import detect_ecosystems

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        t0 = time.monotonic()
        ecosystems = detect_ecosystems(path, self.options.ecosystem)
        if not ecosystems:
            from .parsers.base import WrongContentType
            raise WrongContentType(
                f"No supported manifest found at {path}. "
                f"Expected: pyproject.toml, requirements.txt, package.json, or a lockfile."
            )

        warnings: list[str] = []
        reports: list[EcosystemReport] = []
        for ecosystem, files in ecosystems:
            if ecosystem == "pypi":
                from .parsers.pypi import parse_pypi
                report = parse_pypi(files, self.options)
            elif ecosystem == "npm":
                from .parsers.npm import parse_npm
                report = parse_npm(files, self.options)
            else:
                continue
            reports.append(report)

        if self.options.outdated or self.options.audit:
            from .network import enrich_with_network
            net_warnings = enrich_with_network(reports, self.options)
            warnings.extend(net_warnings)

        return DepReport(
            source=str(path),
            ecosystems=reports,
            audit_requested=self.options.audit,
            outdated_requested=self.options.outdated,
            show_all_transitives=self.options.show_all_transitives,
            parse_duration_ms=int((time.monotonic() - t0) * 1000),
            warnings=warnings,
        )
