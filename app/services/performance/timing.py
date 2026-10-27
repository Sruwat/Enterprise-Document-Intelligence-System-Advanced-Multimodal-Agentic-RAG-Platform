from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator


class StageTimer:
    def __init__(self) -> None:
        self.latency_ms: dict[str, float] = {}

    @contextmanager
    def track(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.latency_ms[name] = (time.perf_counter() - start) * 1000

    def merge_into(self, target: dict[str, float]) -> dict[str, float]:
        target.update(self.latency_ms)
        return target
