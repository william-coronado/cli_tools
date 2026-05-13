"""Tests for log_summarizer.

Fixtures are loaded from tests/fixtures/logs/.
The repetitive.log fixture is generated in memory — not checked in.
"""
from __future__ import annotations

import io
import json
import tracemalloc
from pathlib import Path

import pytest

from log_summarizer.summarizer import LogSummarizer, LogLine, TracebackBlock, MetricEntry
from log_summarizer.detectors.generic_detector import GenericDetector
from log_summarizer.detectors.pytest_detector import PytestDetector
from log_summarizer.detectors.python_logging_detector import PythonLoggingDetector
from log_summarizer.detectors.training_detector import TrainingDetector
from log_summarizer.detectors.json_detector import JSONDetector
from log_summarizer.detectors.webserver_detector import WebserverDetector
from log_summarizer.extractors.traceback_extractor import TracebackExtractor
from log_summarizer.deduplicator import Deduplicator

LOGS = Path(__file__).parent / "fixtures" / "logs"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _summarize(filename: str, **kwargs) -> object:
    return LogSummarizer(**kwargs).summarize(LOGS / filename)


def _lines_iter(text: str):
    return io.StringIO(text)


# ── Format detection ───────────────────────────────────────────────────────────

class TestFormatDetection:
    def test_pytest_fail_detected(self):
        r = _summarize("pytest_fail.log")
        assert r.log_format == "pytest"

    def test_pytest_pass_detected(self):
        r = _summarize("pytest_pass.log")
        assert r.log_format == "pytest"

    def test_python_logging_detected(self):
        r = _summarize("python_logging.log")
        assert r.log_format == "python_logging"

    def test_training_detected(self):
        r = _summarize("training.log")
        assert r.log_format == "training"

    def test_json_lines_detected(self):
        r = _summarize("json_lines.log")
        assert r.log_format == "json_lines"

    def test_nginx_detected(self):
        r = _summarize("nginx_access.log")
        assert r.log_format == "webserver"


# ── Pytest detector ───────────────────────────────────────────────────────────

class TestPytestDetector:
    def test_failures_extracted(self):
        r = _summarize("pytest_fail.log")
        # 3 unique FAILEDs; short-summary section repeats them — errors are never deduped
        assert len(r.errors) >= 3

    def test_error_messages_contain_test_name(self):
        r = _summarize("pytest_fail.log")
        messages = " ".join(e.message for e in r.errors)
        assert "test_subtract" in messages or "FAILED" in messages

    def test_detector_scores_high(self):
        d = PytestDetector()
        lines = (LOGS / "pytest_fail.log").read_text().splitlines()
        assert d.score(lines[:50]) > 0.3


# ── Python logging detector ───────────────────────────────────────────────────

class TestPythonLoggingDetector:
    def test_errors_extracted(self):
        r = _summarize("python_logging.log")
        assert len(r.errors) >= 2

    def test_warnings_extracted(self):
        r = _summarize("python_logging.log")
        assert len(r.warnings) >= 1

    def test_all_three_formats_parsed(self):
        d = PythonLoggingDetector()
        lines = [
            "2025-05-12 10:30:00,123 - myapp - ERROR - Standard format",
            "ERROR:myapp:Colon format",
            "[WARNING] Bracket format",
        ]
        results = [d.extract(l, i + 1) for i, l in enumerate(lines)]
        assert results[0].level == "ERROR"
        assert results[1].level == "ERROR"
        assert results[2].level == "WARNING"

    def test_level_to_category_mapping(self):
        d = PythonLoggingDetector()
        r = d.extract("2025-05-12 10:00:00,000 - app - WARNING - test", 1)
        assert r.category == "warning"
        r2 = d.extract("2025-05-12 10:00:00,000 - app - ERROR - test", 2)
        assert r2.category == "error"


# ── Training detector ─────────────────────────────────────────────────────────

class TestTrainingDetector:
    def test_metrics_extracted(self):
        r = _summarize("training.log")
        assert len(r.metrics) > 0

    def test_nan_flagged_as_error(self):
        r = _summarize("training.log")
        # NaN at epoch 11 should appear in errors
        error_messages = " ".join(e.message for e in r.errors)
        assert "nan" in error_messages.lower() or "Anomaly" in error_messages

    def test_metric_entries_have_names(self):
        d = TrainingDetector()
        entries = d.extract_metrics("Epoch 5/20 - loss=0.42 accuracy=0.88", 5)
        names = {e.name for e in entries}
        assert "loss" in names
        assert "accuracy" in names


# ── JSON detector ─────────────────────────────────────────────────────────────

