from __future__ import annotations

import re
import uuid
from datetime import date

from app.core.schemas import AgentStep
from app.services.agents.contracts import AgentToolCall, ObjectiveAnalysis


class LegalAgent:
    RISK_TERMS = ("termination", "liability", "indemnity", "penalty", "breach", "confidential", "jurisdiction", "payment", "warranty", "governing law")
    EXPECTED_CLAUSES = ("termination", "liability", "indemnity", "confidential", "payment", "governing law", "jurisdiction")

    def annotate(self, question: str, chunks) -> tuple[str, AgentStep]:
        text = " ".join(chunk.text for chunk in chunks)
        lowered = f"{question} {text}".lower()
        matches = sorted({term for term in self.RISK_TERMS if term in lowered})
        clause_inventory = self._clause_inventory(chunks)
        legal_metadata = self._legal_metadata(chunks)
        obligations = self._obligations(text)
        if legal_metadata.get("obligations"):
            obligations = [*(item.get("text", "") for item in legal_metadata["obligations"] if isinstance(item, dict)), *obligations]
            obligations = list(dict.fromkeys(item for item in obligations if item))[:8]
        parties = self._parties(text)
        if legal_metadata.get("parties"):
            parties = list(dict.fromkeys([*legal_metadata["parties"], *parties]))[:8]
        dates = self._dates(text)
        for date_key in ("effective_date", "termination_date", "notice_period"):
            if legal_metadata.get(date_key):
                dates.append(str(legal_metadata[date_key]))
        dates = list(dict.fromkeys(dates))[:12]
        missing = [clause for clause in self.EXPECTED_CLAUSES if clause not in lowered]
        note = "Legal mode: focus on clauses, parties, obligations, dates, exceptions, and risk language."
        if matches:
            note += f" Detected risk topics: {', '.join(matches)}."
        if obligations:
            note += f" Candidate obligations: {'; '.join(obligations[:4])}."
        if parties:
            note += f" Parties/entities detected: {', '.join(parties[:4])}."
        if missing:
            note += f" Missing/unclear standard clauses from retrieved evidence: {', '.join(missing[:5])}."
        analysis = ObjectiveAnalysis(
            module="legal",
            findings=matches,
            risk_tags=matches,
            obligations=obligations,
            missing_evidence=[f"Missing or unclear: {clause}" for clause in missing[:8]],
            recommended_tools=[
                AgentToolCall(tool_name="clause_extractor", arguments={"expected_clauses": list(self.EXPECTED_CLAUSES)}, reason="Normalize contract clauses."),
                AgentToolCall(tool_name="obligation_timeline", arguments={"date_sensitive": True}, reason="Extract due dates and party duties."),
            ],
        )
        return note, AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="LegalAgent",
            action="contract_risk_context",
            output_summary=note,
            metadata={
                "risk_terms": matches,
                "clause_inventory": clause_inventory,
                "obligations": obligations,
                "parties": parties,
                "dates": dates,
                "legal_metadata": legal_metadata,
                "obligation_timeline": self._obligation_timeline(obligations, dates),
                "missing_standard_clauses": missing,
                "structured_output": analysis.model_dump(),
            },
        )

    @staticmethod
    def _obligations(text: str) -> list[str]:
        obligations = []
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if re.search(r"\b(shall|must|required to|agrees to|within \d+ days)\b", sentence, re.IGNORECASE):
                obligations.append(re.sub(r"\s+", " ", sentence).strip()[:260])
        return obligations[:8]

    @staticmethod
    def _parties(text: str) -> list[str]:
        parties = []
        for pattern in (
            r"\b(?:between|by and between)\s+([A-Z][A-Za-z0-9&., ]{2,80}?)\s+and\s+([A-Z][A-Za-z0-9&., ]{2,80}?)(?:[.;,\n]|$)",
            r"\b(?:party|vendor|customer|client|supplier)\s*[:\-]\s*([A-Z][A-Za-z0-9&., ]{2,80})",
        ):
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                values = match if isinstance(match, tuple) else (match,)
                parties.extend(re.sub(r"\s+", " ", value).strip(" .,;") for value in values)
        seen = []
        for party in parties:
            if party and party not in seen:
                seen.append(party)
        return seen[:8]

    @staticmethod
    def _dates(text: str) -> list[str]:
        matches = re.findall(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+(?:days|months|years))\b", text, flags=re.IGNORECASE)
        return list(dict.fromkeys(match.strip() for match in matches))[:12]

    @staticmethod
    def _obligation_timeline(obligations: list[str], dates: list[str]) -> list[dict]:
        timeline = []
        for obligation in obligations:
            due = next((date_text for date_text in dates if date_text.lower() in obligation.lower()), None)
            timeline.append({"obligation": obligation, "due": due or "not specified"})
        return timeline

    @staticmethod
    def _clause_inventory(chunks) -> list[dict]:
        inventory = []
        seen = set()
        for chunk in chunks:
            page_metadata = (chunk.metadata or {}).get("page_metadata", {})
            for clause in page_metadata.get("clauses", []) or []:
                title = clause.get("title") or "Clause"
                key = (title.lower(), chunk.page_number)
                if key in seen:
                    continue
                seen.add(key)
                inventory.append(
                    {
                        "title": title,
                        "page_number": chunk.page_number,
                        "risk_tags": clause.get("risk_tags", []),
                        "text": (clause.get("text") or "")[:500],
                    }
                )
        return inventory[:20]

    @staticmethod
    def _legal_metadata(chunks) -> dict:
        merged: dict = {"parties": [], "obligations": []}
        scalar_keys = ("effective_date", "termination_date", "governing_law", "notice_period", "renewal_terms", "payment_terms", "jurisdiction")
        for chunk in chunks:
            metadata = (chunk.metadata or {}).get("legal_metadata") or (chunk.metadata or {}).get("page_metadata", {}).get("legal_metadata") or {}
            if not isinstance(metadata, dict):
                continue
            merged["parties"].extend(metadata.get("parties") or [])
            merged["obligations"].extend(metadata.get("obligations") or [])
            for key in scalar_keys:
                if not merged.get(key) and metadata.get(key):
                    merged[key] = metadata[key]
        merged["parties"] = list(dict.fromkeys(str(item) for item in merged["parties"] if item))[:10]
        merged["obligations"] = merged["obligations"][:12]
        return {key: value for key, value in merged.items() if value}


