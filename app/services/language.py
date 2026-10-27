from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.schemas import LanguagePreference


SUPPORTED_RESPONSE_LANGUAGES: set[str] = {"english", "hindi", "hinglish", "spanish"}


@dataclass(frozen=True)
class LanguageResolution:
    input_language: LanguagePreference
    response_language: LanguagePreference
    source: str


class LanguagePreferenceService:
    HINGLISH_CUES = {
        "batao",
        "bataiye",
        "samjhao",
        "samjha",
        "kya",
        "kaise",
        "kyun",
        "mujhe",
        "iska",
        "isme",
        "hai",
        "wala",
    }
    SPANISH_CUES = {
        "que",
        "qué",
        "como",
        "cómo",
        "cuál",
        "cual",
        "resumen",
        "explica",
        "contrato",
        "terminación",
        "aviso",
        "riesgo",
    }

    def resolve(self, *, question: str, request, user, session=None) -> LanguageResolution:
        requested_input = self._normalize(getattr(request, "input_language", None))
        legacy_language = self._normalize(getattr(request, "language", "auto"))
        requested_response = self._normalize(getattr(request, "response_language", None))
        detected = self.detect(question)
        input_language = requested_input if requested_input and requested_input != "auto" else detected

        if requested_response and requested_response != "auto":
            return LanguageResolution(input_language=input_language, response_language=requested_response, source="query_response_language")
        if legacy_language and legacy_language != "auto":
            return LanguageResolution(input_language=input_language, response_language=legacy_language, source="query_language")

        session_response = self._normalize(getattr(session, "response_language", None) if session else None)
        if session_response and session_response != "auto":
            return LanguageResolution(input_language=input_language, response_language=session_response, source="session_response_language")

        preferences = getattr(user, "preferences", {}) or {}
        user_response = self._normalize(preferences.get("preferred_response_language") or preferences.get("response_language"))
        if user_response and user_response != "auto":
            return LanguageResolution(input_language=input_language, response_language=user_response, source="user_response_language")

        return LanguageResolution(input_language=input_language, response_language=input_language if input_language != "auto" else "english", source="detected_input_language")

    def detect(self, question: str) -> LanguagePreference:
        text = question.strip()
        lowered = text.lower()
        words = set(re.findall(r"[\w\u0900-\u097f]+", lowered))
        has_devanagari = bool(re.search(r"[\u0900-\u097f]", text))
        has_latin = bool(re.search(r"[A-Za-z]", text))
        if has_devanagari and has_latin:
            return "hinglish"
        if has_devanagari:
            return "hindi"
        if words & self.HINGLISH_CUES:
            return "hinglish"
        if words & self.SPANISH_CUES or re.search(r"[áéíóúñ¿¡]", lowered):
            return "spanish"
        return "english"

    @staticmethod
    def _normalize(value: object) -> LanguagePreference | None:
        if value is None:
            return None
        normalized = str(value).strip().lower().replace("-", "_")
        if normalized in {"en", "english"}:
            return "english"
        if normalized in {"hi", "hindi"}:
            return "hindi"
        if normalized in {"hinglish", "roman_hindi"}:
            return "hinglish"
        if normalized in {"es", "spanish", "espanol", "español"}:
            return "spanish"
        if normalized == "auto":
            return "auto"
        return None
