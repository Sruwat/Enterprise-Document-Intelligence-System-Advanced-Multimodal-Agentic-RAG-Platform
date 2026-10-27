from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.llm.llm_provider import BaseTrackedLLMProvider, GroundedFallbackLLMProvider
from app.services.llm.structured import StructuredOutputValidationError
from app.services.llm.tools import ToolCall, ToolDefinition, execute_tool_calls
from app.services.orchestrator.agent_orchestrator import AgentOrchestrator


class _RouteShape(BaseModel):
    intent: str
    confidence: float


class _StructuredProvider(BaseTrackedLLMProvider):
    provider_name = "test"
    model_name = "test-json"

    def __init__(self, payload: str) -> None:
        super().__init__()
        self.payload = payload

    def generate(self, *_args, **_kwargs):
        return self.payload


def test_generate_structured_accepts_valid_json_output():
    provider = _StructuredProvider('{"intent":"summary","confidence":0.9}')

    result = provider.generate_structured("classify", _RouteShape)

    assert result.intent == "summary"
    assert result.confidence == 0.9


def test_generate_structured_repairs_malformed_json_once():
    provider = _StructuredProvider("```json\n{'intent':'summary','confidence':0.81,}\n```")

    result = provider.generate_structured("classify", _RouteShape)

    assert result.intent == "summary"
    assert result.confidence == 0.81


def test_generate_structured_records_failed_agent_step_when_repair_fails():
    provider = _StructuredProvider("not-json")

    with pytest.raises(StructuredOutputValidationError):
        provider.generate_structured("classify", _RouteShape)

    assert provider.structured_trace_steps[-1].status == "failed"
    assert provider.structured_trace_steps[-1].metadata["raw_output"] == "not-json"


def test_tool_call_executes_valid_allowlisted_tool():
    tools = [
        ToolDefinition(
            name="search_documents",
            description="Search documents.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda args: {"query": args["query"], "count": 1},
        )
    ]

    results = execute_tool_calls(
        [ToolCall(tool_name="search_documents", arguments={"query": "risk"})],
        tools,
        allowlist=AgentOrchestrator.TOOL_ALLOWLIST,
    )

    assert results[0].status == "completed"
    assert results[0].output == {"query": "risk", "count": 1}


def test_unknown_tool_is_rejected_even_when_handler_exists():
    tools = [ToolDefinition(name="run_python", handler=lambda _args: "unsafe")]

    results = execute_tool_calls(
        [ToolCall(tool_name="run_python", arguments={"code": "print(1)"})],
        tools,
        allowlist=AgentOrchestrator.TOOL_ALLOWLIST,
    )

    assert results[0].status == "failed"
    assert "allowlisted" in results[0].error


def test_provider_without_tool_support_returns_fallback_tool_result():
    provider = GroundedFallbackLLMProvider()

    result = provider.run_tools([{"role": "user", "content": "search"}], [])

    assert provider.supports_json_mode is False
    assert provider.supports_tool_calling is False
    assert result.fallback_used is True
    assert result.tool_calls == []
