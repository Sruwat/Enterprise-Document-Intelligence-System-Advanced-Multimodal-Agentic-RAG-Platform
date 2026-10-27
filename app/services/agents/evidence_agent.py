from __future__ import annotations

import uuid

from app.core.schemas import AgentStep, EvidenceCanvas
from app.services.guardrails.citation import build_evidence


class EvidenceAgent:
    def build_canvas(
        self,
        *,
        chunks,
        citations,
        confidence: float,
        route_used: str,
        include_visual: bool,
        answer_preview: str = "",
    ) -> tuple[EvidenceCanvas, AgentStep]:
        evidence_kind = "chart" if route_used == "chart_analysis" else "table" if route_used == "table_analysis" else None
        evidence_items, visual_cards = build_evidence(chunks, include_visual=include_visual, evidence_kind=evidence_kind)
        missing: list[str] = []
        if not chunks:
            missing.append("No document evidence was retrieved for this question.")
        if route_used in {"visual_question", "chart_analysis", "table_analysis"} and not visual_cards:
            missing.append("No dedicated visual/table/chart card could be built from the retrieved evidence.")
        for chunk in chunks:
            page_metadata = (chunk.metadata or {}).get("page_metadata", {})
            missing.extend(page_metadata.get("missing_evidence_notes", []) or [])
        canvas = EvidenceCanvas(
            summary=answer_preview[:320],
            citations=citations,
            evidence_items=evidence_items,
            visual_cards=visual_cards,
            artifact_cards=self._artifact_cards(chunks),
            confidence=confidence,
            missing_evidence=missing,
            why_this_answer=self._why(chunks, citations, route_used),
        )
        step = AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="EvidenceAgent",
            action="build_evidence_canvas",
            output_summary=f"Built canvas with {len(citations)} citations and {len(visual_cards)} visual cards.",
            metadata={"route_used": route_used, "missing_evidence": missing},
        )
        return canvas, step

    @staticmethod
    def _artifact_cards(chunks) -> list[dict]:
        cards: list[dict] = []
        seen: set[str] = set()
        for chunk in chunks:
            page_metadata = (chunk.metadata or {}).get("page_metadata", {})
            candidates = []
            candidates.extend({"artifact_type": "clause", **item} for item in page_metadata.get("clauses", [])[:3])
            candidates.extend({"artifact_type": "risk", **item} for item in page_metadata.get("risks", [])[:4])
            if page_metadata.get("table_json"):
                candidates.append({"artifact_type": "table", **page_metadata["table_json"]})
            if page_metadata.get("chart_series"):
                candidates.append({"artifact_type": "chart", **page_metadata["chart_series"]})
            for item in candidates:
                key = item.get("artifact_id") or f"{chunk.chunk_id}:{item.get('artifact_type')}:{item.get('title')}"
                if key in seen:
                    continue
                seen.add(key)
                cards.append(
                    {
                        "artifact_id": key,
                        "artifact_type": item.get("artifact_type", "artifact"),
                        "title": item.get("title") or item.get("tag") or "Detected artifact",
                        "page_number": chunk.page_number,
                        "filename": chunk.filename,
                        "text": (item.get("text") or item.get("sample_rows") or item.get("points") or "")[:500]
                        if isinstance(item.get("text") or item.get("sample_rows") or item.get("points") or "", str)
                        else item.get("sample_rows") or item.get("points") or [],
                        "risk_tags": item.get("risk_tags", []),
                        "severity": item.get("severity"),
                    }
                )
        return cards[:12]

    @staticmethod
    def _why(chunks, citations, route_used: str) -> str:
        if not chunks:
            return "Aiwana could not ground the answer because no matching source chunks were retrieved."
        pages = sorted({citation.page_number for citation in citations})
        page_text = ", ".join(str(page) for page in pages[:6])
        return f"Aiwana selected {len(chunks)} grounded context chunk(s) for {route_used} and cited page(s): {page_text}."
