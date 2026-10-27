from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.services.llm.tools import ToolDefinition, ToolRunResult


class LLMProvider(Protocol):
    provider_name: str
    model_name: str
    supports_json_mode: bool
    supports_tool_calling: bool

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        ...

    def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        ...

    def run_tools(self, messages: list[dict[str, str]], tools: list[ToolDefinition], tool_choice: str = "auto") -> ToolRunResult:
        ...
