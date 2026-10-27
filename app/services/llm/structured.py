from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredOutputValidationError(ValueError):
    def __init__(self, message: str, *, raw_text: str, repaired_text: str | None = None) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.repaired_text = repaired_text


def validate_structured_output(raw_text: str, schema: type[SchemaT]) -> SchemaT:
    """Validate model JSON against a Pydantic schema, with one repair pass."""
    raw_payload = raw_text.strip()
    try:
        return _validate_json_payload(raw_payload, schema)
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as first_error:
        repaired = repair_json_once(raw_payload)
        if repaired == raw_payload:
            raise StructuredOutputValidationError(
                f"Structured output did not match {schema.__name__}: {first_error}",
                raw_text=raw_text,
            ) from first_error
        try:
            return _validate_json_payload(repaired, schema)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as second_error:
            raise StructuredOutputValidationError(
                f"Structured output repair failed for {schema.__name__}: {second_error}",
                raw_text=raw_text,
                repaired_text=repaired,
            ) from second_error


def repair_json_once(raw_text: str) -> str:
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    if _looks_like_single_quoted_json(text):
        text = text.replace("'", '"')
    return text.strip()


def _validate_json_payload(payload: str, schema: type[SchemaT]) -> SchemaT:
    parsed: Any = json.loads(payload)
    return schema.model_validate(parsed)


def _looks_like_single_quoted_json(text: str) -> bool:
    return '"' not in text and bool(re.search(r"'\w+'\s*:", text))
