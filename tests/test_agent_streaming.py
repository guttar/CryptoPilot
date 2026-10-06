import asyncio
import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk
from src.services.agent_service import AgentService
from unittest.mock import patch


class FakeModel:
    def __init__(self, tool=False, fail=False):
        self.tool = tool
        self.fail = fail
        self.calls = 0
    def bind_tools(self, tools):
        return self
    async def ainvoke(self, messages):
        self.calls += 1
        if self.tool and self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "lookup_protocol", "args": {"protocol": "TLS 1.3"}, "id": "call-1"
            }])
        return AIMessage(content="private draft")
    async def astream(self, messages):
        yield AIMessageChunk(content="final ")
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("stream interrupted")
        yield AIMessageChunk(content="answer")


class AgentStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeated_searches_use_stable_unique_citation_ids(self):
        class Search:
            counter = 0
            def __init__(self, **kwargs):
                pass
            async def search(inner, **kwargs):
                Search.counter += 1
                chunk = "a" if Search.counter in {1, 3} else "b"
                return {"citations": [{"citation_id": "KB1", "chunk_id": chunk}]}
        service = AgentService(llm_client=SimpleNamespace(llm=FakeModel()))
        async def emit(*args):
            pass
        tools = service._build_tools({"knowledge_config": {"kb_ids": [1]}}, emit, [], asyncio.Event(), 1)
        with patch("src.services.agent_service.KnowledgeSearchService", Search):
            results = [await tools["search_knowledge_base"].ainvoke({"query": "q"}) for _ in range(3)]
        self.assertEqual([r["citations"][0]["citation_id"] for r in results], ["KB1", "KB2", "KB1"])

    async def execute(self, model, **kwargs):
        events = []
        async def emit(name, payload):
            events.append((name, payload))
        service = AgentService(llm_client=SimpleNamespace(llm=model))
        result = await service.run("Explain TLS", {
            "memory_config": {"enable_short_term": False},
            "reasoning_config": {"max_steps": 1},
        }, emit=emit, **kwargs)
        return result, events

    async def test_final_answer_streams_without_exposing_planner_draft(self):
        result, events = await self.execute(FakeModel(), stream_answer=True)
        parts = [p["content"] for name, p in events if name == "answer.delta"]
        self.assertEqual(parts, ["final ", "answer"])
        self.assertEqual(result["answer"], "".join(parts))
        self.assertNotIn("private draft", str(events))

    async def test_step_limit_finalization_streams_after_tool_execution(self):
        result, events = await self.execute(FakeModel(tool=True), stream_answer=True)
        names = [name for name, _ in events]
        self.assertLess(names.index("tool.completed"), names.index("answer.delta"))
        self.assertEqual(result["answer"], "final answer")

    async def test_nonstream_run_keeps_existing_answer(self):
        result, events = await self.execute(FakeModel())
        self.assertEqual(result["answer"], "private draft")
        self.assertFalse(any(name == "answer.delta" for name, _ in events))

    async def test_stream_failure_is_not_returned_as_success(self):
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            await self.execute(FakeModel(fail=True), stream_answer=True)

    async def test_cancellation_stops_remaining_deltas(self):
        cancel = asyncio.Event()
        events = []
        async def emit(name, payload):
            if name == "answer.delta":
                events.append(payload["content"])
                cancel.set()
        service = AgentService(llm_client=SimpleNamespace(llm=FakeModel()))
        with self.assertRaises(asyncio.CancelledError):
            await service.run("question", {"memory_config": {"enable_short_term": False}},
                              stream_answer=True, emit=emit, cancel_event=cancel)
        self.assertEqual(events, ["final "])