class StudyAgent:
    def annotate(self, question: str, chunks) -> tuple[str, AgentStep]:
        wants_quiz = bool(re.search(r"\b(quiz|test|practice|questions?)\b", question.lower()))
        wants_comparison = bool(re.search(r"\b(compare|comparison|versus|vs\.?)\b", question.lower()))
        concepts = self._concepts(chunks)
        structured = self._structured_counts(chunks)
        note = "Research/study mode: explain concepts clearly, preserve citations, and convert evidence into learning-friendly structure."
        if wants_quiz:
            note += " Quiz intent detected; questions must be generated only from cited evidence."
        if concepts:
            note += f" Key concepts from retrieved evidence: {', '.join(concepts[:6])}."
        if structured["tables"] or structured["charts"]:
            note += f" Structured evidence available: {structured['tables']} table(s), {structured['charts']} chart(s)."
        if wants_comparison:
            note += " Comparison intent detected; answer should separate sources and cite each side."
        analysis = ObjectiveAnalysis(
            module="research",
            findings=concepts[:8],
            missing_evidence=[],
            recommended_tools=[
                AgentToolCall(tool_name="concept_map", arguments={"concepts": concepts[:8]}, reason="Build study structure."),
                AgentToolCall(tool_name="quiz_generator", arguments={"grounded_only": True}, reason="Create evidence-backed practice questions."),
            ],
        )
        return note, AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="StudyAgent",
            action="study_context",
            output_summary=note,
            metadata={
                "wants_quiz": wants_quiz,
                "wants_comparison": wants_comparison,
                "concepts": concepts,
                "study_questions": self._study_questions(chunks) if wants_quiz else [],
                "deep_summary": self._deep_summary(chunks),
                "table_chart_explanations": self._table_chart_explanations(chunks),
                "comparison_sources": sorted({chunk.document_id for chunk in chunks}) if wants_comparison else [],
                **structured,
                "structured_output": analysis.model_dump(),
            },
        )

    @staticmethod
    def _concepts(chunks) -> list[str]:
        candidates = []
        for chunk in chunks:
            candidates.extend(chunk.section_path or [])
            for match in re.findall(r"\b[A-Z][A-Za-z]{4,}(?:\s+[A-Z][A-Za-z]{4,})?\b", chunk.text):
                candidates.append(match)
        seen = []
        for item in candidates:
            if item not in seen:
                seen.append(item)
        return seen[:12]

    @staticmethod
    def _structured_counts(chunks) -> dict[str, int]:
        tables = sum(1 for chunk in chunks if chunk.table_json or chunk.content_type == "table")
        charts = sum(1 for chunk in chunks if chunk.chart_series or chunk.content_type == "chart")
        return {"tables": tables, "charts": charts}

    @staticmethod
    def _study_questions(chunks) -> list[dict[str, str]]:
        questions = []
        for chunk in chunks[:5]:
            concept = (chunk.section_path or [chunk.filename])[0]
            questions.append(
                {
                    "question": f"What does the evidence say about {concept} on page {chunk.page_number}?",
                    "answer_hint": chunk.text[:180],
                    "citation": f"{chunk.filename} p.{chunk.page_number}",
                }
            )
        return questions

    @staticmethod
    def _deep_summary(chunks) -> list[dict[str, str]]:
        return [
            {
                "point": chunk.text[:220],
                "citation": f"{chunk.filename} p.{chunk.page_number}",
            }
            for chunk in chunks[:6]
        ]

    @staticmethod
    def _table_chart_explanations(chunks) -> list[dict[str, str]]:
        explanations = []
        for chunk in chunks:
            if chunk.table_json:
                explanations.append({"type": "table", "title": chunk.table_json.get("title", "Table"), "citation": f"{chunk.filename} p.{chunk.page_number}"})
            if chunk.chart_series:
                explanations.append({"type": "chart", "title": chunk.chart_series.get("title", "Chart"), "citation": f"{chunk.filename} p.{chunk.page_number}"})
        return explanations[:8]


