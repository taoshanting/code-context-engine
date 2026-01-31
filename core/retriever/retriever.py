"""
检索引擎 - 多策略检索 + 重排序
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
import asyncio
import logging

from .vector_store import VectorStore
from .graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    name: str
    entity_type: str
    file_path: str
    language: str
    content: str
    docstring: str
    start_line: int
    end_line: int
    score: float
    relevance_score: float = 0.0  # 重排序后的相关性分数
    metadata: Dict = field(default_factory=dict)


@dataclass
class RetrievalContext:
    """检索上下文"""
    query: str
    language: Optional[str] = None
    file_path: Optional[str] = None
    entity_type: Optional[str] = None
    max_results: int = 10
    include_callers: bool = False
    include_callees: bool = False
    max_depth: int = 2


class RetrievalEngine:
    """检索引擎 - 多种检索策略"""
    
    def __init__(self, vector_store: VectorStore, graph_store: KnowledgeGraph):
        self.vector_store = vector_store
        self.graph_store = graph_store
        self._reranker = None  # 延迟加载
    
    async def search(self, context: RetrievalContext) -> List[SearchResult]:
        """综合搜索"""
        results = []
        
        # 策略1: 向量检索
        vector_results = await self._vector_search(context)
        results.extend(vector_results)
        
        # 策略2: 如果开启了调用链追踪，获取相关实体
        if context.include_callers or context.include_callees:
            call_chain_results = await self._call_chain_search(context)
            results.extend(call_chain_results)
        
        # 去重
        results = self._dedupe(results)
        
        # 重排序
        results = await self._rerank(context.query, results)
        
        # 返回 top k
        return results[:context.max_results]
    
    async def _vector_search(self, context: RetrievalContext) -> List[SearchResult]:
        """向量检索"""
        filters = {}
        if context.language:
            filters["language"] = context.language
        if context.file_path:
            filters["file_path"] = context.file_path
        if context.entity_type:
            filters["entity_type"] = context.entity_type
        
        raw_results = await self.vector_store.search(
            query=context.query,
            limit=context.max_results * 2,
            filters=filters
        )
        
        return [
            SearchResult(
                id=r["id"],
                name=r["name"],
                entity_type=r["entity_type"],
                file_path=r["file_path"],
                language=r["language"],
                content=r["content"],
                docstring=r["docstring"],
                start_line=r["start_line"],
                end_line=r["end_line"],
                score=r["score"],
                metadata={
                    "content_preview": r["content"][:200],
                }
            )
            for r in raw_results
        ]
    
    async def _call_chain_search(self, context: RetrievalContext) -> List[SearchResult]:
        """调用链检索"""
        # 先做一次向量搜索找到种子实体
        seed_results = await self._vector_search(context)
        
        if not seed_results:
            return []
        
        additional_results = []
        
        for result in seed_results[:3]:  # 只取 top 3 作为种子
            if context.include_callers:
                callers = self.graph_store.get_callers(result.id, depth=context.max_depth)
                for caller in callers:
                    entity_info = self.graph_store.get_entity(caller["id"])
                    if entity_info:
                        additional_results.append(SearchResult(
                            id=caller["id"],
                            name=caller["name"],
                            entity_type=caller["type"],
                            file_path=entity_info.get("file_path", ""),
                            language="",
                            content="",
                            docstring="",
                            start_line=0,
                            end_line=0,
                            score=0.5,的基础  # 较低分数
                            metadata={"source": "callers"}
                        ))
            
            if context.include_callees:
                callees = self.graph_store.get_callees(result.id, depth=context.max_depth)
                for callee in callees:
                    entity_info = self.graph_store.get_entity(callee["id"])
                    if entity_info:
                        additional_results.append(SearchResult(
                            id=callee["id"],
                            name=callee["name"],
                            entity_type=callee["type"],
                            file_path=entity_info.get("file_path", ""),
                            language="",
                            content="",
                            docstring="",
                            start_line=0,
                            end_line=0,
                            score=0.5,
                            metadata={"source": "callees"}
                        ))
        
        return additional_results
    
    def _dedupe(self, results: List[SearchResult]) -> List[SearchResult]:
        """去重"""
        seen = set()
        unique = []
        for r in results:
            if r.id not in seen:
                seen.add(r.id)
                unique.append(r)
        return unique
    
    async def _rerank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        """重排序 - 精排模型"""
        if not results:
            return []
        
        # 如果没有配置重排序模型，使用简单的规则重排
        for r in results:
            # 基础分数 + 规则调整
            adjusted_score = r.score
            
            # 1. 函数/类名匹配关键词，加分
            if any(kw.lower() in r.name.lower() for kw in query.split()):
                adjusted_score += 0.1
            
            # 2. 有 docstring 加分
            if r.docstring:
                adjusted_score += 0.05
            
            # 3. 复杂度适中（不太高也不太低）加分
            # 假设复杂度 1-50 是合理的
            pass  # 暂时不做调整
            
            r.relevance_score = adjusted_score
        
        # 按重排序分数排序
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        
        return results
    
    async def explain_query(self, query: str, max_results: int = 5) -> Dict:
        """查询分析 - 解释为什么返回这些结果"""
        context = RetrievalContext(query=query, max_results=max_results)
        results = await self.search(context)
        
        return {
            "query": query,
            "results_count": len(results),
            "analysis": {
                "search_strategy": "hybrid",
                "strategies_used": ["vector_similarity"],
                "reranking": "rule_based"
            },
            "top_results": [
                {
                    "name": r.name,
                    "entity_type": r.entity_type,
                    "file_path": r.file_path,
                    "line_range": f"{r.start_line}-{r.end_line}",
                    "score": round(r.score, 3),
                    "relevance_score": round(r.relevance_score, 3),
                    "why": self._explain_result(query, r)
                }
                for r in results
            ]
        }
    
    def _explain_result(self, query: str, result: SearchResult) -> str:
        """解释为什么返回这个结果"""
        reasons = []
        
        # 向量相似度
        reasons.append(f"向量相似度: {result.score:.2f}")
        
        # 关键词匹配
        query_terms = query.lower().split()
        if any(term in result.name.lower() for term in query_terms):
            reasons.append("名称包含关键词")
        
        if result.docstring and any(term in result.docstring.lower() for term in query_terms):
            reasons.append("文档包含关键词")
        
        # 类型匹配
        if result.entity_type in query.lower():
            reasons.append(f"类型匹配: {result.entity_type}")
        
        return "; ".join(reasons)
    
    async def find_related(
        self, 
        entity_id: str, 
        max_results: int = 10
    ) -> List[SearchResult]:
        """查找相关实体"""
        # 从图谱获取相关实体
        related = self.graph_store.get_related_entities(entity_id, limit=max_results * 2)
        
        results = []
        for r in related:
            entity_info = self.graph_store.get_entity(r["id"])
            if entity_info:
                results.append(SearchResult(
                    id=r["id"],
                    name=r["name"],
                    entity_type=r["type"],
                    file_path=entity_info.get("file_path", ""),
                    language=entity_info.get("language", ""),
                    content="",
                    docstring="",
                    start_line=entity_info.get("start_line", 0),
                    end_line=entity_info.get("end_line", 0),
                    score=0.6,
                    metadata={"relation": r.get("relation", "unknown")}
                ))
        
        return results
    
    async def get_call_hierarchy(
        self, 
        entity_id: str, 
        max_depth: int = 3
    ) -> Dict:
        """获取调用层次结构"""
        callers = self.graph_store.get_callers(entity_id, depth=max_depth)
        callees = self.graph_store.get_callees(entity_id, depth=max_depth)
        
        return {
            "entity_id": entity_id,
            "callers": callers,
            "callees": callees,
            "depth": max_depth
        }
