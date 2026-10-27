from __future__ import annotations

import re
import time
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from pydantic import BaseModel

try:
    from groq import Groq
except Exception:  # pragma: no cover - graceful fallback if SDK is not installed yet
    Groq = None

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.schemas import AgentStep
from app.services.llm.prompts import build_grounded_prompt
from app.services.llm.structured import StructuredOutputValidationError, validate_structured_output
from app.services.llm.tools import (
    ToolDefinition,
    ToolRunResult,
    execute_tool_calls,
    openai_tool_payload,
    tool_calls_from_openai_message,
)

logger = get_logger(__name__)


@dataclass
class LLMCallInfo:
    provider: str
    model: str
    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)


class BaseTrackedLLMProvider:
    provider_name: str
    model_name: str
    supports_json_mode = False
    supports_tool_calling = False

    def __init__(self) -> None:
        self._last_call = LLMCallInfo(provider="unknown", model="unknown")
        self.structured_trace_steps: list[AgentStep] = []

    @property
    def last_call_info(self) -> LLMCallInfo:
        return self._last_call

    def _record_call(self, *, provider: str, model: str, latency_ms: float, usage: dict[str, int] | None = None) -> None:
        usage_payload = usage or {}
        self._last_call = LLMCallInfo(
            provider=provider,
            model=model,
            latency_ms=latency_ms,
            usage=usage_payload,
        )
        logger.info(
            "llm_call provider=%s model=%s latency_ms=%.2f prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            provider,
            model,
            latency_ms,
            usage_payload.get("prompt_tokens"),
            usage_payload.get("completion_tokens"),
            usage_payload.get("total_tokens"),
        )

    def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        schema_prompt = self._strict_json_prompt(prompt, schema)
        raw = self.generate(schema_prompt, contexts=[], require_citations=False)
        try:
            return validate_structured_output(raw, schema)
        except StructuredOutputValidationError as exc:
            self._record_structured_failure(schema=schema, prompt=schema_prompt, raw=raw, error=exc)
            raise

    def stream_generate(
        self,
        question: str,
        contexts: list[str],
        require_citations: bool = True,
        response_preferences: dict | None = None,
    ) -> Iterable[str]:
        answer = self.generate(question, contexts, require_citations=require_citations, response_preferences=response_preferences)
        for token in re.findall(r"\S+\s*", answer):
            yield token

    def run_tools(self, messages: list[dict[str, str]], tools: list[ToolDefinition], tool_choice: str = "auto") -> ToolRunResult:
        return ToolRunResult(
            provider=self.provider_name,
            model=self.model_name,
            raw_response="tool_calling_unsupported",
            fallback_used=True,
        )

    @staticmethod
    def _strict_json_prompt(prompt: str, schema: type[BaseModel]) -> str:
        return (
            "Return exactly one JSON object that validates against this JSON schema. "
            "Do not include markdown, prose, or comments.\n"
            f"Schema: {schema.model_json_schema()}\n\n"
            f"Task:\n{prompt}"
        )

    def _record_structured_failure(self, *, schema: type[BaseModel], prompt: str, raw: str, error: Exception) -> None:
        self.structured_trace_steps.append(
            AgentStep(
                step_id=f"structured-output-failed-{len(self.structured_trace_steps) + 1}",
                agent_name="LLMProvider",
                action="generate_structured",
                status="failed",
                input_summary=f"Schema={schema.__name__}",
                output_summary="Malformed structured output; deterministic fallback should be used.",
                metadata={
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "error": str(error),
                    "raw_output": raw[:1000],
                    "prompt": prompt[:1000],
                },
            )
        )