class EnterpriseAgent:
    def annotate(self, question: str, chunks) -> tuple[str, AgentStep]:
        source_ids = sorted({chunk.document_id for chunk in chunks})
        policy_terms = sorted({term for term in ("policy", "compliance", "audit", "approval", "security", "privacy", "retention") if term in question.lower() or any(term in chunk.text.lower() for chunk in chunks)})
        note = "Enterprise mode: prioritize policy traceability, source governance, compliance wording, and uncertainty disclosure."
        if policy_terms:
            note += f" Governance topics detected: {', '.join(policy_terms)}."
        analysis = ObjectiveAnalysis(
            module="enterprise",
            findings=policy_terms,
            missing_evidence=[],
            recommended_tools=[
                AgentToolCall(tool_name="policy_trace", arguments={"source_document_ids": source_ids}, reason="Preserve audit trail."),
                AgentToolCall(tool_name="compliance_evidence", arguments={"date": date.today().isoformat()}, reason="Package citations for governance review."),
            ],
        )
        return note, AgentStep(
            step_id=str(uuid.uuid4()),
            agent_name="EnterpriseAgent",
            action="enterprise_trace_context",
            output_summary=note,
            metadata={
                "source_count": len(source_ids),
                "source_document_ids": source_ids,
                "policy_terms": policy_terms,
                "compliance_trail": [
                    {"document_id": chunk.document_id, "page_number": chunk.page_number, "content_type": chunk.content_type}
                    for chunk in chunks[:12]
                ],
                "policy_answer_packet": {
                    "source_document_ids": source_ids,
                    "policy_terms": policy_terms,
                    "approval_caveat": "Treat this as source-backed analysis, not final policy approval.",
                    "uncertainty": "Missing evidence must remain explicitly marked in the final answer.",
                },
                "trace_date": date.today().isoformat(),
                "structured_output": analysis.model_dump(),
            },
        )
