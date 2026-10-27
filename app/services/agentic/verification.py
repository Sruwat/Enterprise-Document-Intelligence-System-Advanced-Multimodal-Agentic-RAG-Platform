from __future__ import annotations

import re

from app.core.schemas import Citation
from app.services.agentic.state import VerificationResult


class AgenticVerifier:
    UNSUPPORTED_MARKERS = ("guarantee", "definitely", "always", "never", "100%")

    def verify(
        self,
        *,
        answer: str,
        citations: list[Citation],
        confidence: float,
        final_context_size: int,
    ) -> VerificationResult:
        missing: list[str] = []
        if not citations:
            missing.append("citations")
        if final_context_size <= 0:
            missing.append("retrieved_evidence")
        unsupported_risk = self._unsupported_risk(answer)
        if unsupported_risk:
            missing.append("claim_strength_review")
        status = "grounded"
        if missing or confidence <= 0:
            status = "blocked"
        elif confidence < 0.55:
            status = "low_confidence"
        return VerificationResult(
            grounding_status=status,
            confidence=round(confidence, 4),
            citation_count=len(citations),
            missing_evidence=missing,
            unsupported_claim_risk=unsupported_risk,
        )

    def _unsupported_risk(self, answer: str) -> bool:
        lowered = answer.lower()
        if any(marker in lowered for marker in self.UNSUPPORTED_MARKERS):
            return True
        return bool(re.search(r"\b(no risk|fully compliant|legally certain)\b", lowered))
