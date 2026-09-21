"""LangGraph-based cryptographic-protocol analysis Agent."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Awaitable, Callable, Dict, List, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from src.llm.llm_client import LLMClient
from src.services.crypto_tools import lookup_protocol as lookup_protocol_record
from src.services.crypto_tools import validate_crypto_parameters as validate_crypto_parameters_record
from src.services.knowledge_search_service import KnowledgeSearchService
from src.services.long_term_memory_service import LongTermMemoryService
from src.services.memory_service import MemorySystem


EventCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    steps: int


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "".join(parts)
    return str(content or "")


class AgentService:
    """Build and execute one bounded Agent graph for each request."""

    TOOL_ALIASES = {
        "search": "search_knowledge_base",
        "knowledge_search": "search_knowledge_base",
        "protocol": "lookup_protocol",
        "parameter_validation": "validate_crypto_parameters",
    }
    DEFAULT_TOOLS = [
        "search_knowledge_base",
        "lookup_protocol",
        "validate_crypto_parameters",
    ]
    MEMORY_TOOLS = ["recall_long_term_memory", "remember_insight"]

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        memory: MemorySystem | None = None,
        retriever_factory: Callable[[], Any] | None = None,
        reranker_factory: Callable[[], Any] | None = None,
        long_term_memory: LongTermMemoryService | None = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.memory = memory
        self.retriever_factory = retriever_factory
        self.reranker_factory = reranker_factory
        self.long_term_memory = long_term_memory

    @staticmethod
    async def _noop_event(_: str, __: Dict[str, Any]) -> None:
        return None

    def _enabled_tool_names(self, config: Dict[str, Any], available_names: set[str]) -> List[str]:
        configured = config.get("tools_config") or {}
        names = configured.get("enabled_tools")
        if names is None:
            names = configured.get("tools")
        if not names:
            names = list(self.DEFAULT_TOOLS)
            if (config.get("memory_config") or {}).get("enable_long_term"):
                names.extend(name for name in self.MEMORY_TOOLS if name in available_names)
        if not isinstance(names, list):
            raise ValueError("tools_config.tools must be a list")

        normalized = []
        for raw_name in names:
            name = self.TOOL_ALIASES.get(str(raw_name), str(raw_name))
            if name not in available_names:
                raise ValueError(f"Agent configuration contains an unsupported tool: {raw_name}")
            if name not in normalized:
                normalized.append(name)
        return normalized

    def _build_tools(
        self,
        config: Dict[str, Any],
        emit: EventCallback,
        tool_trace: List[Dict[str, Any]],
        cancel_event: asyncio.Event,
        user_id: int | None,
    ) -> Dict[str, Any]:
        knowledge_config = config.get("knowledge_config") or {}
        memory_config = config.get("memory_config") or {}
        kb_ids = [int(value) for value in knowledge_config.get("kb_ids", [])]
        configured_top_k = min(max(int(knowledge_config.get("top_k", 5)), 1), 20)

        @tool("search_knowledge_base")
        async def search_knowledge_base(
            query: str,
            top_k: int = 5,
            metadata_filters: Dict[str, Any] | None = None,
        ) -> Dict[str, Any]:
            """Search bound cryptography papers, protocol specifications, and security definitions."""
            if cancel_event.is_set():
                raise asyncio.CancelledError
            if not kb_ids:
                return {"citations": [], "message": "No knowledge base is bound to this Agent."}
            limit = min(max(int(top_k), 1), configured_top_k)
            search_service = KnowledgeSearchService(
                retriever_factory=self.retriever_factory,
                reranker_factory=self.reranker_factory,
            )
            return await search_service.search(
                query=query,
                kb_ids=kb_ids,
                top_k=limit,
                enable_rerank=knowledge_config.get("enable_rerank", True),
                metadata_filters=metadata_filters,
                emit=emit,
            )

        @tool("lookup_protocol")
        def lookup_protocol(protocol: str) -> Dict[str, Any]:
            """Look up a concise standards-oriented description of a known cryptographic protocol."""
            return lookup_protocol_record(protocol)

        @tool("validate_crypto_parameters")
        def validate_crypto_parameters(
            algorithm: str,
            key_size: int | None = None,
            curve: str | None = None,
            hash_name: str | None = None,
            nonce_reuse_possible: bool = False,
        ) -> Dict[str, Any]:
            """Check common cryptographic parameters and return structured security findings."""
            return validate_crypto_parameters_record(
                algorithm=algorithm,
                key_size=key_size,
                curve=curve,
                hash_name=hash_name,
                nonce_reuse_possible=nonce_reuse_possible,
            )

        @tool("recall_long_term_memory")
        async def recall_long_term_memory(query: str, top_k: int = 3) -> Dict[str, Any]:
            """Recall durable user-specific preferences and prior analysis insights relevant to a query."""
            if not memory_config.get("enable_long_term") or user_id is None:
                return {"memories": [], "message": "Long-term memory is disabled."}
            service = self.long_term_memory or LongTermMemoryService()
            memories = await asyncio.to_thread(service.recall, user_id=user_id, query=query, top_k=top_k)
            return {"memories": memories}

        @tool("remember_insight")
        async def remember_insight(content: str, memory_type: str = "insight") -> Dict[str, Any]:
            """Persist a non-secret, durable user preference or confirmed analysis insight for future runs."""
            if not memory_config.get("enable_long_term") or user_id is None:
                return {"stored": False, "message": "Long-term memory is disabled."}
            service = self.long_term_memory or LongTermMemoryService()
            return await asyncio.to_thread(
                service.add,
                user_id=user_id,
                content=content,
                memory_type=memory_type,
                metadata={"source": "agent_tool"},
            )

        registry = {
            search_knowledge_base.name: search_knowledge_base,
            lookup_protocol.name: lookup_protocol,
            validate_crypto_parameters.name: validate_crypto_parameters,
        }
        if memory_config.get("enable_long_term") and user_id is not None:
            registry[recall_long_term_memory.name] = recall_long_term_memory
            registry[remember_insight.name] = remember_insight
        return {name: registry[name] for name in self._enabled_tool_names(config, set(registry))}

    async def run(
        self,
        question: str,
        config: Dict[str, Any],
        *,
        session_id: str | None = None,
        user_id: int | None = None,
        emit: EventCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> Dict[str, Any]:
        if not self.llm_client.llm:
            raise RuntimeError("LLM service is unavailable")
        if not question.strip():
            raise ValueError("Question cannot be empty")

        emit = emit or self._noop_event
        cancel_event = cancel_event or asyncio.Event()
        tool_trace: List[Dict[str, Any]] = []
        tools = self._build_tools(config, emit, tool_trace, cancel_event, user_id)
        base_model = self.llm_client.llm
        model = base_model.bind_tools(list(tools.values())) if tools else base_model
        max_steps = min(max(int((config.get("reasoning_config") or {}).get("max_steps", 6)), 1), 12)
        allow_parallel = bool((config.get("reasoning_config") or {}).get("allow_parallel", True))

        async def call_agent(state: AgentState) -> Dict[str, Any]:
            if cancel_event.is_set():
                raise asyncio.CancelledError
            step = state.get("steps", 0) + 1
            await emit("agent.thinking", {"step": step, "max_steps": max_steps})
            response = await model.ainvoke(state["messages"])
            return {"messages": [response], "steps": step}

        async def execute_one(call: Dict[str, Any]) -> ToolMessage:
            if cancel_event.is_set():
                raise asyncio.CancelledError
            name = call.get("name")
            implementation = tools.get(name)
            if implementation is None:
                raise ValueError(f"Model requested a tool that is not enabled: {name}")
            arguments = call.get("args") or {}
            await emit("tool.started", {"tool": name, "arguments": arguments})
            try:
                result = await implementation.ainvoke(arguments)
                trace_item = {"tool": name, "arguments": arguments, "result": result}
                tool_trace.append(trace_item)
                await emit("tool.completed", trace_item)
                return ToolMessage(
                    content=json.dumps(result, ensure_ascii=False, default=str),
                    tool_call_id=call["id"],
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                trace_item = {"tool": name, "arguments": arguments, "error": str(exc)}
                tool_trace.append(trace_item)
                await emit("tool.failed", trace_item)
                return ToolMessage(content=f"Tool error: {exc}", tool_call_id=call["id"])

        async def call_tools(state: AgentState) -> Dict[str, Any]:
            calls = getattr(state["messages"][-1], "tool_calls", None) or []
            if allow_parallel and len(calls) > 1:
                messages = await asyncio.gather(*(execute_one(call) for call in calls))
            else:
                messages = [await execute_one(call) for call in calls]
            return {"messages": messages, "steps": state.get("steps", 0)}

        async def finalize(state: AgentState) -> Dict[str, Any]:
            await emit("agent.finalizing", {"reason": "step_limit"})
            response = await base_model.ainvoke(
                state["messages"]
                + [SystemMessage(content="Tool budget is exhausted. Give the best grounded final answer now without calling tools.")]
            )
            return {"messages": [response], "steps": state.get("steps", 0)}

        def route(state: AgentState) -> str:
            last = state["messages"][-1]
            calls = getattr(last, "tool_calls", None) or []
            if not calls:
                return "end"
            return "tools"

        def after_tools(state: AgentState) -> str:
            return "finalize" if state.get("steps", 0) >= max_steps else "agent"

        graph = StateGraph(AgentState)
        graph.add_node("agent", call_agent)
        graph.add_node("tools", call_tools)
        graph.add_node("finalize", finalize)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", route, {"tools": "tools", "end": END})
        graph.add_conditional_edges("tools", after_tools, {"agent": "agent", "finalize": "finalize"})
        graph.add_edge("finalize", END)
        runnable = graph.compile()

        memory_config = config.get("memory_config") or {}
        memory = self.memory
        history: List[Dict[str, str]] = []
        if session_id and memory_config.get("enable_short_term", True):
            if memory is None:
                memory = MemorySystem()
            history = await asyncio.to_thread(
                memory.get_short_term_memory,
                session_id,
                min(max(int(memory_config.get("window_size", 10)), 1), 50),
            )

        history_text = "\n".join(f"{item['role']}: {item['content']}" for item in history)
        durable_memories: List[Dict[str, Any]] = []
        if user_id is not None and memory_config.get("enable_long_term"):
            try:
                service = self.long_term_memory or LongTermMemoryService()
                durable_memories = await asyncio.to_thread(
                    service.recall,
                    user_id=user_id,
                    query=question,
                    top_k=min(max(int(memory_config.get("long_term_top_k", 3)), 1), 10),
                )
                await emit("memory.recalled", {"count": len(durable_memories)})
            except Exception as exc:
                await emit("memory.failed", {"message": str(exc)})
        system_prompt = config.get("system_prompt") or (
            "你是密码协议辅助分析 Agent。优先使用绑定知识库中的论文、标准和安全定义作为证据；"
            "涉及算法参数时调用参数校验工具；区分标准事实、检索证据和你的推断；"
            "不要编造协议条款或安全结论；引用检索证据时使用工具返回的 [KB1]、[KB2] 格式，"
            "并在结论中列出对应文件和页码。"
        )
        if history_text:
            system_prompt += f"\n\n最近会话上下文：\n{history_text}"
        if durable_memories:
            memory_text = "\n".join(
                f"- ({item.get('memory_type', 'insight')}) {item.get('text', '')}"
                for item in durable_memories
            )
            system_prompt += (
                "\n\n与当前问题相关的长期记忆（仅作上下文，不作为外部事实证据）：\n"
                f"{memory_text}"
            )
        if memory_config.get("enable_long_term"):
            system_prompt += "\n仅在内容是稳定偏好或已确认结论且不含凭据、私钥或其他秘密时，才可调用 remember_insight。"

        await emit("run.started", {"enabled_tools": list(tools), "max_steps": max_steps})
        result = await runnable.ainvoke(
            {
                "messages": [SystemMessage(content=system_prompt), HumanMessage(content=question)],
                "steps": 0,
            }
        )
        if cancel_event.is_set():
            raise asyncio.CancelledError

        answer = _message_text(result["messages"][-1].content)
        if not answer:
            answer = (config.get("execution_config") or {}).get("fallback_response") or "未能生成有效回答。"

        if session_id and memory_config.get("enable_short_term", True) and memory is not None:
            await asyncio.to_thread(memory.add_short_term_memory, session_id, "user", question)
            await asyncio.to_thread(memory.add_short_term_memory, session_id, "assistant", answer)

        return {"answer": answer, "tool_trace": tool_trace}
