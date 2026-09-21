import unittest

from src.models.vector import SearchResult
from src.retrieval.hybrid_retriever import (
    HybridRetriever,
    bm25_scores,
    reciprocal_rank_fusion,
    tokenize,
)


def result(chunk_id, score, channel):
    return SearchResult(
        id=chunk_id,
        score=score,
        text=f"text-{chunk_id}",
        metadata={"retrieval": channel},
    )


class FakeRetriever:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def retrieve(self, query, top_k, kb_id, kb_ids):
        self.calls.append((query, top_k, kb_id, kb_ids))
        return self.results[:top_k]


class HybridRetrieverTests(unittest.TestCase):
    def test_tokenize_preserves_protocol_names_and_cjk_bigrams(self):
        tokens = tokenize("TLS 1.3 密钥派生 HKDF-SHA256")
        self.assertIn("tls", tokens)
        self.assertIn("1.3", tokens)
        self.assertIn("密钥", tokens)
        self.assertIn("钥派", tokens)
        self.assertIn("hkdf-sha256", tokens)

    def test_bm25_ranks_exact_security_terms_first(self):
        scores = bm25_scores(
            "TLS HKDF",
            ["TLS 1.3 uses HKDF for key derivation", "RSA signing and certificate notes"],
        )
        self.assertGreater(scores[0], scores[1])

    def test_rrf_deduplicates_and_rewards_cross_channel_hits(self):
        fused = reciprocal_rank_fusion(
            [
                [result("dense-only", 0.1, "dense"), result("shared", 0.2, "dense")],
                [result("shared", 9.0, "bm25"), result("keyword-only", 4.0, "bm25")],
            ],
            weights=[0.5, 0.5],
            top_k=3,
        )
        self.assertEqual(fused[0].id, "shared")
        self.assertEqual(len({item.id for item in fused}), 3)
        self.assertEqual(fused[0].metadata["retrieval_channels"], [0, 1])

    def test_hybrid_weight_controls_rrf_order(self):
        dense = FakeRetriever([result("dense", 1.0, "dense")])
        keyword = FakeRetriever([result("keyword", 2.0, "bm25")])
        retriever = HybridRetriever(dense_retriever=dense, keyword_retriever=keyword)

        mostly_dense = retriever.retrieve("test", 2, kb_ids=[1], dense_weight=0.9)
        mostly_keyword = retriever.retrieve("test", 2, kb_ids=[1], dense_weight=0.1)

        self.assertEqual(mostly_dense[0].id, "dense")
        self.assertEqual(mostly_keyword[0].id, "keyword")

    def test_strategy_can_skip_one_channel(self):
        dense = FakeRetriever([result("dense", 1.0, "dense")])
        keyword = FakeRetriever([result("keyword", 2.0, "bm25")])
        retriever = HybridRetriever(dense_retriever=dense, keyword_retriever=keyword)

        results = retriever.retrieve("test", 2, kb_ids=[1], strategy="keyword")

        self.assertEqual(results[0].id, "keyword")
        self.assertEqual(dense.calls, [])


if __name__ == "__main__":
    unittest.main()
