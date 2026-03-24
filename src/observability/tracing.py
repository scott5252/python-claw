from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass
class TracingFacade:
    enabled: bool = False

    @contextmanager
    def span(self, name: str, **_: object) -> Iterator[None]:
        _ = name
        yield
