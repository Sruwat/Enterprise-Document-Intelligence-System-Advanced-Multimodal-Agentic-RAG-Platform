from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PageArtifacts:
    section_path: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    clauses: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    definitions: list[dict[str, Any]] = field(default_factory=list)
    legal_metadata: dict[str, Any] = field(default_factory=dict)


class DocumentArtifactExtractor:
    RISK_TERMS = {
        "termination": "termination",
        "liability": "liability",
        "indemnity": "indemnity",
        "penalty": "penalty",
        "breach": "breach",
        "confidential": "confidentiality",
        "jurisdiction": "jurisdiction",
        "payment": "payment",
        "warranty": "warranty",
        "force majeure": "force_majeure",
        "governing law": "governing_law",
    }

    CLAUSE_PATTERN = re.compile(
        r"(?P<title>(?:\d+(?:\.\d+)*\s+)?(?:Termination|Payment|Fees?|Liability|Indemnity|Confidentiality|Warranty|Governing Law|Jurisdiction|Force Majeure|Data Protection|Obligations?))"
        r"[:.\-\s]+(?P<body>.{40,700}?)(?=(?:\s+\d+(?:\.\d+)*\s+[A-Z][A-Za-z ]{3,40}[:.\-])|$)",
        re.IGNORECASE | re.DOTALL,
    )

    def extract(self, raw_text: str, normalized_text: str, page_number: int) -> PageArtifacts:
        source = raw_text or normalized_text
        normalized = normalized_text or self._normalize(source)
        tables = self.extract_tables(source, page_number)
        charts = self.extract_charts(normalized, page_number)
        clauses = self.extract_clauses(normalized, page_number)
        risks = self.extract_risks(normalized, page_number)
        definitions = self.extract_definitions(normalized, page_number)
        legal_metadata = self.extract_legal_metadata(normalized, page_number)
        return PageArtifacts(
            section_path=self.extract_section_path(source, normalized),
            tables=tables,
            charts=charts,
            clauses=clauses,
            risks=risks,
            definitions=definitions,
            legal_metadata=legal_metadata,
        )

    def extract_section_path(self, raw_text: str, normalized_text: str) -> list[str]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        for line in lines[:20]:
            if re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z0-9 ,/&()-]{3,80}$", line):
                return [line]
            if line.isupper() and 4 <= len(line) <= 80:
                return [line.title()]
        heading = re.search(r"\b(termination|liability|confidentiality|payment|summary|findings|results|policy|scope)\b", normalized_text, re.IGNORECASE)
        return [heading.group(1).title()] if heading else []

    def extract_tables(self, raw_text: str, page_number: int) -> list[dict[str, Any]]:
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        candidate_rows: list[list[str]] = []
        for line in lines:
            cells = self._split_table_line(line)
            if len(cells) >= 2 and (len(cells) >= 3 or any(re.search(r"\d", cell) for cell in cells)):
                candidate_rows.append(cells)
        if len(candidate_rows) < 2:
            return []
        header = candidate_rows[0]
        rows = candidate_rows[1:12]
        return [
            {
                "artifact_id": str(uuid.uuid4()),
                "detected_by": "text_table_layout",
                "title": f"Detected table on page {page_number}",
                "text": " | ".join(header),
                "headers": header,
                "rows": rows,
                "row_count": len(candidate_rows) - 1,
                "bbox": self._line_bbox(raw_text, " ".join(header), height_lines=max(2, min(len(candidate_rows), 12))),
            }
        ]

    def extract_charts(self, text: str, page_number: int) -> list[dict[str, Any]]:
        if not re.search(r"\b(chart|graph|axis|trend|peaked|increase|decrease|quarter|monthly|annual|series)\b", text, re.IGNORECASE):
            return []
        points = []
        for label, value, unit in re.findall(
            r"\b(Q[1-4]|20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)\b\s*[:=\-]?\s*(\d+(?:\.\d+)?)\s*([A-Za-z%/]+)?",
            text,
            flags=re.IGNORECASE,
        ):
            points.append({"label": label, "value": float(value), "unit": unit or ""})
        return [
            {
                "artifact_id": str(uuid.uuid4()),
                "detected_by": "chart_language_and_values",
                "title": f"Detected chart/series on page {page_number}",
                "text": self._sentence_with_keywords(text, ("chart", "graph", "trend", "peaked", "increase", "decrease"))[:500],
                "points": points[:24],
                "point_count": len(points),
                "bbox": self._keyword_bbox(text, ("chart", "graph", "trend", "axis", "series")),
            }
        ]

    def extract_clauses(self, text: str, page_number: int) -> list[dict[str, Any]]:
        clauses = []
        for match in self.CLAUSE_PATTERN.finditer(text):
            title = self._clean(match.group("title"))
            body = self._clean(match.group("body"))
            if len(body) < 30:
                continue
            clauses.append(
                {
                    "artifact_id": str(uuid.uuid4()),
                    "detected_by": "contract_clause_patterns",
                    "title": title,
                    "text": body[:1200],
                    "page_number": page_number,
                    "risk_tags": self._risk_tags(f"{title} {body}"),
                    "bbox": self._keyword_bbox(text, (title,)),
                }
            )
        return clauses[:12]

    def extract_risks(self, text: str, page_number: int) -> list[dict[str, Any]]:
        risks = []
        for term, tag in self.RISK_TERMS.items():
            if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                sentence = self._sentence_with_keywords(text, (term,))
                risks.append(
                    {
                        "artifact_id": str(uuid.uuid4()),
                        "detected_by": "risk_term_scan",
                        "title": tag.replace("_", " ").title(),
                        "text": sentence[:700],
                        "tag": tag,
                        "severity": self._severity(sentence),
                        "page_number": page_number,
                        "bbox": self._keyword_bbox(text, (term,)),
                    }
                )
        return risks

    def extract_definitions(self, text: str, page_number: int) -> list[dict[str, Any]]:
        definitions = []
        for term, body in re.findall(r'"([^"]{3,80})"\s+(?:means|shall mean|refers to)\s+(.{20,300}?)(?:\.|;)', text, flags=re.IGNORECASE):
            definitions.append(
                {
                    "artifact_id": str(uuid.uuid4()),
                    "detected_by": "definition_pattern",
                    "title": term.strip(),
                    "text": self._clean(body),
                    "page_number": page_number,
                    "bbox": self._keyword_bbox(text, (term,)),
                }
            )
        return definitions[:12]

    def extract_legal_metadata(self, text: str, page_number: int) -> dict[str, Any]:
        parties = self._extract_parties(text)
        dates = self._extract_key_dates(text)
        obligations = self._extract_obligations(text)
        return {
            "page_number": page_number,
            "parties": parties,
            "effective_date": dates.get("effective_date"),
            "termination_date": dates.get("termination_date"),
            "obligations": obligations,
            "penalties": self._extract_sentences(text, ("penalty", "liquidated damages", "late fee", "fine")),
            "governing_law": self._first_match(text, (r"governed by the laws of\s+([^.;]{3,80})", r"governing law\s*[:\-]\s*([^.;]{3,80})")),
            "notice_period": self._first_match(text, (r"(\d+\s+days?[^.;]{0,80}notice)", r"notice period\s*[:\-]\s*([^.;]{3,80})")),
            "renewal_terms": self._first_match(text, (r"(?:renewal|renews?|auto-renewal)[^.]{0,180}",)),
            "payment_terms": self._first_match(text, (r"(?:payment|fees?|invoice)[^.]{0,220}",)),
            "jurisdiction": self._first_match(text, (r"jurisdiction(?: of| shall be| is)?\s*[:\-]?\s*([^.;]{3,100})",)),
        }

    def _risk_tags(self, text: str) -> list[str]:
        return [tag for term, tag in self.RISK_TERMS.items() if re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)]

    @staticmethod
    def _split_table_line(line: str) -> list[str]:
        if "|" in line:
            return [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
        if "\t" in line:
            return [cell.strip() for cell in line.split("\t") if cell.strip()]
        return [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]

    @staticmethod
    def _sentence_with_keywords(text: str, keywords: tuple[str, ...]) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sentence in sentences:
            if any(keyword.lower() in sentence.lower() for keyword in keywords):
                return DocumentArtifactExtractor._clean(sentence)
        return DocumentArtifactExtractor._clean(text[:500])

    @staticmethod
    def _severity(text: str) -> str:
        lowered = text.lower()
        if any(term in lowered for term in ("unlimited", "penalty", "breach", "terminate immediately", "liable for all")):
            return "high"
        if any(term in lowered for term in ("may", "material", "confidential", "indemn")):
            return "medium"
        return "low"

    @staticmethod
    def _extract_parties(text: str) -> list[str]:
        parties: list[str] = []
        patterns = (
            r"(?:between|by and between)\s+([A-Z][A-Za-z0-9&., ]{2,100}?)\s+and\s+([A-Z][A-Za-z0-9&., ]{2,100}?)(?:[.;,\n]|$)",
            r"(?:client|customer|vendor|supplier|contractor|company|party)\s*[:\-]\s*([A-Z][A-Za-z0-9&., ]{2,100})",
        )
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                values = match if isinstance(match, tuple) else (match,)
                parties.extend(DocumentArtifactExtractor._clean(value) for value in values)
        return list(dict.fromkeys(party for party in parties if party))[:10]

    @staticmethod
    def _extract_key_dates(text: str) -> dict[str, str | None]:
        date_pattern = r"((?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})|(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}))"
        effective = re.search(rf"(?:effective date|commences? on|starts? on)\s*[:\-]?\s*{date_pattern}", text, flags=re.IGNORECASE)
        termination = re.search(rf"(?:termination date|expires? on|ends? on)\s*[:\-]?\s*{date_pattern}", text, flags=re.IGNORECASE)
        return {
            "effective_date": effective.group(1) if effective else None,
            "termination_date": termination.group(1) if termination else None,
        }

    @staticmethod
    def _extract_obligations(text: str) -> list[dict[str, Any]]:
        obligations = []
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if re.search(r"\b(shall|must|required to|agrees to|responsible for|within \d+ days)\b", sentence, re.IGNORECASE):
                obligations.append({"text": DocumentArtifactExtractor._clean(sentence)[:400], "confidence": 0.72})
        return obligations[:12]

    @staticmethod
    def _extract_sentences(text: str, keywords: tuple[str, ...]) -> list[str]:
        return [
            DocumentArtifactExtractor._clean(sentence)[:400]
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if any(keyword.lower() in sentence.lower() for keyword in keywords)
        ][:8]

    @staticmethod
    def _first_match(text: str, patterns: tuple[str, ...]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return DocumentArtifactExtractor._clean(match.group(1) if match.groups() else match.group(0))[:240]
        return None

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip(" :-")

    @staticmethod
    def _line_bbox(text: str, needle: str, height_lines: int = 2) -> list[float]:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return [0.0, 0.0, 1.0, 1.0]
        needle_lower = needle.lower()
        line_index = next((index for index, line in enumerate(lines) if needle_lower in line.lower()), 0)
        line_height = 1.0 / max(len(lines), 1)
        top = max(0.0, line_index * line_height)
        bottom = min(1.0, (line_index + max(height_lines, 1)) * line_height)
        return [0.05, round(top, 4), 0.95, round(bottom, 4)]

    @staticmethod
    def _keyword_bbox(text: str, keywords: tuple[str, ...]) -> list[float]:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return [0.0, 0.0, 1.0, 1.0]
        lowered_keywords = [keyword.lower() for keyword in keywords if keyword]
        line_index = next(
            (
                index
                for index, line in enumerate(lines)
                if any(keyword in line.lower() for keyword in lowered_keywords)
            ),
            0,
        )
        line_height = 1.0 / max(len(lines), 1)
        top = max(0.0, line_index * line_height)
        bottom = min(1.0, top + max(line_height * 2, 0.08))
        return [0.05, round(top, 4), 0.95, round(bottom, 4)]
