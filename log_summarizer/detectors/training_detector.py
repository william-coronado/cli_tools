from __future__ import annotations

import math

import regex

from ..summarizer import LogLine, MetricEntry
from .base import BaseDetector


class TrainingDetector(BaseDetector):
    FORMAT_NAME = "training"

    METRIC_NAMES = {
        "loss", "val_loss", "train_loss", "acc", "accuracy", "val_acc",
        "val_accuracy", "f1", "f1_score", "val_f1", "auc", "roc_auc",
        "pr_auc", "precision", "recall", "lr", "learning_rate", "epoch",
        "step", "iter", "mse", "mae", "rmse", "perplexity", "ppl",
    }

    METRIC_PATTERN = regex.compile(
        r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)"
        r"\s*[=:]\s*"
        r"(?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|nan|inf|-inf)"
    )

    EPOCH_PATTERN = regex.compile(
        r"(?:Epoch\s+)?(?P<current>\d+)\s*/\s*(?P<total>\d+)",
        regex.IGNORECASE,
    )

    PROGRESS_BAR = regex.compile(r"\[=+>?\s*\]|^\d+%\|")

    def score(self, sample_lines: list[str]) -> float:
        if not sample_lines:
            return 0.0
        hits = 0
        for line in sample_lines:
            lower = line.lower()
            if any(name in lower for name in ("epoch", "loss", "accuracy", "val_", "train_")):
                hits += 1
            elif self.METRIC_PATTERN.search(line):
                for m in self.METRIC_PATTERN.finditer(line):
                    if m.group("name").lower() in self.METRIC_NAMES:
                        hits += 1
                        break
            elif self.PROGRESS_BAR.search(line):
                hits += 1
        return min(1.0, hits / len(sample_lines) * 1.5)

    def extract(self, line: str, line_number: int) -> LogLine:
        has_metric = any(
            m.group("name").lower() in self.METRIC_NAMES
            for m in self.METRIC_PATTERN.finditer(line)
        )
        lower = line.lower()
        if has_metric or any(n in lower for n in ("epoch", "step", "iter")):
            return LogLine(
                line_number=line_number, raw=line, level=None,
                timestamp=None, message=line.strip(), category="metric", source=None,
            )
        return LogLine(
            line_number=line_number, raw=line, level=None,
            timestamp=None, message=line.strip(), category="info", source=None,
        )

    def extract_metrics(self, line: str, line_number: int) -> list[MetricEntry]:
        entries: list[MetricEntry] = []
        step: int | None = None
        em = self.EPOCH_PATTERN.search(line)
        if em:
            try:
                step = int(em.group("current"))
            except (ValueError, IndexError):
                pass

        for m in self.METRIC_PATTERN.finditer(line):
            name = m.group("name").lower()
            raw_val = m.group("value").lower()
            if name not in self.METRIC_NAMES:
                continue
            try:
                val: float | str = float(raw_val)
            except ValueError:
                val = raw_val
            entries.append(MetricEntry(
                line_number=line_number,
                name=name,
                value=val,
                step=step,
                unit=None,
            ))
        return entries

    def detect_anomalies(self, metrics: list[MetricEntry]) -> list[LogLine]:
        anomalies: list[LogLine] = []

        # NaN / inf
        for entry in metrics:
            v = entry.value
            if isinstance(v, str) and v in ("nan", "inf", "-inf"):
                anomalies.append(LogLine(
                    line_number=entry.line_number, raw="",
                    level="ERROR", timestamp=None,
                    message=f"Anomaly: {entry.name}={v} at line {entry.line_number}",
                    category="error", source=None,
                ))
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                anomalies.append(LogLine(
                    line_number=entry.line_number, raw="",
                    level="ERROR", timestamp=None,
                    message=f"Anomaly: {entry.name}={v} at line {entry.line_number}",
                    category="error", source=None,
                ))

        # Loss increasing for 3+ consecutive epochs
        loss_vals = [
            (e.step, float(e.value))
            for e in metrics
            if e.name == "loss" and isinstance(e.value, (int, float))
            and not math.isnan(float(e.value)) and not math.isinf(float(e.value))
        ]
        if len(loss_vals) >= 3:
            consecutive_increase = 0
            for i in range(1, len(loss_vals)):
                if loss_vals[i][1] > loss_vals[i - 1][1]:
                    consecutive_increase += 1
                    if consecutive_increase >= 3:
                        anomalies.append(LogLine(
                            line_number=loss_vals[i][0] or 0, raw="",
                            level="WARNING", timestamp=None,
                            message="Training loss has been increasing for 3+ consecutive steps",
                            category="warning", source=None,
                        ))
                        break
                else:
                    consecutive_increase = 0

        return anomalies