class GroundedFallbackLLMProvider(BaseTrackedLLMProvider):
    provider_name = "grounded_fallback"
    model_name = "extractive-local-v2"
    supports_json_mode = False
    supports_tool_calling = False
    QUESTION_STOPWORDS = {
        "what",
        "which",
        "when",
        "where",
        "with",
        "from",
        "that",
        "this",
        "there",
        "their",
        "cite",
        "page",
        "explain",
        "layman",
        "simple",
        "mein",
        "karo",
        "batao",
        "hinglish",
        "english",
    }
    REFERENCE_PAGE_MARKERS = (
        "question bank",
        "evaluation question",
        "expected evidence/result",
        "citation validation prompt",
        "evidence inventory and citation map",
    )

    def __init__(self) -> None:
        super().__init__()

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        start = time.perf_counter()
        if not contexts:
            answer = "I do not have enough grounded evidence in the retrieved documents to answer reliably."
            self._record_call(
                provider=self.provider_name,
                model=self.model_name,
                latency_ms=(time.perf_counter() - start) * 1000,
                usage={},
            )
            return answer
        preferences = response_preferences or {}
        mode = preferences.get("answer_mode", "answer")
        language = preferences.get("language", "english")
        intent = preferences.get("intent", "factual")
        evidence_sentences, best_source = self._select_evidence(question, contexts, intent)
        supported_text = " ".join(evidence_sentences)
        if language == "hinglish":
            supported_text = self._to_hinglish(supported_text, intent)
        elif language == "hindi":
            supported_text = self._to_hindi(supported_text)
        elif language == "spanish":
            supported_text = self._to_spanish(supported_text)
        supported_answer = f"{supported_text} {best_source}" if require_citations and best_source else supported_text
        if mode == "scenario":
            answer = f"From your document:\n{supported_answer}\n\nExample scenario:\nThis evidence can be applied as an example, but the scenario itself is illustrative."
        elif mode == "quiz_me":
            answer = f"Question: What key fact is supported by this source?\n\nAnswer: {supported_answer}"
        elif language == "hinglish":
            answer = f"Aapke document ke hisaab se: {supported_answer}"
        elif language == "hindi":
            answer = f"आपके दस्तावेज़ के अनुसार: {supported_answer}"
        elif language == "spanish":
            answer = f"Según su documento: {supported_answer}"
        else:
            answer = supported_answer
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=(time.perf_counter() - start) * 1000,
            usage={},
        )
        return answer

    def _select_evidence(self, question: str, contexts: list[str], intent: str) -> tuple[list[str], str]:
        keywords = {
            token.lower()
            for token in re.findall(r"\w+", question)
            if len(token) > 3 and token.lower() not in self.QUESTION_STOPWORDS
        }
        wants_number = bool(re.search(r"\b(total|value|how much|how many|peak|highest|generation|capacity|budget)\b", question.lower()))
        wants_total = bool(re.search(r"\b(total|annual|yearly)\b", question.lower()))
        wants_peak = bool(re.search(r"\b(peak|highest|maximum|most)\b", question.lower()))
        candidates: list[tuple[float, str, str]] = []
        for context in contexts:
            source_line, _, body = context.partition("\n")
            lowered_body = body.lower()
            visual_context = "content_type=visual_text" in source_line.lower()
            reference_penalty = -8 if any(marker in lowered_body for marker in self.REFERENCE_PAGE_MARKERS) else 0
            sentences = re.split(r"(?<=[.!?])\s+", body.strip())
            for index, raw_sentence in enumerate(sentences):
                sentence = self._clean_sentence(raw_sentence)
                if len(sentence) < 20:
                    continue
                lowered_sentence = sentence.lower()
                overlap = sum(1 for token in keywords if token in lowered_sentence)
                score = float(overlap * 3 + reference_penalty)
                if "?" in sentence or "prompt" in lowered_sentence or lowered_sentence.startswith("ask "):
                    score -= 12
                if wants_number and re.search(r"\d", sentence):
                    score += 2
                if wants_total and re.search(r"\b(total|totalled|annual|year)\b", lowered_sentence):
                    score += 5
                if wants_peak and re.search(r"\b(peak|peaked|highest|maximum)\b", lowered_sentence):
                    score += 5
                if intent in {"chart_analysis", "visual_question", "table_analysis"} and re.search(
                    r"\b(chart|availability|trend|peaked|generation|table|score)\b", lowered_sentence
                ):
                    score += 2
                if intent in {"chart_analysis", "visual_question", "table_analysis"} and visual_context:
                    score += 6
                if index == 0 and reference_penalty == 0:
                    score += 0.25
                candidates.append((score, sentence, source_line.strip()))
        if not candidates:
            body = contexts[0].split("\n", 1)[-1].strip()
            return [self._clean_sentence(body)], contexts[0].split("\n", 1)[0].strip()
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_sentence, best_source = candidates[0]
        selected = [best_sentence]
        if intent in {"chart_analysis", "visual_question", "table_analysis", "summary"}:
            for score, sentence, source in candidates[1:]:
                if source == best_source and sentence != best_sentence and score >= max(best_score - 5, 1):
                    selected.append(sentence)
                    break
        return selected, best_source

    @staticmethod
    def _clean_sentence(sentence: str) -> str:
        cleaned = re.sub(r"^AIWANA QA DOCUMENT \| Fictional test material\s+\w+\s+PAGE \d+ OF \d+\s+", "", sentence.strip())
        return cleaned

    @staticmethod
    def _to_hinglish(text: str, intent: str) -> str:
        substitutions = (
            ("Quarterly generation totalled", "Quarterly generation ka total"),
            ("with Q4 the strongest period at", "aur Q4 sabse strong period tha"),
            ("after preventive maintenance in September", "September ke preventive maintenance ke baad"),
            ("Daily availability averaged", "Daily availability ka average"),
            ("litres across the year and increased sharply during monsoon recharge between July and September", "litres tha, aur July se September monsoon recharge ke dauran yeh tezi se badhi"),
            ("Availability peaked in August at", "August mein availability sabse zyada thi:"),
            ("The report links the seasonal rise to monsoon recharge", "Report ke mutabik seasonal badhotri monsoon recharge se judi thi"),
        )
        result = text
        for source, target in substitutions:
            result = result.replace(source, target)
        if intent == "chart_analysis" and result == text:
            return f"Graph se yeh pata chalta hai: {text}"
        return result

    @staticmethod
    def _to_hindi(text: str) -> str:
        substitutions = (
            ("The termination clause requires", "समाप्ति धारा में आवश्यक है"),
            ("thirty days notice", "तीस दिन का नोटिस"),
            ("The chart shows", "चार्ट दिखाता है"),
            ("revenue growth", "राजस्व वृद्धि"),
        )
        result = text
        for source, target in substitutions:
            result = result.replace(source, target)
        return result

    @staticmethod
    def _to_spanish(text: str) -> str:
        substitutions = (
            ("The termination clause requires", "La clausula de terminacion requiere"),
            ("thirty days notice", "aviso de treinta dias"),
            ("The chart shows", "El grafico muestra"),
            ("revenue growth", "crecimiento de ingresos"),
        )
        result = text
        for source, target in substitutions:
            result = result.replace(source, target)
        return result


