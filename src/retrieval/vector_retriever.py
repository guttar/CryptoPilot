from typing import List, Optional
from src.retrieval.base_retriever import BaseRetriever
from src.database.vector_db import MilvusClient
from src.embedding import get_embedding_service
from src.models.vector import SearchResult


class VectorRetriever(BaseRetriever):
    """基于向量相似度的检索器实现。
    
    使用Milvus向量数据库进行语义搜索，通过嵌入服务将查询文本转换为向量，
    然后在向量数据库中查找最相似的文档片段。支持按知识库ID进行过滤。
    """

    def __init__(self):
        """初始化向量检索器，创建Milvus客户端和嵌入服务实例。"""
        self.milvus_client = MilvusClient()
        self.embedding_service = get_embedding_service()

    def retrieve(self, query: str, top_k: int = 10, kb_id: Optional[int] = None, kb_ids: Optional[List[int]] = None) -> List[SearchResult]:
        """执行向量相似度检索。
        
        将查询文本转换为向量表示，然后在Milvus向量数据库中搜索最相似的文档片段。
        支持单个或多个知识库的过滤条件。
        
        Args:
            query: 查询文本字符串，将被转换为向量进行相似度搜索。
            top_k: 返回的最相似结果数量，默认为10。
            kb_id: 单个知识库的ID，用于过滤搜索结果。与kb_ids互斥。
            kb_ids: 多个知识库的ID列表，用于过滤搜索结果。与kb_id互斥。
            
        Returns:
            SearchResult对象列表，按相似度分数降序排列。
            如果查询向量化失败，则返回空列表。
        """
        # 将查询文本转换为向量表示
        query_vector = self.embedding_service.embed_query(query)
        if not query_vector:
            return []
            
        # 构建Milvus过滤表达式，支持单个或多个知识库的过滤
        expr = None
        if kb_ids:
            # 使用IN操作符匹配多个知识库ID
            expr = f"kb_id in {kb_ids}"
        elif kb_id is not None:
            # 使用等于操作符匹配单个知识库ID
            expr = f"kb_id == {kb_id}"
            
        # 在Milvus中执行向量相似度搜索
        results = self.milvus_client.search(query_vector, top_k=top_k, expr=expr)
        
        return results
