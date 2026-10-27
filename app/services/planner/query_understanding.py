from __future__ import annotations

from dataclasses import dataclass

from app.core.schemas import AnswerMode, ExplanationLevel, LanguagePreference
from app.services.language import LanguagePreferenceService


@dataclass
class QueryUnderstanding:
    retrieval_query: str
    interpreted_query: str | None
    input_language: LanguagePreference
    answer_language: LanguagePreference
    explanation_level: ExplanationLevel
    route_hint: str | None
    needs_clarification: bool = False


class QueryUnderstandingService:
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
    RETRIEVAL_TRANSLATIONS = {
        "batao": "explain",
        "bataiye": "explain",
        "samjhao": "explain",
        "kya": "what",
        "kaise": "how",
        "kyun": "why",
        "mujhe": "me",
        "iska": "this",
        "isme": "in this",
    }
    HINDI_RETRIEVAL_TRANSLATIONS = {
        "क्या": "what",
        "किस": "which",
        "कैसे": "how",
        "क्यों": "why",
        "समझाओ": "explain",
        "बताओ": "explain",
        "सारांश": "summary",
        "अनुबंध": "contract",
        "समाप्ति": "termination",
        "नोटिस": "notice",
        "जोखिम": "risk",
    }
    SPANISH_RETRIEVAL_TRANSLATIONS = {
        "qué": "what",
        "que": "what",
        "cómo": "how",
        "como": "how",
        "dice": "says",
        "por": "for",
        "sobre": "about",
        "resumen": "summary",
        "explica": "explain",
        "contrato": "contract",
        "terminación": "termination",
        "terminacion": "termination",
        "aviso": "notice",
        "riesgo": "risk",
    }
    MODE_ROUTES = {
        "summarize": "summary",
        "explain_visual": "visual_question",
        "compare": "comparison",
        "scenario": "scenario",
        "quiz_me": "quiz",
    }

    def understand(
        self,
        question: str,
        language: LanguagePreference = "auto",
        input_language: LanguagePreference | None = None,
        response_language: LanguagePreference | None = None,
        explanation_level: ExplanationLevel = "normal",
        answer_mode: AnswerMode = "answer",
    ) -> QueryUnderstanding:
        words = [word.strip(" ?¿¡.,;:!").lower() for word in question.split()]
        words = [word for word in words if word]
        detected_language = input_language or (LanguagePreferenceService().detect(question) if language == "auto" else language)
        answer_language: LanguagePreference = response_language or language
        if answer_language == "auto":
            answer_language = detected_language if detected_language != "auto" else "english"
        translated_words = [self._translate_for_retrieval(word, detected_language) for word in words]
        retrieval_query = " ".join(translated_words).strip() or question
        interpreted_query = retrieval_query if retrieval_query.lower() != question.strip(" ?").lower() else None
        return QueryUnderstanding(
            retrieval_query=retrieval_query,
            interpreted_query=interpreted_query,
            input_language=detected_language,
            answer_language=answer_language,
            explanation_level=explanation_level,
            route_hint=self.MODE_ROUTES.get(answer_mode),
            needs_clarification=len(question.strip()) < 4,
        )

    def _translate_for_retrieval(self, word: str, language: LanguagePreference) -> str:
        if language == "hindi":
            return self.HINDI_RETRIEVAL_TRANSLATIONS.get(word, word)
        if language == "spanish":
            return self.SPANISH_RETRIEVAL_TRANSLATIONS.get(word, word)
        return self.RETRIEVAL_TRANSLATIONS.get(word, word)
