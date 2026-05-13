"""Tests for data_summarizer."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from data_summarizer.summarizer import DataSummarizer, SummarizerOptions
from data_summarizer.readers.base import (
    MissingOptionalDep,
    WrongContentType,
    _content_sniff,
    _hint_for_path,
    dispatch_reader,
)


def _summarize(path, **opts) -> object:
    return DataSummarizer(SummarizerOptions(**opts)).summarize(path)


# ── Format detection ───────────────────────────────────────────────────────────

class TestFormatDetection:
    def test_csv_by_extension(self, tiny_csv):
        assert _hint_for_path(tiny_csv) == "csv"

    def test_jsonl_by_extension(self, tiny_jsonl):
        assert _hint_for_path(tiny_jsonl) == "jsonl"

    def test_sqlite_by_extension(self, multi_table_sqlite):
        assert _hint_for_path(multi_table_sqlite) == "sqlite"

    def test_content_sniff_csv(self, tmp_path):
        p = tmp_path / "data.unknown"
        p.write_text("a,b,c\n1,2,3\n")
        assert _content_sniff(p) == "csv"

    def test_content_sniff_json_object(self, tmp_path):
        p = tmp_path / "data.unknown"
        p.write_text('{"a": 1}')
        assert _content_sniff(p) == "json"

    def test_content_sniff_sqlite_magic(self, multi_table_sqlite):
        # Rename to .unknown and sniff
        import shutil
        target = Path(str(multi_table_sqlite).replace(".sqlite", ".unknown"))
        shutil.copy(multi_table_sqlite, target)
        try:
            assert _content_sniff(target) == "sqlite"
        finally:
            target.unlink()

    def test_dispatch_unknown_raises(self, tmp_path):
        p = tmp_path / "mystery.bin"
        p.write_bytes(b"\x00\x01\x02\x03 just binary")
        with pytest.raises(ValueError):
            dispatch_reader(p, None)

    def test_format_hint_overrides_extension(self, tiny_csv):
        r = _summarize(tiny_csv, format_hint="csv")
        assert r.file_format == "csv"


# ── CSV reader ────────────────────────────────────────────────────────────────

class TestCSVReader:
    def test_schema_correct(self, tiny_csv):
        r = _summarize(tiny_csv)
        t = r.tables[0]
        names = [c.name for c in t.columns]
        assert names == ["order_id", "customer_email", "amount_usd", "order_date", "region"]

    def test_dtype_inference(self, tiny_csv):
        r = _summarize(tiny_csv)
        by_name = {c.name: c.dtype for c in r.tables[0].columns}
        assert by_name["order_id"] == "int"
        assert by_name["customer_email"] == "string"
        assert by_name["amount_usd"] == "float"
        assert by_name["order_date"] == "datetime"
        assert by_name["region"] == "string"

    def test_nulls_counted(self, tiny_csv):
        r = _summarize(tiny_csv)
        by_name = {c.name: c.null_count for c in r.tables[0].columns}
        assert by_name["amount_usd"] == 1
        assert by_name["region"] == 1
        assert by_name["order_id"] == 0

    def test_row_count(self, tiny_csv):
        r = _summarize(tiny_csv)
        assert r.tables[0].row_count == 10

    def test_messy_csv_parses(self, messy_csv):
        r = _summarize(messy_csv)
        t = r.tables[0]
        assert t.row_count == 5
        assert t.columns[1].name == "note"


# ── JSONL reader ──────────────────────────────────────────────────────────────

class TestJSONLReader:
    def test_schema_unions_keys(self, tiny_jsonl):
        r = _summarize(tiny_jsonl)
        names = [c.name for c in r.tables[0].columns]
        assert "id" in names and "region" in names

    def test_missing_keys_become_nulls(self, tiny_jsonl):
        r = _summarize(tiny_jsonl)
        by_name = {c.name: c for c in r.tables[0].columns}
        # region first appears on record 3 → records 1,2 = nulls (2 total)
        assert by_name["region"].null_count == 2


# ── JSON reader ───────────────────────────────────────────────────────────────

class TestJSONReader:
    def test_array_of_records_path(self, array_json):
        r = _summarize(array_json)
        assert r.tables and not r.structures
        assert r.tables[0].row_count == 3

    def test_nested_json_path(self, nested_json):
        r = _summarize(nested_json)
        assert not r.tables and r.structures
        s = r.structures[0]
        keys = {k["key"] for k in s.top_level_keys}
        assert {"version", "users", "config", "active", "owner"} <= keys


# ── SQLite reader ─────────────────────────────────────────────────────────────

class TestSQLiteReader:
    def test_multi_table(self, multi_table_sqlite):
        r = _summarize(multi_table_sqlite)
        names = {t.name for t in r.tables}
        assert {"users", "orders", "events"} <= names

    def test_table_filter(self, multi_table_sqlite):
        r = _summarize(multi_table_sqlite, tables=["users"])
        assert [t.name for t in r.tables] == ["users"]

    def test_row_counts(self, multi_table_sqlite):
        r = _summarize(multi_table_sqlite)
        by_name = {t.name: t.row_count for t in r.tables}
        assert by_name == {"users": 3, "orders": 10, "events": 30}


# ── Statistics ────────────────────────────────────────────────────────────────

class TestStatistics:
    def test_numeric_min_max_mean(self, tiny_csv):
        r = _summarize(tiny_csv)
        amount = next(s for s in r.tables[0].stats if s.name == "amount_usd")
        assert amount.min == pytest.approx(12.50)
        assert amount.max == pytest.approx(1024.00)
        assert amount.mean is not None

    def test_categorical_top_values(self, tiny_csv):
        r = _summarize(tiny_csv)
        region = next(s for s in r.tables[0].stats if s.name == "region")
        # NA appears 4x in tiny.csv, EU 3x, APAC 2x, one null
        top_by_value = dict(region.top_values)
        assert top_by_value.get("NA", 0) >= 3

    def test_no_stats_keeps_schema(self, tiny_csv):
        r = _summarize(tiny_csv, no_stats=True)
        # Schema dtype must still be correct
        by_name = {c.name: c.dtype for c in r.tables[0].columns}
        assert by_name["amount_usd"] == "float"
        # But stats list is empty
        assert r.tables[0].stats == []

    def test_median_flag_gated(self, tiny_csv):
        r_off = _summarize(tiny_csv)
        amount_off = next(s for s in r_off.tables[0].stats if s.name == "amount_usd")
        assert amount_off.median is None
        r_on = _summarize(tiny_csv, median=True)
        amount_on = next(s for s in r_on.tables[0].stats if s.name == "amount_usd")
        assert amount_on.median is not None


# ── Sampling ──────────────────────────────────────────────────────────────────

class TestSampling:
    def test_head_only(self, tiny_csv):
        r = _summarize(tiny_csv, sample_head=3, sample_tail=0)
        t = r.tables[0]
        assert len(t.head) == 3
        assert t.tail == []

    def test_no_sample(self, tiny_csv):
        r = _summarize(tiny_csv, no_sample=True)
        assert r.tables[0].head == [] and r.tables[0].tail == []


# ── Column subset ─────────────────────────────────────────────────────────────

class TestColumnsSubset:
    def test_columns_filter(self, tiny_csv):
        r = _summarize(tiny_csv, columns=["order_id", "region"])
        names = [c.name for c in r.tables[0].columns]
        assert names == ["order_id", "region"]
        # Sample rows should also only have those keys
        for row in r.tables[0].head:
            assert set(row.keys()) <= {"order_id", "region"}


# ── Caps ──────────────────────────────────────────────────────────────────────

class TestCaps:
    def test_max_rows_truncates(self, tiny_csv):
        r = _summarize(tiny_csv, max_rows=3)
        t = r.tables[0]
        assert t.truncated is True
        assert any("sampled from first" in n for n in t.notes)

    def test_max_columns_caps_count(self, tiny_csv):
        r = _summarize(tiny_csv, max_columns=2)
        assert len(r.tables[0].columns) == 2


# ── Renderers ─────────────────────────────────────────────────────────────────

class TestRenderers:
    def test_json_renderer_valid(self, tiny_csv):
        r = _summarize(tiny_csv)
        d = r.to_json()
        # Should be JSON-serializable
        json.dumps(d, default=str)
        assert d["file_format"] == "csv"
        assert len(d["tables"]) == 1

    def test_markdown_has_schema_section(self, tiny_csv):
        md = _summarize(tiny_csv).to_markdown()
        assert "## Schema" in md
        assert "## Sample" in md
        assert "## Statistics" in md

    def test_text_has_each_column(self, tiny_csv):
        text = _summarize(tiny_csv).to_text()
        for col in ("order_id", "amount_usd", "region"):
            assert col in text


# ── Optional-dep fallback ─────────────────────────────────────────────────────

class TestOptionalDeps:
    def test_missing_parquet_dep(self, tmp_path):
        p = tmp_path / "fake.parquet"
        p.write_bytes(b"\x00" * 16)
        with pytest.raises(MissingOptionalDep):
            _summarize(p, format_hint="parquet")

    def test_missing_excel_dep_when_openpyxl_absent(self, monkeypatch, tmp_path):
        # Patch openpyxl import
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("openpyxl not installed (simulated)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        p = tmp_path / "fake.xlsx"
        p.write_bytes(b"PK\x03\x04")
        with pytest.raises(MissingOptionalDep):
            _summarize(p, format_hint="xlsx")


# ── CLI exit codes ────────────────────────────────────────────────────────────

class TestCLIExitCodes:
    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "data_summarizer.cli", *args],
            capture_output=True, text=True,
        )

    def test_zero_on_success(self, tiny_csv):
        r = self._run(str(tiny_csv))
        assert r.returncode == 0
        assert "# Data Summary:" in r.stdout

    def test_one_on_missing_file(self, tmp_path):
        r = self._run(str(tmp_path / "no_such.csv"))
        assert r.returncode == 1

    def test_four_on_missing_optional_dep(self, tmp_path):
        p = tmp_path / "x.parquet"
        p.write_bytes(b"\x00" * 16)
        r = self._run(str(p))
        assert r.returncode == 4

    def test_format_json_valid(self, tiny_csv):
        r = self._run(str(tiny_csv), "--format", "json")
        assert r.returncode == 0
        json.loads(r.stdout)  # raises if invalid


# ── Directory mode ────────────────────────────────────────────────────────────

class TestDirectoryMode:
    def test_summarizes_multiple_files(self, sample_data_dir):
        r = subprocess.run(
            [sys.executable, "-m", "data_summarizer.cli", str(sample_data_dir), "--no-stats"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        # Should contain results for at least csv/jsonl/sqlite (3 separators)
        assert r.stdout.count("# Data Summary:") >= 3

    def test_excludes_node_modules(self, sample_data_dir):
        r = subprocess.run(
            [sys.executable, "-m", "data_summarizer.cli", str(sample_data_dir), "--no-stats"],
            capture_output=True, text=True,
        )
        # bad.csv inside node_modules must not appear
        assert "bad.csv" not in r.stdout


# ── MCP wrapper ───────────────────────────────────────────────────────────────

class TestMCPWrapper:
    def test_summarize_data_returns_result(self, tiny_csv):
        req = json.dumps({"name": "summarize_data", "parameters": {"path": str(tiny_csv), "sample": 3}})
        r = subprocess.run(
            [sys.executable, "-m", "data_summarizer.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        assert r.returncode == 0
        d = json.loads(r.stdout.strip())
        assert "result" in d
        assert "# Data Summary:" in d["result"]

    def test_unknown_tool_returns_error(self):
        req = json.dumps({"name": "nope", "parameters": {}})
        r = subprocess.run(
            [sys.executable, "-m", "data_summarizer.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d

    def test_missing_path_returns_error(self):
        req = json.dumps({"name": "summarize_data", "parameters": {"path": "/no/such/file.csv"}})
        r = subprocess.run(
            [sys.executable, "-m", "data_summarizer.mcp_tool"],
            input=req + "\n", capture_output=True, text=True,
        )
        d = json.loads(r.stdout.strip())
        assert "error" in d
