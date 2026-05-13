from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DetectionResult:
    format_name: str
    confidence: float
    sample_lines: list[str]


class BaseDetector(ABC):
    FORMAT_NAME: str = "unknown"

    @abstractmethod
    def score(self, sample_lines: list[str]) -> float:
        """Return confidence 0.0–1.0. Must never raise."""
        ...

    @abstractmethod
    def extract(self, line: str, line_number: int):
        """Parse a single line into a LogLine."""
        ...

    def is_key_event(self, line) -> bool:
        return False
