"""Dedicated Milvus collection for user-scoped long-term Agent memory."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

from src.settings import settings


class MemoryVectorStore:
    alias = "agent_memory"

    def __init__(self) -> None:
        connections.connect(
            alias=self.alias,
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            timeout=10,
        )
        self.collection = self._collection()

    def _collection(self) -> Collection:
        name = settings.LONG_TERM_MEMORY_COLLECTION
        if not utility.has_collection(name, using=self.alias):
            schema = CollectionSchema(
                [
                    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                    FieldSchema(name="user_id", dtype=DataType.INT64),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=settings.MILVUS_DIMENSION),
                    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
                    FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="created_at", dtype=DataType.INT64),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ],
                description="User-scoped long-term Agent memories",
            )
            collection = Collection(name, schema=schema, using=self.alias)
            collection.create_index(
                field_name="embedding",
                index_params={
                    "index_type": "HNSW",
                    "metric_type": "COSINE",
                    "params": {"M": 16, "efConstruction": 128},
                },
            )
            collection.create_index(field_name="user_id", index_name="memory_user_id_index")
        else:
            collection = Collection(name, using=self.alias)
        collection.load()
        return collection

    def insert(
        self,
        *,
        user_id: int,
        text: str,
        embedding: List[float],
        memory_type: str,
        metadata: Dict[str, Any],
    ) -> str:
        memory_id = str(uuid.uuid4())
        self.collection.insert(
            [
                [memory_id],
                [int(user_id)],
                [embedding],
                [text],
                [memory_type],
                [int(time.time())],
                [metadata],
            ]
        )
        self.collection.flush()
        return memory_id

    def search(self, *, user_id: int, embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        results = self.collection.search(
            data=[embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": max(32, top_k * 4)}},
            limit=top_k,
            expr=f"user_id == {int(user_id)}",
            output_fields=["text", "memory_type", "created_at", "metadata"],
        )
        memories = []
        for hits in results:
            for hit in hits:
                memories.append(
                    {
                        "id": hit.id,
                        "text": hit.entity.get("text"),
                        "memory_type": hit.entity.get("memory_type"),
                        "created_at": hit.entity.get("created_at"),
                        "metadata": hit.entity.get("metadata") or {},
                        "score": float(hit.score),
                    }
                )
        return memories
