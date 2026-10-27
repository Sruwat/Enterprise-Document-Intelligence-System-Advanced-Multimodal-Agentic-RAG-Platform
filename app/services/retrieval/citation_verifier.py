from __future__ import annotations

from typing import Any

from app.core.schemas import ChunkRecord, Citation


class CitationVerifier:
    def verify(self, *, answer: str, citations: list[Citation], chunks: list[ChunkRecord]) -> dict[str, Any]:
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        source_pairs = {(chunk.document_id, int(chunk.page_number)) for chunk in chunks}
        checks = []
        for citation in citations:
            anchored = citation.chunk_id in chunk_ids or (citation.document_id, int(citation.page_number)) in source_pairs
            snippet_supported = self._snippet_supported(citation.snippet, chunks)
            checks.append(
                {
                    "chunk_id": citation.chunk_id,
                    "document_id": citation.document_id,
                    "page_number": citation.page_number,
                    "anchored": anchored,
                    "snippet_supported": snippet_supported,
                    "status": "ok" if anchored and snippet_supported else "failed",
                }
            )
        return {
            "citation_count": len(citations),
            "verified_count": sum(1 for check in checks if check["status"] == "ok"),
            "all_verified": bool(citations) and all(check["status"] == "ok" for check in checks),
            "answer_has_source_marker": "[source:" in answer.lower(),
            "claim_checks": checks,
        }

    @staticmethod
    def _snippet_supported(snippet: str, chunks: list[ChunkRecord]) -> bool:
        if not snippet:
            return False
        needle_tokens = {token.lower() for token in snippet.split() if len(token) > 3}
        if not needle_tokens:
            return True
        haystack = " ".join(chunk.text.lower() for chunk in chunks)
        matched = sum(1 for token in needle_tokens if token in haystack)
        return matched / max(len(needle_tokens), 1) >= 0.35

