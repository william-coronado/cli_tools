from __future__ import annotations

import itertools
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Iterator


@dataclass
class LogLine:
    line_number: int
    raw: str
    level: str | None
    timestamp: str | None
    message: str
    category: str   # "error"|"warning"|"traceback"|"metric"|"info"|"unknown"
    source: str | None


@dataclass
class TracebackBlock:
    start_line: int
    end_line: int
    exception_type: str | None
    exception_message: str | None
    frames: list[str]
    full_text: str


@dataclass
class MetricEntry:
    line_number: int
    name: str
    value: float | str
    step: int | None
    unit: str | None


@dataclass
class DedupGroup:
    representative: LogLine
    count: int
    first_line: int
    last_line: int


@dataclass
class SummaryResult:
    source: str
    log_format: str
    total_lines: int
    total_bytes: int
    parse_duration_ms: int
    errors: list[LogLine]
    warnings: list[LogLine]
    tracebacks: list[TracebackBlock]
    metrics: list[MetricEntry]
    dedup_groups: list[DedupGroup]
    key_events: list[LogLine]
    suppressed_line_count: int

    def to_markdown(self) -> str:
        from .renderer import Renderer
        return Renderer().render_markdown(self)

    def to_json(self) -> dict:
        from .renderer import Renderer
        return Renderer().render_json(self)

    def to_text(self) -> str:
        from .renderer import Renderer
        return Renderer().render_text(self)


