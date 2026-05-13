"""Streaming accumulators for per-column statistics."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+([eE][+-]?\d+)?$|^-?\d+([eE][+-]?\d+)?$")
_BOOL_VALUES = {"true", "false"}
_DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"),
]


def infer_value_type(v: Any) -> str:
    """Return one of: int, float, bool, datetime, string, null."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "nan" if math.isnan(v) else "float"
    if isinstance(v, datetime):
        return "datetime"
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return "null"
        if s.lower() in _BOOL_VALUES:
            return "bool"
        if _INT_RE.match(s):
            return "int"
        if _FLOAT_RE.match(s):
            return "float"
        if any(p.match(s) for p in _DATE_PATTERNS):
            return "datetime"
        return "string"
    return "string"


def merge_types(types: set[str]) -> str:
    """Reduce a set of observed types to one column-level dtype."""
    types = {t for t in types if t not in ("null", "nan")}
    if not types:
        return "null"
    if len(types) == 1:
        return types.pop()
    if types == {"int", "float"}:
        return "float"
    return "mixed"


def is_null_value(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _coerce_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _coerce_datetime_str(v: Any) -> str | None:
    """Return the ISO-like string for sortable comparison; None if not datetime-like."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str):
        s = v.strip()
        if any(p.match(s) for p in _DATE_PATTERNS):
            return s
    return None


@dataclass
class ColumnAccumulator:
    """Streaming stats accumulator for one column."""
    name: str
    count: int = 0
    null_count: int = 0
    observed_types: set[str] = field(default_factory=set)

    # Numeric running stats (Welford for variance)
    _n_numeric: int = 0
    _mean: float = 0.0
    _m2: float = 0.0
    min_val: float | None = None
    max_val: float | None = None
    _numeric_samples: list[float] = field(default_factory=list)  # only kept if median wanted

    # Datetime min/max as strings (ISO sortable)
    min_dt: str | None = None
    max_dt: str | None = None

    # Distinct + top-k tracking
    _counter: Counter = field(default_factory=Counter)
    _distinct_overflow: bool = False

    # Limits
    max_distinct: int = 100
    keep_samples_for_median: bool = False

    def update(self, value: Any) -> None:
        self.count += 1
        if is_null_value(value):
            self.null_count += 1
            self.observed_types.add("null")
            return

        t = infer_value_type(value)
        self.observed_types.add(t)

        # Numeric path
        num = _coerce_number(value)
        if num is not None and t in ("int", "float"):
            self._n_numeric += 1
            delta = num - self._mean
            self._mean += delta / self._n_numeric
            delta2 = num - self._mean
            self._m2 += delta * delta2
            if self.min_val is None or num < self.min_val:
                self.min_val = num
            if self.max_val is None or num > self.max_val:
                self.max_val = num
            if self.keep_samples_for_median:
                self._numeric_samples.append(num)

        # Datetime path
        dt_s = _coerce_datetime_str(value)
        if dt_s is not None and t == "datetime":
            if self.min_dt is None or dt_s < self.min_dt:
                self.min_dt = dt_s
            if self.max_dt is None or dt_s > self.max_dt:
                self.max_dt = dt_s

        # Distinct + top-k (skip unhashable values like list/dict)
        if not self._distinct_overflow:
            try:
                self._counter[value] += 1
            except TypeError:
                # Unhashable (list, dict, set) — fall back to repr key
                self._counter[repr(value)] += 1
            if len(self._counter) > self.max_distinct:
                self._distinct_overflow = True

    @property
    def distinct_count(self) -> int | None:
        return None if self._distinct_overflow else len(self._counter)

    @property
    def std(self) -> float | None:
        if self._n_numeric < 2:
            return None
        variance = self._m2 / (self._n_numeric - 1)
        return math.sqrt(variance) if variance >= 0 else None

    @property
    def mean(self) -> float | None:
        return self._mean if self._n_numeric > 0 else None

    @property
    def median(self) -> float | None:
        if not self.keep_samples_for_median or not self._numeric_samples:
            return None
        s = sorted(self._numeric_samples)
        n = len(s)
        mid = n // 2
        if n % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) / 2

    def top_values(self, k: int) -> list[tuple[Any, int]]:
        if self._distinct_overflow:
            return self._counter.most_common(k)
        return self._counter.most_common(k)

    def dtype(self) -> str:
        return merge_types(self.observed_types)

    def null_pct(self) -> float:
        return (100.0 * self.null_count / self.count) if self.count else 0.0
