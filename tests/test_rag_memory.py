import unittest
from types import SimpleNamespace
from src.services.rag_service import RAGService


class Memory:
    def __init__(self):
        self.calls = []
        self.writes = []
    def retrieve_long_term_memory(self, **kwargs):
        self.calls.append(kwargs)
        return [{"text": "Prefer RFC citations"}]
    def add_short_term_memory(self, *args):
        self.writes.append(args)


class Model:
    def __init__(self):
        self.prompts = []
    def generate_general_response(self, query, context):
        self.prompts.append(context)
        return "answer"
    async def generate_stream(self, prompt):
        self.prompts.append(prompt)
        yield "answer"


class RAGMemoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = RAGService.__new__(RAGService)
        self.service.memory = Memory()
        self.service.llm_client = Model()
        self.config = {"memory_config": {"enable_short_term": False, "enable_long_term": True}}

    def test_sync_query_scopes_long_term_recall_and_respects_disabled_short_term(self):
        self.service.query("q", assistant_config=self.config, user_id=42)
        self.assertEqual(self.service.memory.calls[0]["user_id"], 42)
        self.assertIn("不作为外部事实证据", self.service.llm_client.prompts[0])
        self.assertEqual(self.service.memory.writes, [])

    async def test_stream_query_also_receives_user_scoped_memory(self):
        events = [event async for event in self.service.query_stream("q", assistant_config=self.config, user_id=7)]
        self.assertEqual(self.service.memory.calls[0]["user_id"], 7)
        self.assertIn("Prefer RFC citations", self.service.llm_client.prompts[0])
        self.assertEqual(events[-1], {"type": "done"})

    def test_missing_user_or_disabled_memory_does_not_access_store(self):
        self.assertEqual(self.service._long_term_context(None, "q", {"enable_long_term": True}), "")
        self.assertEqual(self.service._long_term_context(1, "q", {}), "")
        self.assertEqual(self.service.memory.calls, [])

    def test_recall_failure_degrades_without_failing_question(self):
        def fail(**kwargs):
            raise RuntimeError("offline")
        self.service.memory.retrieve_long_term_memory = fail
        self.assertEqual(self.service.query("q", assistant_config=self.config, user_id=1)["answer"], "answer")
