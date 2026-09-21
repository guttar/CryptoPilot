from typing import AsyncIterator, List, Dict, Any, Optional
from src.retrieval.vector_retriever import VectorRetriever
from src.retrieval.reranker import DashScopeReranker
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
from src.settings import settings
from src.services.question_analyzer import QuestionAnalyzer
from src.services.memory_service import MemorySystem

class RAGService:
    """
    RAG（检索增强生成）服务类
    
    提供基于知识库的智能问答功能，支持单跳和多跳查询，
    集成短期和长期记忆系统，支持通用聊天和RAG检索两种模式。
    """
    
    def __init__(self):
        """
        初始化RAG服务
        
        初始化向量检索器、LLM客户端、重排序器、问题分析器和记忆系统等核心组件。
        """
        self.retriever = VectorRetriever()
        self.llm_client = LLMClient()
        self.reranker = DashScopeReranker()
        self.analyzer = QuestionAnalyzer(self.llm_client)
        self.memory = MemorySystem()

    def query(
        self, 
        query_text: str, 
        top_k: int = 5, 
        session_id: str = "default", 
        kb_ids: Optional[List[int]] = None,
        assistant_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行查询操作
        
        根据配置自动选择通用聊天模式或RAG检索模式回答问题。
        支持会话记忆、多智能体配置和多种高级功能。
        
        参数:
            query_text: 用户输入的查询文本
            top_k: 检索时返回的顶部结果数量，默认为5
            session_id: 会话标识符，用于管理短期记忆，默认为"default"
            kb_ids: 知识库ID列表，如果为None则进入通用聊天模式
            assistant_config: 助手配置字典，包含以下可选键:
                - system_prompt: 系统指令文本
                - agent_ids: 智能体ID列表
                - memory_config: 记忆配置字典，包含:
                    - enable_short_term: 是否启用短期记忆，默认True
                    - window_size: 历史对话窗口大小，默认10
                    - enable_long_term: 是否启用长期记忆，默认False
        
        返回:
            包含查询结果的字典:
                - query: 原始查询文本
                - answer: 生成的回答内容
                - source_documents: 来源文档列表（仅在RAG模式下有数据）
                - metrics: 性能指标（如果可用），包含首token延迟和总延迟
        """
        
        # 配置提取
        system_prompt = assistant_config.get("system_prompt") if assistant_config else None
        agent_ids = assistant_config.get("agent_ids") if assistant_config else None
        # model = assistant_config.get("llm_model") # 如果LLM客户端支持则传递
        
        # 0. 获取历史对话（短期记忆）
        memory_config = assistant_config.get("memory_config", {}) if assistant_config else {}
        enable_short_term = memory_config.get("enable_short_term", True) # 如果未指定则默认为True
        window_size = memory_config.get("window_size", 10)
        
        history = []
        if enable_short_term:
            history = self.memory.get_short_term_memory(session_id, limit=window_size)
            
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        
        # 长期记忆注入（占位符/模拟）
        enable_long_term = memory_config.get("enable_long_term", False)
        long_term_context = ""
        if enable_long_term:
            # 在实际系统中，我们会嵌入查询并搜索长期向量存储
            # 目前我们模拟这个功能或仅记录日志
            logger.info(f"Long-term memory enabled for session {session_id}")
            # long_term_memories = self.memory.retrieve_long_term_memory(query_text)
            # long_term_context = "\n".join([m['content'] for m in long_term_memories])
            pass

        # 1. 分析问题（结合历史对话）
        # 如果没有知识库，则处于"通用聊天"模式
        
        if not kb_ids:
            # 通用聊天模式
            logger.info("No KB selected, using General Chat Mode")
            context = f"历史对话:\n{history_str}" if history else ""
            if long_term_context:
                context = f"长期记忆:\n{long_term_context}\n\n{context}"
                
            if system_prompt:
                context = f"系统指令: {system_prompt}\n\n{context}"
                
            # TODO: 如果存在agent_ids，可以在此处调用AgentExecutor
            if agent_ids:
                logger.info(f"Agents configured: {agent_ids}. Agent execution logic to be implemented.")
                
            # 直接调用LLM
            # 对非RAG查询使用通用响应方法
            answer = self.llm_client.generate_general_response(query_text, context)
            
            # 更新记忆
            self.memory.add_short_term_memory(session_id, "user", query_text)
            self.memory.add_short_term_memory(session_id, "assistant", answer)
            
            return {
                "query": query_text,
                "answer": answer,
                "source_documents": []
            }

        # RAG模式
        contextual_query = f"历史对话:\n{history_str}\n当前问题: {query_text}" if history else query_text
        analysis = self.analyzer.analyze(contextual_query)
        logger.info(f"Question Analysis: {analysis}")

        if settings.ENABLE_MULTI_HOP and analysis.get("is_multi_hop"):
            result = self._multi_hop_query(query_text, analysis.get("sub_queries", []), top_k, history_str, kb_ids, system_prompt)
        else:
            result = self._single_hop_query(query_text, top_k, history_str, kb_ids, system_prompt)
        
        # 2. 更新短期记忆
        self.memory.add_short_term_memory(session_id, "user", query_text)
        self.memory.add_short_term_memory(session_id, "assistant", result["answer"])
        
        return result

    async def query_stream(
        self,
        query_text: str,
        top_k: int = 5,
        session_id: str = "default",
        kb_ids: Optional[List[int]] = None,
        assistant_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """执行流式查询，逐 token 产出事件。

        与 query() 的区别在于 LLM 生成阶段采用异步流式输出，
        前端可实时展示每个 token。

        Yields:
            事件字典，包含以下类型:
            - {"type": "token", "content": str} — 流式 token
            - {"type": "sources", "data": list} — 来源文档
            - {"type": "done"} — 流结束
        """
        system_prompt = assistant_config.get("system_prompt") if assistant_config else None
        memory_config = assistant_config.get("memory_config", {}) if assistant_config else {}
        enable_short_term = memory_config.get("enable_short_term", True)

        history = []
        if enable_short_term:
            history = self.memory.get_short_term_memory(session_id, limit=10)
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])

        # 通用聊天模式（无知识库）
        if not kb_ids:
            context = f"历史对话:\n{history_str}" if history else ""
            if system_prompt:
                context = f"系统指令: {system_prompt}\n\n{context}"
            prompt = f"You are a helpful assistant.\n\n{context}\n\nUser Question: {query_text}\n\nAnswer:"
            async for token in self.llm_client.generate_stream(prompt):
                yield {"type": "token", "content": token}
            yield {"type": "done"}
            return

        # RAG 模式：检索 → 重排序 → 流式生成
        initial_k = top_k * 2 if settings.ENABLE_RERANK else top_k
        search_results = self.retriever.retrieve(query_text, top_k=initial_k, kb_ids=kb_ids)

        if settings.ENABLE_RERANK and search_results:
            search_results = self.reranker.rerank(query_text, search_results)
        else:
            search_results = search_results[:top_k]

        context = self._format_context(search_results)
        if history_str:
            context = f"历史背景:\n{history_str}\n\n检索到的资料:\n{context}"
        else:
            context = f"检索到的资料:\n{context}"
        if system_prompt:
            context = f"系统指令: {system_prompt}\n\n{context}"

        prompt = f"""基于以下上下文信息，回答问题。

上下文：
{context}

问题：{query_text}

要求：
1. 基于上下文回答，不添加外部知识
2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
3. 引用相关段落编号
4. 保持回答准确、简洁

回答："""

        async for token in self.llm_client.generate_stream(prompt):
            yield {"type": "token", "content": token}

        # 产出来源文档
        yield {
            "type": "sources",
            "data": [
                {"id": res.id, "text": res.text, "score": res.score, "metadata": res.metadata}
                for res in search_results
            ]
        }
        yield {"type": "done"}

    def _single_hop_query(
        self, 
        query_text: str, 
        top_k: int, 
        history_str: str = "", 
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """
        执行单跳查询
        
        通过一次检索完成问答流程，包括检索、重排序、上下文构建和答案生成。
        
        参数:
            query_text: 用户查询文本
            top_k: 最终返回的顶部结果数量
            history_str: 历史对话字符串，用于构建上下文
            kb_ids: 知识库ID列表，指定要检索的知识库
            system_prompt: 系统指令，用于控制LLM的行为
        
        返回:
            包含查询结果的字典:
                - query: 原始查询文本
                - answer: 生成的回答
                - source_documents: 来源文档列表，包含id、text、score和metadata
                - metrics: 性能指标（如果LLM客户端支持），包含首token延迟和总延迟
        """
        
        # 1. 检索
        initial_k = top_k * 2 if settings.ENABLE_RERANK else top_k
        search_results = []
        if kb_ids:
            search_results = self.retriever.retrieve(query_text, top_k=initial_k, kb_ids=kb_ids)
        
        # 2. 重排序
        if settings.ENABLE_RERANK and search_results:
            search_results = self.reranker.rerank(query_text, search_results)
        else:
            search_results = search_results[:top_k]
        
        # 3. 格式化上下文
        context = self._format_context(search_results)
        if history_str:
            context = f"历史背景:\n{history_str}\n\n检索到的资料:\n{context}"
        else:
            context = f"检索到的资料:\n{context}"
            
        if system_prompt:
             context = f"系统指令: {system_prompt}\n\n{context}"
        
        # 4. 生成答案
        if hasattr(self.llm_client, 'generate_response_with_metrics'):
             # 构建完整提示词，如同generate_response所做的那样
             # LLMClient中的generate_response方法在内部构建提示词
             # 我们需要复制该逻辑或修改generate_response以支持指标
             # 目前，我们在这里使用generate_response逻辑来构建提示词
             prompt = f"""基于以下上下文信息，回答问题。
            
        上下文：
        {context}

        问题：{query_text}

        要求：
        1. 基于上下文回答，不添加外部知识
        2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
        3. 引用相关段落编号
        4. 保持回答准确、简洁

        回答："""
             answer, first_token, total_time = self.llm_client.generate_response_with_metrics(prompt)
             
             result = self._format_response(query_text, answer, search_results)
             result["metrics"] = {
                 "first_token_latency": first_token,
                 "total_latency": total_time
             }
             return result
        else:
            answer = self.llm_client.generate_response(query_text, context)
            return self._format_response(query_text, answer, search_results)

    def _multi_hop_query(
        self, 
        query_text: str, 
        sub_queries: List[str], 
        top_k: int, 
        history_str: str = "", 
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """
        执行多跳查询
        
        针对复杂问题，通过多个子查询逐步收集信息，最后综合生成答案。
        每个子查询都会进行独立检索，并累积上下文供后续步骤使用。
        
        参数:
            query_text: 原始用户查询文本
            sub_queries: 子查询列表，由问题分析器生成
            top_k: 每次检索返回的顶部结果数量
            history_str: 历史对话字符串
            kb_ids: 知识库ID列表
            system_prompt: 系统指令
        
        返回:
            包含查询结果的字典:
                - query: 原始查询文本
                - answer: 生成的回答
                - source_documents: 所有检索到的来源文档列表
        """
        
        all_results = []
        accumulated_context = history_str + "\n" if history_str else ""
        
        # 通过MAX_HOP限制子查询数量
        steps = sub_queries[:settings.MAX_HOP]
        
        for i, sub_query in enumerate(steps):
            logger.info(f"Multi-hop Step {i+1}: {sub_query}")
            
            # 为子查询执行检索
            if kb_ids:
                results = self.retriever.retrieve(sub_query, top_k=top_k, kb_ids=kb_ids)
                
                # 过滤唯一结果
                new_results = [r for r in results if r.id not in [existing.id for existing in all_results]]
                all_results.extend(new_results)
                
                # 为下一步更新累积上下文
                accumulated_context += f"\n--- Step {i+1} Context ---\n"
                accumulated_context += self._format_context(new_results)

        # 对所有收集的证据进行最终重排序
        if settings.ENABLE_RERANK and all_results:
            all_results = self.reranker.rerank(query_text, all_results)
        else:
            all_results = all_results[:top_k]

        # 最终上下文
        final_context = accumulated_context + "\n\n最终检索结果:\n" + self._format_context(all_results)
        
        if system_prompt:
             final_context = f"系统指令: {system_prompt}\n\n{final_context}"

        # 最终答案
        answer = self.llm_client.generate_response(query_text, final_context)
        
        return self._format_response(query_text, answer, all_results)

    def _format_response(self, query: str, answer: str, results: List[Any]) -> Dict[str, Any]:
        """
        格式化响应结果
        
        将查询、答案和检索结果组织成统一的返回格式。
        
        参数:
            query: 原始查询文本
            answer: 生成的回答内容
            results: 检索结果列表，每个元素应包含id、text、score和metadata属性
        
        返回:
            格式化后的响应字典:
                - query: 查询文本
                - answer: 回答内容
                - source_documents: 来源文档列表，每个文档包含id、text、score和metadata
        """
        return {
            "query": query,
            "answer": answer,
            "source_documents": [
                {
                    "id": res.id,
                    "text": res.text,
                    "score": res.score,
                    "metadata": res.metadata
                }
                for res in results
            ]
        }

    def _format_context(self, search_results: List[Any]) -> str:
        """
        格式化上下文文本
        
        将检索结果转换为适合输入给LLM的结构化文本格式。
        
        参数:
            search_results: 检索结果列表，每个元素应包含id和text属性
        
        返回:
            格式化后的上下文字符串，每个段落都有编号和ID标识
        """
        context_parts = []
        for i, res in enumerate(search_results):
            context_parts.append(f"段落 {i+1} (ID: {res.id}):\n{res.text}")
        return "\n\n".join(context_parts)
