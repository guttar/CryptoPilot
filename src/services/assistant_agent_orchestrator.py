"""Execute the Agents attached to an Assistant and merge their results."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from copy import deepcopy
from typing import Any, Awaitable, Callable, Dict, Iterable, List


EventCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]
AgentServiceFactory = Callable[[], Any]
Synthesizer = Callable[[str, List[Dict[str, Any]]], Awaitable[str] | str]


class AssistantAgentOrchestrator:
    """Run an Assistant's owned Agent snapshots with bounded concurrency."""

    def __init__(
        self,
        agent_service_factory: AgentServiceFactory | None = None,
        synthesizer: Synthesizer | None = None,
        max_concurrency: int = 3,
        llm_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._agent_service_factory = agent_service_factory
        self._synthesizer = synthesizer
        self._max_concurrency = min(max(int(max_concurrency), 1), 8)
        self._llm_factory = llm_factory

    @staticmethod
    async def _noop_event(_: str, __: Dict[str, Any]) -> None:
        return None

    def _new_agent_service(self) -> Any:
        if self._agent_service_factory is not None:
            return self._agent_service_factory()
        # Keep the heavyweight LangGraph imports lazy so orchestration can be
        # unit-tested without booting the whole application stack.
        from src.services.agent_service import AgentService

        return AgentService()

    async def _default_synthesize(self, question: str, results: List[Dict[str, Any]],
                                  emit: EventCallback | None = None) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage
        if self._llm_factory is None:
            from src.llm.llm_client import LLMClient
            llm = LLMClient().llm
        else:
            llm = self._llm_factory()
        if llm is None:
            raise RuntimeError("LLM service is unavailable for multi-Agent synthesis")
        evidence = [
            {"agent": item["agent_name"], "answer": item["answer"]}
            for item in results
        ]
        messages = [
                SystemMessage(
                    content=(
                        "你是密码协议分析总编排器。请综合各子 Agent 的结论，消除重复与冲突；"
                        "不得添加子 Agent 未提供的事实，并保留回答中的 [KBn] 引用。"
                    )
                ),
                HumanMessage(
                    content=f"用户问题：{question}\n\n子 Agent 结果：\n"
                    + json.dumps(evidence, ensure_ascii=False)
                ),
            ]
        if emit is not None:
            parts = []
            async for chunk in llm.astream(messages):
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    parts.append(content)
                    await emit("answer.delta", {"content": content})
            return "".join(parts)
        response = await llm.ainvoke(messages)
        content = getattr(response, "content", response)
        return str(content or "").strip()

    @staticmethod
    def _normalize_citations(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Give all child evidence a shared citation namespace before synthesis."""
        results = deepcopy(results)
        global_ids: dict[tuple, str] = {}
        for item in results:
            local_ids = {}
            for trace in item.get("tool_trace", []):
                if trace.get("tool") != "search_knowledge_base":
                    continue
                for citation in (trace.get("result") or {}).get("citations", []):
                    identity = (citation.get("kb_id"), citation.get("chunk_id"))
                    global_id = global_ids.setdefault(identity, f"KB{len(global_ids) + 1}")
                    local_ids[citation.get("citation_id")] = global_id
                    citation["citation_id"] = global_id
            item["answer"] = re.sub(
                r"\[(KB\d+)\]", lambda match: f"[{local_ids[match.group(1)]}]"
                if match.group(1) in local_ids else match.group(0), item.get("answer", ""),
            )
        return results

    @staticmethod
    def _source_documents(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for agent_result in results:
            for trace in agent_result.get("tool_trace", []):
                if trace.get("tool") != "search_knowledge_base":
                    continue
                result = trace.get("result") or {}
                for citation in result.get("citations", []):
                    identity = (citation.get("kb_id"), citation.get("chunk_id"))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    metadata = dict(citation.get("metadata") or {})
                    metadata.setdefault("kb_id", citation.get("kb_id"))
                    metadata.setdefault("source", citation.get("source"))
                    metadata.setdefault("page", citation.get("page"))
                    sources.append(
                        {
                            "id": citation.get("chunk_id") or citation.get("citation_id"),
                            "text": citation.get("text", ""),
                            "score": float(citation.get("score") or 0),
                            "metadata": metadata,
                            "citation": citation.get("citation_id"),
                        }
                    )
        return sources

    async def run(
        self,
        *,
        question: str,
        agents: List[Dict[str, Any]],
        session_id: str,
        user_id: int,
        emit: EventCallback | None = None,
        stream_answer: bool = False,
    ) -> Dict[str, Any]:
        if not agents:
            raise ValueError("At least one Agent is required")

        emit = emit or self._noop_event
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run_one(agent: Dict[str, Any]) -> Dict[str, Any]:
            agent_id = int(agent["id"])
            agent_name = str(agent.get("name") or f"Agent {agent_id}")

            async def scoped_emit(event_type: str, payload: Dict[str, Any]) -> None:
                await emit(
                    event_type,
                    {"agent_id": agent_id, "agent_name": agent_name, **payload},
                )

            await emit("agent.started", {"agent_id": agent_id, "agent_name": agent_name})
            try:
                async with semaphore:
                    result = await self._new_agent_service().run(
                        question,
                        agent["config"],
                        session_id=f"{session_id}:agent:{agent_id}",
                        user_id=user_id,
                        emit=scoped_emit,
                        stream_answer=stream_answer and len(agents) == 1,
                    )
                item = {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "answer": result.get("answer", ""),
                    "tool_trace": result.get("tool_trace", []),
                }
                await emit(
                    "agent.completed",
                    {"agent_id": agent_id, "agent_name": agent_name},
                )
                return item
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await emit(
                    "agent.failed",
                    {"agent_id": agent_id, "agent_name": agent_name, "error": str(exc)},
                )
                return {
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "answer": "",
                    "tool_trace": [],
                    "error": str(exc),
                }

        all_results = await asyncio.gather(*(run_one(agent) for agent in agents))
        if len(agents) > 1:
            all_results = self._normalize_citations(all_results)
        successful = [item for item in all_results if item.get("answer")]
        if not successful:
            errors = "; ".join(
                f"{item['agent_name']}: {item.get('error', 'no answer')}" for item in all_results
            )
            raise RuntimeError(f"All attached Agents failed: {errors}")

        if len(successful) == 1 and (not stream_answer or len(agents) == 1):
            answer = successful[0]["answer"]
        elif stream_answer and self._synthesizer is None:
            answer = await self._default_synthesize(question, successful, emit=emit)
        else:
            synthesizer = self._synthesizer or self._default_synthesize
            answer_value = synthesizer(question, successful)
            answer = await answer_value if inspect.isawaitable(answer_value) else answer_value
            answer = str(answer or "").strip()
            if stream_answer:
                await emit("answer.delta", {"content": answer})

        tool_trace = [
            {"agent_id": item["agent_id"], "agent_name": item["agent_name"], **trace}
            for item in successful
            for trace in item.get("tool_trace", [])
        ]
        return {
            "query": question,
            "answer": answer,
            "source_documents": self._source_documents(successful),
            "agent_results": all_results,
            "tool_trace": tool_trace,
        }
