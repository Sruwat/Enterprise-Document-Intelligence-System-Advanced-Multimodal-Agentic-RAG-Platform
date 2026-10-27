from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentToolCall(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class AgentDecision(BaseModel):
    agent_name: str
    objective_profile: str = "general"
    analysis_mode: str = "quick"
    intent: str = "factual"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tools: list[AgentToolCall] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class StructuredRoutePlan(BaseModel):
    intent: str = "factual"
    objective_profile: str = "general"
    analysis_mode: str = "quick"
    retrieval_strategy: str = "hybrid"
    requested_top_k: int = 5
    needs_clarification: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    tool_calls: list[AgentToolCall] = Field(default_factory=list)


class ObjectiveAnalysis(BaseModel):
    module: Literal["legal", "research", "enterprise"]
    findings: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_tools: list[AgentToolCall] = Field(default_factory=list)