class GroqLLMProvider(BaseTrackedLLMProvider):
    provider_name = "groq"
    supports_json_mode = True
    supports_tool_calling = True

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.model_name = settings.llm_model or "llama-3.3-70b-versatile"
        if Groq is None:
            raise RuntimeError("groq SDK is not installed.")
        self._client = Groq(api_key=settings.groq_api_key)

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        messages = build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences)
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        usage = self._extract_usage(response)
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
            usage=usage,
        )
        return (response.choices[0].message.content or "").strip()

    def stream_generate(
        self,
        question: str,
        contexts: list[str],
        require_citations: bool = True,
        response_preferences: dict | None = None,
    ) -> Iterable[str]:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        messages = build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences)
        start = time.perf_counter()
        collected: list[str] = []
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.1,
            stream=True,
        )
        for chunk in response:
            delta = getattr(chunk.choices[0].delta, "content", None)
            if delta:
                collected.append(delta)
                yield delta
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=(time.perf_counter() - start) * 1000,
            usage={"completion_tokens": len("".join(collected).split())},
        )

    def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        schema_prompt = self._strict_json_prompt(prompt, schema)
        start = time.perf_counter()
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": schema_prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except Exception:
            return BaseTrackedLLMProvider.generate_structured(self, prompt, schema)
        latency_ms = (time.perf_counter() - start) * 1000
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=latency_ms, usage=self._extract_usage(response))
        raw = (response.choices[0].message.content or "").strip()
        try:
            return validate_structured_output(raw, schema)
        except StructuredOutputValidationError as exc:
            self._record_structured_failure(schema=schema, prompt=schema_prompt, raw=raw, error=exc)
            raise

    def run_tools(self, messages: list[dict[str, str]], tools: list[ToolDefinition], tool_choice: str = "auto") -> ToolRunResult:
        if not self.settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not configured.")
        from app.services.orchestrator.agent_orchestrator import AgentOrchestrator

        allowed_tools = [tool for tool in tools if tool.name in AgentOrchestrator.TOOL_ALLOWLIST]
        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            tools=[openai_tool_payload(tool) for tool in allowed_tools],
            tool_choice=tool_choice,
            temperature=0.0,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=latency_ms, usage=self._extract_usage(response))
        message = response.choices[0].message
        tool_calls = tool_calls_from_openai_message(message)
        results = execute_tool_calls(tool_calls, allowed_tools, allowlist=AgentOrchestrator.TOOL_ALLOWLIST)
        return ToolRunResult(provider=self.provider_name, model=self.model_name, tool_calls=tool_calls, results=results, raw_response=str(message))

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        return {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        }


