from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    handler: Callable[[dict[str, Any]], Any] | None = None


class ToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None


class ToolExecutionResult(BaseModel):
    tool_name: str
    status: str
    output: Any | None = None
    error: str | None = None


class ToolRunResult(BaseModel):
    provider: str
    model: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    results: list[ToolExecutionResult] = Field(default_factory=list)
    raw_response: Any | None = None
    fallback_used: bool = False


def execute_tool_calls(tool_calls: list[ToolCall], tools: list[ToolDefinition], *, allowlist: set[str]) -> list[ToolExecutionResult]:
    registry = {tool.name: tool for tool in tools if tool.name in allowlist}
    results: list[ToolExecutionResult] = []
    for call in tool_calls:
        tool = registry.get(call.tool_name)
        if tool is None:
            results.append(ToolExecutionResult(tool_name=call.tool_name, status="failed", error="Tool is not allowlisted."))
            continue
        if tool.handler is None:
            results.append(ToolExecutionResult(tool_name=call.tool_name, status="failed", error="Tool has no executable handler."))
            continue
        try:
            results.append(ToolExecutionResult(tool_name=call.tool_name, status="completed", output=tool.handler(call.arguments)))
        except Exception as exc:  # pragma: no cover - handlers are app-defined
            results.append(ToolExecutionResult(tool_name=call.tool_name, status="failed", error=str(exc)))
    return results


def openai_tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


def tool_calls_from_openai_message(message: Any) -> list[ToolCall]:
    calls = getattr(message, "tool_calls", None)
    if calls is None and isinstance(message, dict):
        calls = message.get("tool_calls")
    parsed: list[ToolCall] = []
    for call in calls or []:
        function = getattr(call, "function", None)
        if function is None and isinstance(call, dict):
            function = call.get("function", {})
        name = getattr(function, "name", None) if function is not None else None
        if name is None and isinstance(function, dict):
            name = function.get("name")
        raw_args = getattr(function, "arguments", "{}") if function is not None else "{}"
        if isinstance(function, dict):
            raw_args = function.get("arguments", "{}")
        try:
            arguments = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args or {})
        except json.JSONDecodeError:
            arguments = {}
        call_id = getattr(call, "id", None) if not isinstance(call, dict) else call.get("id")
        if name:
            parsed.append(ToolCall(tool_name=name, arguments=arguments, call_id=call_id))
    return parsed
