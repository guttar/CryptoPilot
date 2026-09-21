"""Agent-facing retrieval pipeline with filtering, reranking, and citations."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List


EventCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]
ALLOWED_METADATA_FILTERS = {
    "doc_id",
    "doc_uid",
    "file_type",
    "filename",
    "source",
    "page",
    "protocol",
    "year",
    "category",
}


class KnowledgeSearchService:
    def __init__(
        self,
        retriever_factory: Callable[[], Any] | None = None,
        reranker_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.retriever_factory = retriever_factory
        self.reranker_factory = reranker_factory

    async def _retriever(self):
        if self.retriever_factory is not None:
            return self.retriever_factory()
        from src.retrieval.hybrid_retriever import HybridRetriever

        return await asyncio.to_thread(HybridRetriever)

    def _reranker(self):
        if self.reranker_factory is not None:
            return self.reranker_factory()
        from src.retrieval.reranker import DashScopeReranker

        return DashScopeReranker()

    @staticmethod
    def _matches_filters(result: Any, filters: Dict[str, Any]) -> bool:
        metadata = result.metadata or {}
        for key, expected in filters.items():
            actual = metadata.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif str(actual).casefold() != str(expected).casefold():
                return False
        return True

    @staticmethod
    def _citation(index: int, result: Any) -> Dict[str, Any]:
        metadata = result.metadata or {}
        return {
            "citation_id": f"KB{index}",
            "chunk_id": result.id,
            "text": result.text,
            "score": float(result.score),
            "source": metadata.get("filename") or metadata.get("source") or "unknown",
            "page": metadata.get("page_num") or metadata.get("page"),
            "doc_uid": metadata.get("doc_uid"),
            "metadata": {
                key: metadata[key]
                for key in ("protocol", "year", "category", "file_type")
                if key in metadata
            },
        }

    async def search(
        self,
        *,
        query: str,
        kb_ids: Iterable[int],
        top_k: int,
        enable_rerank: bool = True,
        recall_strategy: str = "hybrid",
        dense_weight: float = 0.5,
        metadata_filters: Dict[str, Any] | None = None,
        emit: EventCallback | None = None,
    ) -> Dict[str, Any]:
        if not query.strip():
            raise ValueError("Search query cannot be empty")
        normalized_kb_ids = sorted({int(value) for value in kb_ids})
        if not normalized_kb_ids:
            return {"query": query, "citations": [], "metrics": {"reason": "no_bound_knowledge_base"}}

        filters = metadata_filters or {}
        unsupported = set(filters) - ALLOWED_METADATA_FILTERS
        if unsupported:
            raise ValueError(f"Unsupported metadata filters: {', '.join(sorted(unsupported))}")

        limit = min(max(int(top_k), 1), 20)
        strategy = str(recall_strategy or "hybrid").casefold()
        if strategy not in {"vector", "keyword", "hybrid"}:
            raise ValueError("recall_strategy must be vector, keyword, or hybrid")
        normalized_dense_weight = min(max(float(dense_weight), 0.0), 1.0)
        candidate_k = min(max(limit * 3, limit), 60)
        if emit:
            await emit(
                "retrieval.started",
                {
                    "query": query,
                    "kb_ids": normalized_kb_ids,
                    "candidate_k": candidate_k,
                    "filters": filters,
                    "recall_strategy": strategy,
                    "dense_weight": normalized_dense_weight,
                },
            )

        started = time.perf_counter()
        retriever = await self._retriever()
        candidates = await asyncio.to_thread(
            retriever.retrieve,
            query,
            candidate_k,
            None,
            normalized_kb_ids,
            strategy=strategy,
            dense_weight=normalized_dense_weight,
        )
        filtered = [item for item in candidates if self._matches_filters(item, filters)]
        filtered_count = len(filtered)
        rerank_applied = False
        rerank_fallback = False

        if enable_rerank and filtered:
            try:
                reranker = self._reranker()
                reranker.top_n = limit
                filtered = await asyncio.to_thread(reranker.rerank, query, filtered)
                rerank_applied = True
            except Exception:
                rerank_fallback = True

        selected = filtered[:limit]
        citations = [self._citation(index, item) for index, item in enumerate(selected, start=1)]
        metrics = {
            "candidate_count": len(candidates),
            "filtered_count": filtered_count,
            "returned_count": len(citations),
            "rerank_applied": rerank_applied,
            "rerank_fallback": rerank_fallback,
            "recall_strategy": strategy,
            "dense_weight": normalized_dense_weight,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if emit:
            await emit("retrieval.completed", {"query": query, **metrics})
        return {"query": query, "citations": citations, "metrics": metrics}