class TestJSONDetector:
    def test_json_format_detected(self):
        r = _summarize("json_lines.log")
        assert r.log_format == "json_lines"

    def test_errors_extracted(self):
        r = _summarize("json_lines.log")
        assert len(r.errors) >= 2

    def test_severity_field_alias(self):
        d = JSONDetector()
        line = '{"severity": "WARNING", "msg": "test warning"}'
        result = d.extract(line, 1)
        assert result.category == "warning"

    def test_ts_field_alias(self):
        d = JSONDetector()
        line = '{"ts": "2025-01-01T00:00:00Z", "lvl": "ERROR", "text": "fail"}'
        result = d.extract(line, 1)
        assert result.level == "ERROR"
        assert result.timestamp == "2025-01-01T00:00:00Z"

    def test_score_high_for_ndjson(self):
        d = JSONDetector()
        lines = ['{"level": "INFO", "message": "ok"}'] * 10
        assert d.score(lines) > 0.8


# ── Webserver detector ────────────────────────────────────────────────────────

class TestWebserverDetector:
    def test_5xx_extracted_as_errors(self):
        r = _summarize("nginx_access.log")
        assert len(r.errors) >= 1
        statuses = [e.message for e in r.errors]
        assert any("500" in s or "503" in s for s in statuses)

    def test_4xx_extracted_as_warnings(self):
        r = _summarize("nginx_access.log")
        assert len(r.warnings) >= 1
        statuses = [w.message for w in r.warnings]
        assert any("404" in s or "403" in s for s in statuses)


# ── Traceback extractor ───────────────────────────────────────────────────────

class TestTracebackExtractor:
    TRACEBACK = """\
Traceback (most recent call last):
  File "app.py", line 42, in main
    run()
  File "runner.py", line 18, in run
    raise ValueError("bad input")
ValueError: bad input""".splitlines()

    def test_single_traceback_extracted(self):
        ext = TracebackExtractor()
        blocks = []
        for i, line in enumerate(self.TRACEBACK, 1):
            tb = ext.feed(line, i)
            if tb:
                blocks.append(tb)
        tb = ext.flush()
        if tb:
            blocks.append(tb)
        assert len(blocks) == 1
        assert blocks[0].exception_type == "ValueError"
        assert blocks[0].exception_message == "bad input"

    def test_frames_capped(self):
        ext = TracebackExtractor(max_frames=2)
        blocks = []
        for i, line in enumerate(self.TRACEBACK, 1):
            tb = ext.feed(line, i)
            if tb:
                blocks.append(tb)
        tb = ext.flush()
        if tb:
            blocks.append(tb)
        assert len(blocks) >= 1
        assert all(len(b.frames) <= 2 for b in blocks)

    def test_chained_exceptions(self):
        chained = """\
Traceback (most recent call last):
  File "a.py", line 1, in foo
    raise TypeError("original")
TypeError: original

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "b.py", line 5, in bar
    raise ValueError("wrapped")
ValueError: wrapped""".splitlines()
        ext = TracebackExtractor()
        blocks = []
        for i, line in enumerate(chained, 1):
            tb = ext.feed(line, i)
            if tb:
                blocks.append(tb)
        tb = ext.flush()
        if tb:
            blocks.append(tb)
        assert len(blocks) >= 1


# ── Deduplicator ──────────────────────────────────────────────────────────────

class TestDeduplicator:
    def _make_line(self, msg: str, n: int, category: str = "info") -> LogLine:
        return LogLine(
            line_number=n, raw=msg, level=None,
            timestamp=None, message=msg, category=category, source=None,
        )

    def test_suppresses_repeated_lines(self):
        dedup = Deduplicator(exact_threshold=3)
        results = []
        for i in range(10):
            r = dedup.process(self._make_line("same message", i))
            results.append(r)
        suppressed = sum(1 for r in results if r is None)
        assert suppressed > 0

    def test_never_suppresses_errors(self):
        dedup = Deduplicator(exact_threshold=1)
        results = []
        for i in range(5):
            r = dedup.process(self._make_line("same error", i, category="error"))
            results.append(r)
        assert all(r is not None for r in results)

    def test_dedup_groups_returned(self):
        dedup = Deduplicator(exact_threshold=2)
        for i in range(10):
            dedup.process(self._make_line("repeated line", i))
        groups = dedup.get_dedup_groups()
        assert len(groups) >= 1
        assert groups[0].count > 2

    def test_normalize_replaces_numbers(self):
        dedup = Deduplicator()
        n1 = dedup._normalize("retry 3 of 5")
        n2 = dedup._normalize("retry 7 of 10")
        assert n1 == n2

    def test_normalize_replaces_uuids(self):
        dedup = Deduplicator()
        n1 = dedup._normalize("request id=550e8400-e29b-41d4-a716-446655440000")
        n2 = dedup._normalize("request id=123e4567-e89b-12d3-a456-426614174000")
        assert n1 == n2