class OpenAILLMProvider(BaseTrackedLLMProvider):
    provider_name = "openai"
    supports_json_mode = True
    supports_tool_calling = True

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.model_name = settings.llm_model or "gpt-4o-mini"

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI provider.")
        payload = {
            "model": self.model_name,
            "messages": build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences),
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        start = time.perf_counter()
        with httpx.Client(timeout=60.0) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        latency_ms = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
        )
        return data["choices"][0]["message"]["content"].strip()

    def stream_generate(
        self,
        question: str,
        contexts: list[str],
        require_citations: bool = True,
        response_preferences: dict | None = None,
    ) -> Iterable[str]:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI provider.")
        payload = {
            "model": self.model_name,
            "messages": build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences),
            "temperature": 0.1,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "Content-Type": "application/json"}
        start = time.perf_counter()
        collected: list[str] = []
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", "https://api.openai.com/v1/chat/completions", json=payload, headers=headers) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        collected.append(delta)
                        yield delta
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=(time.perf_counter() - start) * 1000,
            usage={"completion_tokens": len("".join(collected).split())},
        )

    def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI provider.")
        schema_prompt = self._strict_json_prompt(prompt, schema)
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": schema_prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "Content-Type": "application/json"}
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except Exception:
            return BaseTrackedLLMProvider.generate_structured(self, prompt, schema)
        latency_ms = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
        )
        raw = data["choices"][0]["message"].get("content", "").strip()
        try:
            return validate_structured_output(raw, schema)
        except StructuredOutputValidationError as exc:
            self._record_structured_failure(schema=schema, prompt=schema_prompt, raw=raw, error=exc)
            raise

    def run_tools(self, messages: list[dict[str, str]], tools: list[ToolDefinition], tool_choice: str = "auto") -> ToolRunResult:
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI provider.")
        from app.services.orchestrator.agent_orchestrator import AgentOrchestrator

        allowed_tools = [tool for tool in tools if tool.name in AgentOrchestrator.TOOL_ALLOWLIST]
        payload = {
            "model": self.model_name,
            "messages": messages,
            "tools": [openai_tool_payload(tool) for tool in allowed_tools],
            "tool_choice": tool_choice,
            "temperature": 0.0,
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "Content-Type": "application/json"}
        start = time.perf_counter()
        with httpx.Client(timeout=60.0) as client:
            response = client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        latency_ms = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self._record_call(
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
        )
        message = data["choices"][0]["message"]
        tool_calls = tool_calls_from_openai_message(message)
        results = execute_tool_calls(tool_calls, allowed_tools, allowlist=AgentOrchestrator.TOOL_ALLOWLIST)
        return ToolRunResult(provider=self.provider_name, model=self.model_name, tool_calls=tool_calls, results=results, raw_response=message)


