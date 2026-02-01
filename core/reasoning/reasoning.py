"""
推理引擎 - 智能上下文选择
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
import asyncio
import logging

from .retriever import RetrievalEngine, RetrievalContext, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class ContextItem:
    """上下文项"""
    entity_id: str
    name: str
    entity_type: str
    file_path: str
    content: str
    importance: float
    relevance: float
    reason: str


@dataclass
class QueryIntent:
    """查询意图"""
    intent_type: str  # find_implementation, understand_flow, refactor, debug
    target_entity: Optional[str] = None
    target_file: Optional[str] = None
    language: Optional[str] = None
    constraints: List[str] = field(default_factory=list)


class ReasoningEngine:
    """推理引擎 - 智能上下文选择和推理"""
    
    def __init__(self, retriever: RetrievalEngine):
        self.retriever = retriever
    
    async def analyze_intent(self, query: str) -> QueryIntent:
        """分析查询意图"""
        query_lower = query.lower()
        
        # 意图分类
        if any(kw in query_lower for kw in ["实现", "写", "create", "add", "implement"]):
            intent_type = "find_implementation"
        elif any(kw in query_lower for kw in ["流程", "流程图", "如何工作", "flow", "how"]):
            intent_type = "understand_flow"
        elif any(kw in query_lower for kw in ["重构", "优化", "refactor", "improve", "optimize"]):
            intent_type = "refactor"
        elif any(kw in query_lower for kw in ["bug", "错误", "修复", "fix", "debug"]):
            intent_type = "debug"
        else:
            intent_type = "find_implementation"
        
        # 提取目标实体
        target_entity = self._extract_entity(query)
        
        # 提取目标语言
        language = self._extract_language(query)
        
        return QueryIntent(
            intent_type=intent_type,
            target_entity=target_entity,
            language=language
        )
    
    def _extract_entity(self, query: str) -> Optional[str]:
        """提取目标实体名"""
        # 简单提取：查找常见的函数/类名模式
        import re
        patterns = [
            r"([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",  # foo.bar
            r"[的](\w+)",  # 的foo
        ]
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                return match.group(1)
        return None
    
    def _extract_language(self, query: str) -> Optional[str]:
        """提取编程语言"""
        lang_map = {
            "python": ["python", "py"],
            "typescript": ["typescript", "ts"],
            "javascript": ["javascript", "js"],
            "go": ["go ", "golang"],
            "rust": ["rust"],
            "java": ["java"],
        }
        query_lower = query.lower()
        for lang, keywords in lang_map.items():
            if any(kw in query_lower for kw in keywords):
                return lang
        return None
    
    async def select_context(
        self, 
        query: str,
        max_items: int = 10
    ) -> List[ContextItem]:
        """选择最佳上下文"""
        # 分析意图
        intent = await self.analyze_intent(query)
        
        # 检索初始结果
        context = RetrievalContext(
            query=query,
            language=intent.language,
            max_results=max_items * 2,
            include_callers=intent.intent_type in ["understand_flow", "refactor"],
            include_callees=intent.intent_type in ["understand_flow"]
        )
        
        results = await self.retriever.search(context)
        
        # 根据意图调整上下文选择
        context_items = []
        for result in results:
            importance = self._calculate_importance(result, intent)
            relevance = self._calculate_relevance(result, query)
            
            context_items.append(ContextItem(
                entity_id=result.id,
                name=result.name,
                entity_type=result.entity_type,
                file_path=result.file_path,
                content=result.content[:500],  # 限制内容长度
                importance=importance,
                relevance=relevance,
                reason=self._generate_reason(result, intent)
            ))
        
        # 综合排序
        context_items.sort(key=lambda x: x.importance * 0.3 + x.relevance * 0.7, reverse=True)
        
        return context_items[:max_items]
    
    def _calculate_importance(self, result: SearchResult, intent: QueryIntent) -> float:
        """计算重要性分数"""
        importance = 0.5  # 基础分数
        
        # 1. 实体类型重要性
        type_importance = {
            "class": 1.0,
            "function": 0.8,
            "method": 0.7,
            "variable": 0.3,
        }
        importance += type_importance.get(result.entity_type, 0) * 0.2
        
        # 2. 复杂度作为重要性指标
        if result.metadata.get("complexity", 0) > 20:
            importance += 0.1  # 高复杂度通常更重要
        
        # 3. 如果是目标实体，加分
        if intent.target_entity and intent.target_entity.lower() in result.name.lower():
            importance += 0.3
        
        # 4. 有 docstring 加分
        if result.docstring:
            importance += 0.1
        
        return min(importance, 1.0)
    
    def _calculate_relevance(self, result: SearchResult, query: str) -> float:
        """计算相关性分数"""
        relevance = result.relevance_score
        
        # 查询词匹配
        query_terms = query.lower().split()
        content_lower = (result.name + " " + result.docstring + " " + result.content).lower()
        
        for term in query_terms:
            if term in result.name.lower():
                relevance += 0.2
            elif term in result.docstring.lower():
                relevance += 0.1
        
        return min(relevance, 1.0)
    
    def _generate_reason(self, result: SearchResult, intent: QueryIntent) -> str:
        """生成选择理由"""
        reasons = []
        
        if intent.target_entity and intent.target_entity.lower() in result.name.lower():
            reasons.append(f"目标实体: {result.name}")
        
        if result.docstring:
            reasons.append("有文档说明")
        
        if intent.intent_type == "understand_flow":
            if result.entity_type in ["class", "function"]:
                reasons.append(f"是{result.entity_type}，适合理解流程")
        
        return "; ".join(reasons) if reasons else "匹配查询"
    
    async def build_context_for_ai(
        self, 
        query: str,
        max_tokens: int = 8000
    ) -> Dict[str, Any]:
        """为 AI 构建最佳上下文"""
        # 选择上下文
        context_items = await self.select_context(query)
        
        # 构建上下文内容
        context_parts = []
        total_tokens = 0
        
        for item in context_items:
            content = f"""
## {item.name} ({item.entity_type})
文件: {item.file_path}
重要性: {item.importance:.2f}
原因: {item.reason}

```code
{item.content}
```
"""
            # 估算 token 数（简单估算：4字符≈1token）
            content_tokens = len(content) // 4
            
            if total_tokens + content_tokens > max_tokens:
                break
            
            context_parts.append(content)
            total_tokens += content_tokens
        
        # 生成摘要
        summary = f"""
根据查询「{query}」，我为你准备了以下代码上下文：

已选择 {len(context_parts)} 个相关代码片段，总计约 {total_tokens} tokens。

这些代码片段根据以下标准选择：
1. 与查询的相关性
2. 代码重要性（类型、复杂度、文档）
3. 调用链关系（上下游函数）

建议关注：
- 先查看最重要的函数/类定义
- 了解调用关系来理解整体流程
"""
        
        return {
            "query": query,
            "summary": summary,
            "context": "\n".join(context_parts),
            "items_count": len(context_parts),
            "estimated_tokens": total_tokens,
            "selected_files": list(set(item.file_path for item in context_items))
        }