class LogSummarizer:
    def __init__(
        self,
        max_errors: int = 50,
        max_warnings: int = 20,
        max_tracebacks: int = 10,
        max_metrics: int = 30,
        max_frames: int = 5,
        dedup_threshold: int = 3,
        chunk_size: int = 65_536,
        format_hint: str | None = None,
        errors_only: bool = False,
        use_dedup: bool = True,
    ) -> None:
        self.max_errors = max_errors
        self.max_warnings = max_warnings
        self.max_tracebacks = max_tracebacks
        self.max_metrics = max_metrics
        self.max_frames = max_frames
        self.dedup_threshold = dedup_threshold
        self.chunk_size = chunk_size
        self.format_hint = format_hint
        self.errors_only = errors_only
        self.use_dedup = use_dedup

    def summarize(self, source: str | Path | IO) -> SummaryResult:
        t0 = time.monotonic()

        if isinstance(source, (str, Path)):
            source_name = str(source)
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            total_bytes = path.stat().st_size
            line_iter = self._stream_lines(path)
        elif source is sys.stdin or hasattr(source, "read"):
            source_name = "stdin"
            total_bytes = 0
            line_iter = self._stream_lines(source)
        else:
            source_name = repr(source)
            total_bytes = 0
            line_iter = self._stream_lines(source)

        # Peek first 50 lines for format detection
        peeked: list[tuple[int, str]] = []
        rest_iter: Iterator[tuple[int, str]]

        for item in itertools.islice(line_iter, 50):
            peeked.append(item)

        # Chain peeked lines back with remainder
        rest_iter = itertools.chain(iter(peeked), line_iter)

        sample_lines = [raw for _, raw in peeked]
        detector = self._detect_format(sample_lines)

        from .extractors.traceback_extractor import TracebackExtractor
        from .deduplicator import Deduplicator

        tb_extractor = TracebackExtractor(max_frames=self.max_frames)
        dedup = Deduplicator(exact_threshold=self.dedup_threshold) if self.use_dedup else None

        errors: list[LogLine] = []
        warnings: list[LogLine] = []
        tracebacks: list[TracebackBlock] = []
        metrics: list[MetricEntry] = []
        key_events: list[LogLine] = []
        suppressed = 0
        total_lines = 0

        # Metric timeline for training logs
        metric_timeline: dict[str, list[tuple[int | None, float]]] = {}

        for line_number, raw in rest_iter:
            total_lines = line_number

            # Traceback extractor sees every raw line first
            tb = tb_extractor.feed(raw, line_number)
            if tb and len(tracebacks) < self.max_tracebacks:
                tracebacks.append(tb)

            parsed = detector.extract(raw, line_number)

            # Dedup (never suppresses errors/tracebacks)
            if dedup:
                result = dedup.process(parsed)
                if result is None:
                    suppressed += 1
                    continue
                parsed = result

            cat = parsed.category
            if cat == "error" and len(errors) < self.max_errors:
                errors.append(parsed)
            elif cat == "warning" and not self.errors_only and len(warnings) < self.max_warnings:
                warnings.append(parsed)
            elif cat == "metric" and not self.errors_only:
                # Collect from training detector
                from .detectors.training_detector import TrainingDetector
                if isinstance(detector, TrainingDetector):
                    for entry in detector.extract_metrics(raw, line_number):
                        try:
                            val = float(entry.value)
                        except (ValueError, TypeError):
                            val = None
                        if val is not None:
                            metric_timeline.setdefault(entry.name, []).append((entry.step, val))
                        if len(metrics) < self.max_metrics:
                            metrics.append(entry)

            if hasattr(detector, "is_key_event") and detector.is_key_event(parsed):
                key_events.append(parsed)

        # Flush any in-progress traceback
        final_tb = tb_extractor.flush()
        if final_tb and len(tracebacks) < self.max_tracebacks:
            tracebacks.append(final_tb)

        # Anomaly detection for training logs
        from .detectors.training_detector import TrainingDetector
        if isinstance(detector, TrainingDetector) and not self.errors_only:
            anomalies = detector.detect_anomalies(metrics)
            errors.extend(anomalies[: max(0, self.max_errors - len(errors))])

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        dedup_groups = dedup.get_dedup_groups() if dedup else []

        return SummaryResult(
            source=source_name,
            log_format=detector.FORMAT_NAME,
            total_lines=total_lines,
            total_bytes=total_bytes,
            parse_duration_ms=elapsed_ms,
            errors=errors,
            warnings=warnings,
            tracebacks=tracebacks,
            metrics=metrics,
            dedup_groups=dedup_groups,
            key_events=key_events,
            suppressed_line_count=suppressed,
        )

    def summarize_directory(
        self,
        dir_path: Path,
        pattern: str = "*.log",
        recursive: bool = False,
    ) -> list[SummaryResult]:
        glob_fn = dir_path.rglob if recursive else dir_path.glob
        files = sorted(glob_fn(pattern))
        if not files:
            print(f"warning: no files matching {pattern!r} in {dir_path}", file=sys.stderr)
        return [self.summarize(f) for f in files]

    def _detect_format(self, sample_lines: list[str]):
        from .detectors.pytest_detector import PytestDetector
        from .detectors.python_logging_detector import PythonLoggingDetector
        from .detectors.training_detector import TrainingDetector
        from .detectors.json_detector import JSONDetector
        from .detectors.webserver_detector import WebserverDetector
        from .detectors.generic_detector import GenericDetector

        if self.format_hint:
            hint_map = {
                "pytest": PytestDetector,
                "python": PythonLoggingDetector,
                "training": TrainingDetector,
                "json": JSONDetector,
                "webserver": WebserverDetector,
                "generic": GenericDetector,
            }
            cls = hint_map.get(self.format_hint)
            if cls:
                return cls()

        detectors = [
            PytestDetector(),
            PythonLoggingDetector(),
            TrainingDetector(),
            JSONDetector(),
            WebserverDetector(),
            GenericDetector(),
        ]
        best = max(detectors, key=lambda d: d.score(sample_lines))
        if best.score(sample_lines) < 0.3:
            return GenericDetector()
        return best

    def _stream_lines(self, source) -> Iterator[tuple[int, str]]:
        line_number = 0
        if isinstance(source, Path):
            try:
                with open(source, "rb") as f:
                    for raw_bytes in f:
                        line_number += 1
                        try:
                            line = raw_bytes.decode("utf-8", errors="replace")
                        except Exception:
                            line = raw_bytes.decode("latin-1", errors="replace")
                        yield line_number, line.rstrip("\n\r")
            except PermissionError as e:
                raise PermissionError(f"Cannot read file: {source}") from e
        else:
            # stdin or file-like
            for raw in source:
                line_number += 1
                if isinstance(raw, bytes):
                    line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
                else:
                    line = raw.rstrip("\n\r")
                yield line_number, line
