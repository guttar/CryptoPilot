import unittest

from src.services.long_term_memory_service import LongTermMemoryService, validate_memory_content


class FakeEmbedding:
    def embed_query(self, text):
        return [float(len(text)), 1.0]


class FakeStore:
    def __init__(self):
        self.inserted = []
        self.searched = []

    def insert(self, **record):
        self.inserted.append(record)
        return "memory-1"

    def search(self, **query):
        self.searched.append(query)
        return [{"id": "memory-1", "text": "Prefer standards citations", "score": 0.91}]


class LongTermMemoryTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.service = LongTermMemoryService(
            store_factory=lambda: self.store,
            embedding_factory=FakeEmbedding,
        )

    def test_add_normalizes_and_scopes_memory(self):
        result = self.service.add(user_id=7, content="  Prefer   RFC citations  ")
        self.assertTrue(result["stored"])
        self.assertEqual(self.store.inserted[0]["user_id"], 7)
        self.assertEqual(self.store.inserted[0]["text"], "Prefer RFC citations")

    def test_recall_always_passes_user_filter(self):
        memories = self.service.recall(user_id=42, query="citation style", top_k=99)
        self.assertEqual(memories[0]["id"], "memory-1")
        self.assertEqual(self.store.searched[0]["user_id"], 42)
        self.assertEqual(self.store.searched[0]["top_k"], 10)

    def test_rejects_api_keys(self):
        with self.assertRaisesRegex(ValueError, "Potential secret"):
            validate_memory_content("api_key = super-secret-value")

    def test_rejects_private_keys(self):
        with self.assertRaisesRegex(ValueError, "Potential secret"):
            validate_memory_content("-----BEGIN PRIVATE KEY----- ABC")


if __name__ == "__main__":
    unittest.main()
