from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from app.core.schemas import QueryResponse


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def token_chunks(text: str) -> Iterable[str]:
    parts = re.findall(r"\S+\s*", text)
    if not parts:
        yield ""
    for part in parts:
        yield part


def stream_completed_response(response: QueryResponse) -> Iterable[str]:
    yield sse_event(
        "metadata",
        {
            "confidence": response.confidence,
            "intent": response.intent,
            "abstained": response.abstained,
            "grounding_status": response.grounding_status,
        },
    )
    for key, label in [
        ("upload_received", "upload received"),
        ("parsing", "parsing"),
        ("chunking", "chunking"),
        ("embedding", "embedding"),
        ("retrieval", "retrieval"),
        ("reranking", "reranking"),
        ("context_building", "context building"),
        ("llm_generating", "LLM generating"),
        ("citations_ready", "citations ready"),
    ]:
        latency_key = "generation" if key == "llm_generating" else key
        yield sse_event("stage", {"stage": key, "label": label, "latency_ms": response.latency_ms.get(latency_key)})
    for token in token_chunks(response.answer):
        yield sse_event("token", {"text": token})
    yield sse_event("final", response.model_dump(mode="json"))
    yield sse_event("done", {"ok": True})
