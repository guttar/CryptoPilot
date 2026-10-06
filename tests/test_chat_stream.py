import asyncio
import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fakeredis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from src.settings import settings
from src.services.memory_service import MemorySystem
from src.services.rag_service import RAGService
from src.llm.llm_client import LLMClient


class ChatStreamTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(settings, "DATABASE_URL", "sqlite://"), patch.object(RAGService, "__init__", lambda self: None):
            cls.router = importlib.import_module("src.api.routers.chat")
        from src.database.models import ChatInteraction, User
        from src.database.sql_session import Base
        cls.Base, cls.User, cls.Interaction = Base, User, ChatInteraction

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.user = self.User(username="test", email="test@example.test", password_hash="unused")
        self.db.add(self.user)
        self.db.commit()
        self.memory = MemorySystem(fakeredis.FakeRedis())

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def run_stream(self, fail=False, incomplete=False):
        async def query_stream(**kwargs):
            self.assertEqual(kwargs["user_id"], self.user.id)
            yield {"type": "token", "content": "first "}
            if fail:
                raise RuntimeError("provider failed")
            yield {"type": "token", "content": "second"}
            if not incomplete:
                yield {"type": "done"}
        with patch.object(self.router, "rag_service", SimpleNamespace(query_stream=query_stream)), \
             patch.object(self.router, "SessionLocal", self.sessions), \
             patch.object(self.router, "memory_system", self.memory):
            response = await self.router.chat_stream(self.router.ChatRequest(query="q"), self.user, self.db)
            events = []
            async for item in response.body_iterator:
                event = json.loads(item.removeprefix("data: ").strip())
                if event["type"] == "done":
                    self.assertEqual(self.db.query(self.Interaction).count(), 1)
                events.append(event)
            return events

    async def test_deltas_are_not_duplicated_and_done_follows_database_commit(self):
        events = await self.run_stream()
        self.assertEqual([e["content"] for e in events if e["type"] == "token"], ["first ", "second"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(self.db.query(self.Interaction).one().answer, "first second")

    async def test_failed_stream_does_not_store_partial_answer_or_memory(self):
        events = await self.run_stream(fail=True)
        self.assertEqual(events[-1]["type"], "error")
        self.assertFalse(any(e["type"] == "done" for e in events))
        self.assertEqual(self.db.query(self.Interaction).count(), 0)
        self.assertEqual(list(self.memory.redis_client.scan_iter()), [])

    async def test_incomplete_stream_is_rejected(self):
        events = await self.run_stream(incomplete=True)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.db.query(self.Interaction).count(), 0)

    async def test_database_failure_is_reported_before_done(self):
        with patch.object(self.router, "_persist_stream_answer", side_effect=RuntimeError("database failed")):
            events = await self.run_stream()
        self.assertEqual(events[-1]["type"], "error")
        self.assertFalse(any(e["type"] == "done" for e in events))

    async def test_agent_delta_arrives_while_agent_is_still_running(self):
        gate = asyncio.Event()
        class Orchestrator:
            async def run(inner, **kwargs):
                await kwargs["emit"]("answer.delta", {"content": "first "})
                await gate.wait()
                await kwargs["emit"]("answer.delta", {"content": "second"})
                return {"answer": "first second", "source_documents": []}
        with patch.object(self.router, "AssistantAgentOrchestrator", Orchestrator), \
             patch.object(self.router, "_resolve_assistant_config", return_value=({"agents": [{"id": 1}]}, [])), \
             patch.object(self.router, "SessionLocal", self.sessions), \
             patch.object(self.router, "memory_system", self.memory):
            response = await self.router.chat_stream(self.router.ChatRequest(query="q"), self.user, self.db)
            iterator = response.body_iterator
            await anext(iterator)  # session id
            event = json.loads((await anext(iterator)).removeprefix("data: ").strip())
            self.assertEqual(event, {"type": "token", "content": "first "})
            self.assertEqual(self.db.query(self.Interaction).count(), 0)
            gate.set()
            events = [json.loads(item.removeprefix("data: ").strip()) async for item in iterator]
            self.assertEqual([e["content"] for e in events if e["type"] == "token"], ["second"])
            self.assertEqual(events[-1]["type"], "done")

    async def test_closing_stream_cancels_associated_agent(self):
        cancelled = asyncio.Event()
        class Orchestrator:
            async def run(inner, **kwargs):
                try:
                    await kwargs["emit"]("answer.delta", {"content": "partial"})
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        with patch.object(self.router, "AssistantAgentOrchestrator", Orchestrator), \
             patch.object(self.router, "_resolve_assistant_config", return_value=({"agents": [{"id": 1}]}, [])):
            response = await self.router.chat_stream(self.router.ChatRequest(query="q"), self.user, self.db)
            await anext(response.body_iterator)
            await anext(response.body_iterator)
            await response.body_iterator.aclose()
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.db.query(self.Interaction).count(), 0)


class ModelStreamFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_failure_propagates_instead_of_becoming_answer_text(self):
        class Model:
            async def astream(self, messages):
                yield SimpleNamespace(content="partial")
                raise RuntimeError("provider offline")
        client = LLMClient.__new__(LLMClient)
        client.llm = Model()
        with self.assertRaisesRegex(RuntimeError, "streaming failed"):
            async for _ in client.generate_stream("q"):
                pass
