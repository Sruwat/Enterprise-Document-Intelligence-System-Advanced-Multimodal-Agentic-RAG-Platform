from __future__ import annotations

import math
import re
from collections import Counter, defaultdict


TOKEN_PATTERN = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


class BM25IndexStore:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_lengths: dict[str, int] = {}
        self.term_freqs: dict[str, Counter[str]] = {}
        self.inverted_index: dict[str, dict[str, int]] = defaultdict(dict)
        self.avg_doc_length: float = 0.0

    def upsert_documents(self, documents: dict[str, str]) -> None:
        for doc_id, text in documents.items():
            tokens = tokenize(text)
            freqs = Counter(tokens)
            self.term_freqs[doc_id] = freqs
            self.doc_lengths[doc_id] = len(tokens)
        self._rebuild_inverted_index()

    def remove_documents(self, doc_ids: list[str]) -> None:
        changed = False
        for doc_id in doc_ids:
            if doc_id in self.term_freqs:
                changed = True
                self.term_freqs.pop(doc_id, None)
                self.doc_lengths.pop(doc_id, None)
        if changed:
            self._rebuild_inverted_index()

    def _rebuild_inverted_index(self) -> None:
        self.inverted_index = defaultdict(dict)
        total_len = 0
        for doc_id, freqs in self.term_freqs.items():
            total_len += self.doc_lengths.get(doc_id, 0)
            for token, freq in freqs.items():
                self.inverted_index[token][doc_id] = freq
        self.avg_doc_length = total_len / max(len(self.doc_lengths), 1)

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        tokens = tokenize(query)
        scores: dict[str, float] = defaultdict(float)
        doc_count = max(len(self.doc_lengths), 1)
        for token in tokens:
            postings = self.inverted_index.get(token, {})
            if not postings:
                continue
            doc_freq = len(postings)
            idf = math.log(1 + (doc_count - doc_freq + 0.5) / (doc_freq + 0.5))
            for doc_id, freq in postings.items():
                doc_len = self.doc_lengths[doc_id]
                denom = freq + self.k1 * (1 - self.b + self.b * (doc_len / max(self.avg_doc_length, 1)))
                scores[doc_id] += idf * ((freq * (self.k1 + 1)) / max(denom, 1e-9))
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]

    def size(self) -> int:
        return len(self.doc_lengths)
