import unittest
from types import SimpleNamespace

from src.services.knowledge_search_service import KnowledgeSearchService


class FakeRetriever:
    def retrieve(self, query, top_k, kb_id, kb_ids, **options):
        self.call = {"query": query, "top_k": top_k, "kb_id": kb_id, "kb_ids": kb_ids, **options}
        return [
            SimpleNamespace(
                id="chunk-1",
                score=0.7,
                text="TLS 1.3 uses HKDF in its key schedule.",
                metadata={"filename": "rfc8446.pdf", "page_num": 91, "category": "protocol"},
            ),
            SimpleNamespace(
                id="chunk-2",
                score=0.3,
                text="An unrelated implementation note.",
                metadata={"filename": "notes.txt", "category": "implementation"},
            ),
        ]


class FakeReranker:
    top_n = 0

    def rerank(self, query, documents):
        return list(reversed(documents))[: self.top_n]


class KnowledgeSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_and_builds_stable_citations(self):
        retriever = FakeRetriever()
        service = KnowledgeSearchService(
            retriever_factory=lambda: retriever,
            reranker_factory=FakeReranker,
        )
        result = await service.search(
            query="TLS key schedule",
            kb_ids=[3, 3],
            top_k=2,
            enable_rerank=True,
            metadata_filters={"category": "protocol"},
        )

        self.assertEqual(retriever.call["kb_ids"], [3])
        self.assertEqual(retriever.call["strategy"], "hybrid")
        self.assertEqual(result["citations"][0]["citation_id"], "KB1")
        self.assertEqual(result["citations"][0]["source"], "rfc8446.pdf")
        self.assertEqual(result["metrics"]["filtered_count"], 1)
        self.assertTrue(result["metrics"]["rerank_applied"])

    async def test_rejects_arbitrary_metadata_expression(self):
        service = KnowledgeSearchService(retriever_factory=FakeRetriever)
        with self.assertRaisesRegex(ValueError, "Unsupported metadata filters"):
            await service.search(
                query="test",
                kb_ids=[1],
                top_k=5,
                metadata_filters={"owner_id": 99},
            )

    async def test_empty_binding_does_not_initialize_vector_store(self):
        service = KnowledgeSearchService(retriever_factory=lambda: self.fail("must not initialize"))
        result = await service.search(query="test", kb_ids=[], top_k=5)
        self.assertEqual(result["citations"], [])

    def test_list_metadata_filters_match_any_requested_value(self):
        item = SimpleNamespace(metadata={"algorithms": ["HKDF", "AES-GCM"]})
        self.assertTrue(
            KnowledgeSearchService._matches_filters(item, {"algorithms": ["RSA", "HKDF"]})
        )
        self.assertFalse(
            KnowledgeSearchService._matches_filters(item, {"algorithms": "SHA-1"})
        )


if __name__ == "__main__":
    unittest.main()
