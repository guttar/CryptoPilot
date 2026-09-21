import asyncio
import unittest

from src.services.assistant_agent_orchestrator import AssistantAgentOrchestrator


class FakeAgentService:
    def __init__(self, calls):
        self.calls = calls

    async def run(self, question, config, **kwargs):
        self.calls.append({"question": question, "config": config, **kwargs})
        await kwargs["emit"]("tool.started", {"tool": "search_knowledge_base"})
        name = config["name"]
        return {
            "answer": f"{name} answer [KB1]",
            "tool_trace": [
                {
                    "tool": "search_knowledge_base",
                    "arguments": {"query": question},
                    "result": {
                        "citations": [
                            {
                                "citation_id": "KB1",
                                "chunk_id": "shared-chunk",
                                "text": "RFC evidence",
                                "score": 0.91,
                                "source": "RFC 8446",
                                "page": 12,
                                "metadata": {"file_type": "pdf"},
                            }
                        ]
                    },
                }
            ],
        }


class AssistantAgentOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_agent_returns_answer_and_scoped_sources(self):
        calls = []
        events = []

        async def emit(event_type, payload):
            events.append((event_type, payload))

        service = AssistantAgentOrchestrator(
            agent_service_factory=lambda: FakeAgentService(calls)
        )
        result = await service.run(
            question="Explain TLS 1.3",
            agents=[{"id": 9, "name": "TLS Analyst", "config": {"name": "tls"}}],
            session_id="session-1",
            user_id=7,
            emit=emit,
        )

        self.assertEqual(result["answer"], "tls answer [KB1]")
        self.assertEqual(result["source_documents"][0]["id"], "shared-chunk")
        self.assertEqual(result["source_documents"][0]["citation"], "KB1")
        self.assertEqual(calls[0]["session_id"], "session-1:agent:9")
        self.assertEqual(calls[0]["user_id"], 7)
        self.assertTrue(any(event == "agent.completed" for event, _ in events))

    async def test_multiple_agents_are_synthesized_and_sources_deduplicated(self):
        calls = []
        synthesized = []

        async def synthesize(question, results):
            synthesized.append((question, results))
            return "combined answer [KB1]"

        service = AssistantAgentOrchestrator(
            agent_service_factory=lambda: FakeAgentService(calls),
            synthesizer=synthesize,
        )
        result = await service.run(
            question="Compare protocols",
            agents=[
                {"id": 1, "name": "A", "config": {"name": "a"}},
                {"id": 2, "name": "B", "config": {"name": "b"}},
            ],
            session_id="session-2",
            user_id=5,
        )

        self.assertEqual(result["answer"], "combined answer [KB1]")
        self.assertEqual(len(result["source_documents"]), 1)
        self.assertEqual(len(result["tool_trace"]), 2)
        self.assertEqual(len(synthesized[0][1]), 2)

    async def test_partial_agent_failure_keeps_successful_answer(self):
        class SometimesFailingService(FakeAgentService):
            async def run(self, question, config, **kwargs):
                if config["name"] == "bad":
                    raise RuntimeError("boom")
                return await super().run(question, config, **kwargs)

        calls = []
        service = AssistantAgentOrchestrator(
            agent_service_factory=lambda: SometimesFailingService(calls)
        )
        result = await service.run(
            question="Analyze",
            agents=[
                {"id": 1, "name": "Good", "config": {"name": "good"}},
                {"id": 2, "name": "Bad", "config": {"name": "bad"}},
            ],
            session_id="session-3",
            user_id=1,
        )

        self.assertEqual(result["answer"], "good answer [KB1]")
        self.assertEqual(result["agent_results"][1]["error"], "boom")


if __name__ == "__main__":
    unittest.main()
