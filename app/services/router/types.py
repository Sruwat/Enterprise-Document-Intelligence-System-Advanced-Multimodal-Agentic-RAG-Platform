from __future__ import annotations

from typing import Protocol

from app.core.schemas import RouteDecision


class Router(Protocol):
    def route(self, question: str) -> RouteDecision:
        ...