# ── Repetitive log (generated in memory) ─────────────────────────────────────

class TestRepetitiveLog:
    def _make_source(self, tmp_path: Path) -> Path:
        p = tmp_path / "repetitive.log"
        with open(p, "w") as f:
            for i in range(10_000):
                f.write("2025-05-12 10:00:00,000 - worker - INFO - Processing item\n")
            for i in range(5):
                f.write(f"2025-05-12 10:01:00,000 - worker - ERROR - Failed on item {i}\n")
        return p

    def test_suppressed_count_exceeds_shown(self, tmp_path):
        p = self._make_source(tmp_path)
        r = LogSummarizer().summarize(p)
        assert r.suppressed_line_count > r.total_lines // 2

    def test_errors_not_suppressed(self, tmp_path):
        p = self._make_source(tmp_path)
        r = LogSummarizer().summarize(p)
        assert len(r.errors) == 5

    def test_no_dedup_flag(self, tmp_path):
        p = self._make_source(tmp_path)
        r = LogSummarizer(use_dedup=False).summarize(p)
        assert r.suppressed_line_count == 0


# ── CLI flags ─────────────────────────────────────────────────────────────────

class TestCLI:
    def test_markdown_output(self):
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(LOGS / "pytest_fail.log")])
        assert rc == 0
        assert "## Errors" in buf.getvalue()

    def test_json_output(self):
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(LOGS / "python_logging.log"), "--format", "json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "errors" in data

    def test_errors_only_flag(self):
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(LOGS / "python_logging.log"), "--errors-only", "--format", "json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["warnings"] == []

    def test_format_hint(self):
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(LOGS / "pytest_fail.log"), "--format-hint", "pytest"])
        assert rc == 0

    def test_missing_file_exits_1(self):
        from log_summarizer.cli import main
        rc = main(["/no/such/file.log"])
        assert rc == 1

    def test_stdin_mode(self, tmp_path):
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        import sys as _sys
        content = "2025-05-12 10:00:00,000 - app - ERROR - Something failed\n"
        old_stdin = _sys.stdin
        _sys.stdin = _io.StringIO(content)
        buf = _io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = main(["-"])
        finally:
            _sys.stdin = old_stdin
        assert rc == 0

    def test_tail_flag(self, tmp_path):
        p = tmp_path / "big.log"
        lines = [f"2025-05-12 10:00:{i:02d},000 - app - INFO - Line {i}\n" for i in range(60)]
        lines[-1] = "2025-05-12 10:01:00,000 - app - ERROR - Last error\n"
        p.write_text("".join(lines))
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(p), "--tail", "10", "--format", "json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["total_lines"] <= 10

    def test_directory_mode(self, tmp_path):
        import shutil
        shutil.copy(LOGS / "python_logging.log", tmp_path / "app.log")
        from log_summarizer.cli import main
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            rc = main([str(tmp_path)])
        assert rc == 0
        assert "Log Summary" in buf.getvalue()


# ── Empty file ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.log"
        p.write_bytes(b"")
        r = LogSummarizer().summarize(p)
        assert r.total_lines == 0
        assert r.errors == []
        assert r.warnings == []

    def test_encoding_fallback(self, tmp_path):
        p = tmp_path / "latin1.log"
        p.write_bytes(b"2025-05-12 10:00:00,000 - app - ERROR - caf\xe9 error\n")
        r = LogSummarizer().summarize(p)
        assert r.total_lines == 1

    def test_to_markdown_omits_empty_sections(self, tmp_path):
        p = tmp_path / "info_only.log"
        p.write_text("2025-05-12 10:00:00,000 - app - INFO - All good\n")
        r = LogSummarizer().summarize(p)
        md = r.to_markdown()
        assert "## Errors" not in md
        assert "## Warnings" not in md

    def test_to_json_valid(self):
        r = LogSummarizer().summarize(LOGS / "json_lines.log")
        d = r.to_json()
        json.dumps(d)
        assert "errors" in d and "warnings" in d and "tracebacks" in d

    def test_traceback_in_log_file(self, tmp_path):
        p = tmp_path / "tb.log"
        content = (
            "2025-05-12 10:00:00,000 - app - ERROR - crash incoming\n"
            "Traceback (most recent call last):\n"
            '  File "app.py", line 10, in main\n'
            "    process()\n"
            "RuntimeError: something broke\n"
        )
        p.write_text(content)
        r = LogSummarizer().summarize(p)
        assert len(r.tracebacks) >= 1
        assert r.tracebacks[0].exception_type == "RuntimeError"