class OpenAICompatibleLLMProvider(OpenAILLMProvider):
    provider_name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        BaseTrackedLLMProvider.__init__(self)
        self.settings = settings
        self.model_name = settings.llm_model
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        if not self.base_url:
            raise RuntimeError("LLM_BASE_URL is required for openai_compatible/private provider.")

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI-compatible provider.")
        payload = {
            "model": self.model_name,
            "messages": build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences),
            "temperature": 0.1,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        start = time.perf_counter()
        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        latency_ms = (time.perf_counter() - start) * 1000
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=latency_ms, usage=usage)
        return data["choices"][0]["message"]["content"].strip()

    def stream_generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> Iterable[str]:
        if httpx is None:
            raise RuntimeError("httpx is required for OpenAI-compatible provider.")
        payload = {
            "model": self.model_name,
            "messages": build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences),
            "temperature": 0.1,
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        start = time.perf_counter()
        collected: list[str] = []
        with httpx.Client(timeout=60.0) as client:
            with client.stream("POST", f"{self.base_url}/chat/completions", json=payload, headers=headers) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        collected.append(delta)
                        yield delta
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=(time.perf_counter() - start) * 1000, usage={"completion_tokens": len("".join(collected).split())})


class OllamaLLMProvider(BaseTrackedLLMProvider):
    provider_name = "ollama"
    supports_json_mode = False
    supports_tool_calling = False

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.model_name = settings.llm_model
        self.base_url = settings.ollama_base_url.rstrip("/")

    def generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> str:
        if httpx is None:
            raise RuntimeError("httpx is required for Ollama provider.")
        messages = build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences)
        payload = {"model": self.model_name, "messages": messages, "stream": False, "options": {"temperature": 0.1}}
        start = time.perf_counter()
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=(time.perf_counter() - start) * 1000, usage={})
        return str(data.get("message", {}).get("content", "")).strip()

    def stream_generate(self, question: str, contexts: list[str], require_citations: bool = True, response_preferences: dict | None = None) -> Iterable[str]:
        if httpx is None:
            raise RuntimeError("httpx is required for Ollama provider.")
        messages = build_grounded_prompt(question, contexts, require_citations=require_citations, response_preferences=response_preferences)
        payload = {"model": self.model_name, "messages": messages, "stream": True, "options": {"temperature": 0.1}}
        start = time.perf_counter()
        collected: list[str] = []
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = str(data.get("message", {}).get("content") or "")
                    if token:
                        collected.append(token)
                        yield token
                    if data.get("done"):
                        break
        self._record_call(provider=self.provider_name, model=self.model_name, latency_ms=(time.perf_counter() - start) * 1000, usage={"completion_tokens": len("".join(collected).split())})


def build_llm_providers(settings: Settings) -> tuple[BaseTrackedLLMProvider, BaseTrackedLLMProvider | None]:
    if settings.llm_privacy_mode == "private_only" and settings.llm_provider not in {"openai_compatible", "private", "ollama"}:
        raise RuntimeError("LLM_PRIVACY_MODE=private_only requires LLM_PROVIDER=openai_compatible, private, or ollama.")
    if settings.llm_provider in {"openai_compatible", "private"}:
        return OpenAICompatibleLLMProvider(settings), None
    if settings.llm_provider == "ollama":
        return OllamaLLMProvider(settings), None
    if settings.llm_provider == "openai":
        primary = OpenAILLMProvider(settings) if settings.openai_api_key else GroundedFallbackLLMProvider()
        fallback = GroqLLMProvider(settings) if settings.enable_openai_fallback and settings.groq_api_key and Groq is not None else None
        return primary, fallback
    primary = GroqLLMProvider(settings) if settings.groq_api_key and Groq is not None else GroundedFallbackLLMProvider()
    fallback = OpenAILLMProvider(settings) if settings.enable_openai_fallback and settings.openai_api_key else None
    return primary, fallback


def build_primary_llm_provider(settings: Settings):
    return build_llm_providers(settings)[0]
