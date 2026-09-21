"""Privacy-aware, user-isolated long-term memory service."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List


SENSITIVE_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:password|passwd|api[_ -]?key|secret)\s*[:=]\s*\S+", re.IGNORECASE),
]


def validate_memory_content(content: str) -> str:
    normalized = " ".join(content.split())
    if not normalized:
        raise ValueError("Long-term memory cannot be empty")
    if len(normalized) > 2000:
        raise ValueError("Long-term memory exceeds 2000 characters")
    if any(pattern.search(normalized) for pattern in SENSITIVE_PATTERNS):
        raise ValueError("Potential secret detected; long-term memory was not stored")
    return normalized


class LongTermMemoryService:
    def __init__(
        self,
        store_factory: Callable[[], Any] | None = None,
        embedding_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.store_factory = store_factory
        self.embedding_factory = embedding_factory
        self._store = None
        self._embedding = None

    @property
    def store(self):
        if self._store is None:
            if self.store_factory is not None:
                self._store = self.store_factory()
            else:
                from src.database.memory_vector_db import MemoryVectorStore

                self._store = MemoryVectorStore()
        return self._store

    @property
    def embedding(self):
        if self._embedding is None:
            if self.embedding_factory is not None:
                self._embedding = self.embedding_factory()
            else:
                from src.embedding import get_embedding_service

                self._embedding = get_embedding_service()
        return self._embedding

    def add(
        self,
        *,
        user_id: int,
        content: str,
        memory_type: str = "insight",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        normalized = validate_memory_content(content)
        vector = self.embedding.embed_query(normalized)
        if not vector:
            raise RuntimeError("Unable to embed long-term memory")
        memory_id = self.store.insert(
            user_id=int(user_id),
            text=normalized,
            embedding=vector,
            memory_type=memory_type[:64],
            metadata=metadata or {},
        )
        return {"id": memory_id, "memory_type": memory_type[:64], "stored": True}

    def recall(self, *, user_id: int, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not query.strip():
            return []
        vector = self.embedding.embed_query(query)
        if not vector:
            return []
        return self.store.search(
            user_id=int(user_id),
            embedding=vector,
            top_k=min(max(int(top_k), 1), 10),
        )
