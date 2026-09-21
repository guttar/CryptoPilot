from typing import List, Any
import dashscope
from http import HTTPStatus
from src.settings import settings
from src.utils.logger import logger
from src.models.vector import SearchResult


class DashScopeReranker:
    """基于DashScope API的重排序器实现。
    
    使用DashScope的文本重排序服务对检索结果进行重新排序，提升搜索结果的相关性。
    支持配置开关控制和降级策略。
    """

    def __init__(self):
        """初始化重排序器，从配置中加载API密钥、模型名称和返回数量等参数。"""
        self.api_key = settings.DASHSCOPE_API_KEY
        self.model = settings.RERANK_MODEL
        self.top_n = settings.RERANK_TOP_N

    def rerank(self, query: str, documents: List[SearchResult]) -> List[SearchResult]:
        """对检索结果进行重排序。
        
        调用DashScope的重排序API，根据查询文本与文档的相关性对文档列表进行重新排序。
        如果重排序功能未启用或发生错误，则返回原始结果的前top_n条记录。
        
        Args:
            query: 查询文本字符串，用于计算与文档的相关性分数。
            documents: 待重排序的搜索结果列表，每个元素为SearchResult对象。
            
        Returns:
            重排序后的SearchResult对象列表，按相关性分数降序排列。
            如果输入为空或发生错误，可能返回空列表或截断的原始结果。
        """
        # 处理空文档列表的边界情况
        if not documents:
            return []
            
        # 检查重排序功能是否启用，未启用时直接返回前top_n条结果
        if not settings.ENABLE_RERANK:
            return documents[:self.top_n]

        try:
            # 提取文档文本内容，准备调用DashScope API
            doc_texts = [doc.text for doc in documents]
            
            # 调用DashScope TextReRank服务进行相关性重排序
            from dashscope import TextReRank
            
            resp = TextReRank.call(
                model=self.model,
                query=query,
                documents=doc_texts,
                top_n=self.top_n,
                api_key=self.api_key
            )

            # 解析API响应，更新文档的相关性分数并构建重排序结果
            if resp.status_code == HTTPStatus.OK:
                reranked_results = []
                for item in resp.output.results:
                    idx = item.index
                    score = item.relevance_score
                    original_doc = documents[idx]
                    # 使用重排序服务返回的相关性分数更新文档
                    original_doc.score = score
                    reranked_results.append(original_doc)
                return reranked_results
            else:
                # API调用失败，记录错误并返回原始结果作为降级方案
                logger.error(f"DashScope Rerank Error: {resp.code} - {resp.message}")
                return documents[:self.top_n]
                
        except Exception as e:
            # 捕获异常并记录日志，返回原始结果作为降级方案
            logger.error(f"Rerank failed: {e}")
            return documents[:self.top_n]
