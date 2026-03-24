from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricsSink:
    enabled: bool = False

    def increment(self, name: str, **_: object) -> None:
        _ = name

    def observe(self, name: str, value: float, **_: object) -> None:
        _ = (name, value)
