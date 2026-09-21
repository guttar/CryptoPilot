from typing import AsyncIterator, List, Optional, Tuple
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from src.settings import settings
from src.utils.logger import logger

import time


class LLMClient:
    """大语言模型客户端封装类。
    
    基于LangChain和DashScope（通义千问）提供LLM调用功能，支持流式输出、
    性能指标监控以及多种响应生成模式（RAG问答、通用对话、自定义提示）。
    """

    def __init__(self):
        """初始化LLM客户端，配置模型参数并创建ChatTongyi实例。
        
        从系统设置中加载模型名称和API密钥，启用流式输出模式。
        如果初始化失败，将记录错误日志并将llm实例设为None。
        """
        self.model_name = settings.LLM_MODEL
        self.api_key = settings.DASHSCOPE_API_KEY
        
        try:
            self.llm = ChatTongyi(
                model=self.model_name,
                temperature=0.7,
                top_p=0.8,
                api_key=self.api_key,
                streaming=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize LLM Client: {e}")
            self.llm = None

    def generate_response_with_metrics(self, prompt: str) -> Tuple[str, float, float]:
        """生成带性能指标的响应内容。
        
        使用流式方式调用LLM，记录首token延迟和总响应时间，用于性能监控。
        
        Args:
            prompt: 用户输入的提示词字符串。
            
        Returns:
            包含三个元素的元组：
            - content (str): LLM生成的完整响应内容
            - first_token_latency (float): 首token延迟（秒），从请求开始到收到第一个token的时间
            - total_latency (float): 总延迟（秒），从请求开始到完成所有生成的时间
            如果LLM服务不可用，返回错误信息和0.0的延迟值。
        """
        if not self.llm:
            return "LLM Service unavailable.", 0.0, 0.0
            
        # 记录请求开始时间，用于计算性能指标
        start_time = time.time()
        first_token_time = None
        content = ""
        
        try:
            # 构建消息列表，包含系统消息和用户消息
            messages = [
                SystemMessage(content="You are a helpful RAG assistant."),
                HumanMessage(content=prompt)
            ]
            
            # 流式接收LLM响应，记录首token时间和累积内容
            for chunk in self.llm.stream(messages):
                if first_token_time is None:
                    first_token_time = time.time()
                content += chunk.content
                
            end_time = time.time()
            
            # 计算首token延迟和总延迟
            first_token_latency = (first_token_time - start_time) if first_token_time else 0.0
            total_latency = end_time - start_time
            
            return content, first_token_latency, total_latency

        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error generating response: {str(e)}", 0.0, 0.0

    async def generate_stream(self, prompt: str, system_prompt: Optional[str] = None) -> AsyncIterator[str]:
        """异步流式生成响应，逐 token 产出。

        Args:
            prompt: 用户输入的提示词。
            system_prompt: 可选的系统提示词，默认使用标准 RAG 助手提示。

        Yields:
            每个流式 token 的文本内容。
        """
        if not self.llm:
            yield "LLM Service unavailable."
            return

        try:
            sys_msg = system_prompt if system_prompt else "You are a helpful RAG assistant."
            messages = [
                SystemMessage(content=sys_msg),
                HumanMessage(content=prompt)
            ]
            async for chunk in self.llm.astream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield f"Error generating response: {str(e)}"

    def generate_response(self, query: str, context: str, system_prompt: Optional[str] = None) -> str:
        """基于RAG上下文生成回答。
        
        根据提供的上下文信息和用户问题生成回答。支持两种模式：
        1. 自定义系统提示模式：用于特定任务（如QA生成）
        2. 默认RAG模式：严格基于上下文回答，不添加外部知识
        
        Args:
            query: 用户提出的问题。
            context: 检索到的相关上下文信息。
            system_prompt: 可选的系统提示词，如果提供则使用自定义提示模式。
            
        Returns:
            LLM生成的回答字符串。如果LLM服务不可用，返回错误提示信息。
        """
        if not self.llm:
            return "LLM Service unavailable."
            
        # 如果提供了自定义系统提示，使用自定义提示模式生成响应
        if system_prompt:
             prompt = f"""{system_prompt}
             
上下文：
{context}

问题：{query}

要求：
1. 基于上下文回答
2. 输出符合指令要求
"""
             return self.generate_custom_response(prompt)

        # 构建默认RAG提示词，强调严格基于上下文回答
        prompt = f"""基于以下上下文信息，回答问题。
        
上下文：
{context}

问题：{query}

要求：
1. 基于上下文回答，不添加外部知识
2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
3. 引用相关段落编号
4. 保持回答准确、简洁

回答："""

        return self.generate_custom_response(prompt)

    def generate_general_response(self, query: str, context: str = "") -> str:
        """生成通用对话响应，不使用严格的RAG约束。
        
        适用于闲聊场景或需要利用外部知识的问答，允许LLM使用其训练数据中的知识。
        
        Args:
            query: 用户的问题或对话内容。
            context: 可选的上下文信息，默认为空字符串。
            
        Returns:
            LLM生成的通用回答字符串。如果LLM服务不可用，返回错误提示信息。
        """
        if not self.llm:
            return "LLM Service unavailable."
            
        # 构建通用对话提示词，允许使用外部知识
        prompt = f"""You are a helpful assistant.
        
{context}

User Question: {query}

Answer:"""
        
        return self.generate_custom_response(prompt)

    def generate_custom_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """使用自定义提示词生成响应。
        
        底层的通用生成方法，支持自定义系统提示词，其他生成方法内部调用此方法。
        
        Args:
            prompt: 用户输入的提示词字符串。
            system_prompt: 可选的系统提示词，默认为标准的RAG助手提示。
            
        Returns:
            LLM生成的响应内容字符串。如果LLM服务不可用或发生错误，返回错误提示信息。
        """
        if not self.llm:
            return "LLM Service unavailable."
            
        try:
            # 构建系统消息和用户消息
            sys_msg = system_prompt if system_prompt else "You are a helpful RAG assistant."
            messages = [
                SystemMessage(content=sys_msg),
                HumanMessage(content=prompt)
            ]
            # 调用LLM进行非流式推理
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error generating response: {str(e)}"
