"""Dense, BM25 keyword, and weighted RRF hybrid retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from src.models.vector import SearchResult


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:/+\-]*|[\u4e00-\u9fff]+", re.IGNORECASE)


def tokenize(text: str) -> List[str]:
    """Tokenize standards identifiers, English terms, and CJK bigrams."""
    tokens: List[str] = []
    for match in TOKEN_PATTERN.findall((text or "").casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            tokens.extend([match] if len(match) == 1 else [match[index:index + 2] for index in range(len(match) - 1)])
        else:
            tokens.append(match)
    return tokens


def bm25_scores(query: str, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> List[float]:
    """Calculate Okapi BM25 scores without a third-party runtime dependency."""
    if not documents:
        return []
    query_terms = list(dict.fromkeys(tokenize(query)))
    tokenized = [tokenize(document) for document in documents]
    if not query_terms:
        return [0.0] * len(documents)

    average_length = sum(len(document) for document in tokenized) / max(len(tokenized), 1)
    average_length = average_length or 1.0
    document_frequency = {
        term: sum(1 for document in tokenized if term in set(document)) for term in query_terms
    }
    scores = []
    total = len(tokenized)
    for document in tokenized:
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_document_frequency = math.log(1 + (total - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * len(document) / average_length)
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[SearchResult]],
    *,
    weights: Sequence[float] | None = None,
    top_k: int = 10,
    rank_constant: int = 60,
) -> List[SearchResult]:
    """Fuse result rankings while preserving each unique chunk's payload."""
    weights = list(weights or [1.0] * len(ranked_lists))
    if len(weights) != len(ranked_lists):
        raise ValueError("weights must match ranked_lists")
    combined: Dict[str, Dict[str, Any]] = {}
    for channel_index, results in enumerate(ranked_lists):
        for rank, result in enumerate(results, start=1):
            item = combined.setdefault(result.id, {"result": result, "score": 0.0, "channels": []})
            item["score"] += weights[channel_index] / (rank_constant + rank)
            item["channels"].append(channel_index)

    fused = []
    for item in sorted(combined.values(), key=lambda value: (-value["score"], value["result"].id))[:top_k]:
        source = item["result"]
        metadata = dict(source.metadata or {})
        metadata["retrieval_channels"] = item["channels"]
        fused.append(
            SearchResult(
                id=source.id,
                text=source.text,
                score=float(item["score"]),
                metadata=metadata,
            )
        )
    return fused


class KeywordRetriever:
    """Fetch lexical candidates from PostgreSQL and rank them with BM25."""

    def __init__(self, session_factory: Callable[[], Any] | None = None, candidate_limit: int = 1000):
        self._session_factory = session_factory
        self.candidate_limit = min(max(int(candidate_limit), 50), 5000)

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from src.database.sql_session import SessionLocal

        return SessionLocal()

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        kb_id: Optional[int] = None,
        kb_ids: Optional[List[int]] = None,
    ) -> List[SearchResult]:
        from sqlalchemy import or_
        from src.database.models import DocumentChunk, KnowledgeDocument

        selected_kb_ids = sorted({int(value) for value in (kb_ids or ([kb_id] if kb_id is not None else []))})
        if not selected_kb_ids:
            return []
        lexical_terms = [term for term in dict.fromkeys(tokenize(query)) if len(term) > 1][:12]
        if not lexical_terms:
            return []

        db = self._session()
        try:
            escaped_terms = [term.replace("%", r"\%").replace("_", r"\_") for term in lexical_terms]
            clauses = [DocumentChunk.content.ilike(f"%{term}%", escape="\\") for term in escaped_terms]
            rows = (
                db.query(DocumentChunk, KnowledgeDocument)
                .join(KnowledgeDocument, DocumentChunk.doc_id == KnowledgeDocument.id)
                .filter(KnowledgeDocument.kb_id.in_(selected_kb_ids), or_(*clauses))
                .limit(self.candidate_limit)
                .all()
            )
        finally:
            db.close()

        scores = bm25_scores(query, [chunk.content for chunk, _ in rows])
        ranked = sorted(zip(rows, scores), key=lambda item: item[1], reverse=True)
        return [
            SearchResult(
                id=chunk.vector_id or chunk.chunk_uid,
                text=chunk.content,
                score=float(score),
                metadata={
                    "kb_id": document.kb_id,
                    "doc_uid": document.doc_uid,
                    "filename": document.filename,
                    "file_type": document.file_type,
                    "page_num": chunk.page_num,
                    "retrieval": "bm25",
                },
            )
            for (chunk, document), score in ranked[:top_k]
            if score > 0
        ]


class HybridRetriever:
    """Select dense/keyword retrieval or combine both through weighted RRF."""

    def __init__(
        self,
        dense_retriever: Any | None = None,
        keyword_retriever: Any | None = None,
    ) -> None:
        self.dense = dense_retriever
        self.keyword = keyword_retriever or KeywordRetriever()

    def _dense_retriever(self) -> Any:
        if self.dense is None:
            from src.retrieval.vector_retriever import VectorRetriever

            self.dense = VectorRetriever()
        return self.dense

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        kb_id: Optional[int] = None,
        kb_ids: Optional[List[int]] = None,
        *,
        strategy: str = "hybrid",
        dense_weight: float = 0.5,
    ) -> List[SearchResult]:
        normalized_strategy = str(strategy or "hybrid").casefold()
        if normalized_strategy not in {"vector", "keyword", "hybrid"}:
            raise ValueError("strategy must be vector, keyword, or hybrid")
        limit = min(max(int(top_k), 1), 100)
        if normalized_strategy == "vector":
            return self._dense_retriever().retrieve(query, limit, kb_id, kb_ids)
        if normalized_strategy == "keyword":
            return self.keyword.retrieve(query, limit, kb_id, kb_ids)

        weight = min(max(float(dense_weight), 0.0), 1.0)
        candidate_k = min(limit * 3, 100)
        if weight == 0:
            return self.keyword.retrieve(query, limit, kb_id, kb_ids)
        if weight == 1:
            return self._dense_retriever().retrieve(query, limit, kb_id, kb_ids)
        dense_results = self._dense_retriever().retrieve(query, candidate_k, kb_id, kb_ids)
        keyword_results = self.keyword.retrieve(query, candidate_k, kb_id, kb_ids)
        return reciprocal_rank_fusion(
            [dense_results, keyword_results],
            weights=[weight, 1.0 - weight],
            top_k=limit,
        )
