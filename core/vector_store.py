"""
向量存储服务 - Qdrant
"""

import json
import uuid
from typing import List, Dict, Optional, Any
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct, 
    Filter, FieldCondition, MatchValue, MatchText
)
import httpx
import numpy as np


class VectorStore:
    """向量存储"""
    
    def __init__(self, config):
        self.config = config.qdrant
        self.vector_config = config.vector
        self.collection_name = self.config.collection_name
        
        # 连接 Qdrant
        self.client = QdrantClient(
            host=self.config.host,
            port=self.config.port,
        )
        
        # HTTP 客户端（调用向量 API）
        self.http_client = httpx.AsyncClient(timeout=60.0)
        
        # 确保 collection 存在
        self._ensure_collection()
    
    def _ensure_collection(self):
        """确保 collection 存在"""
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]
            
            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_config.dimensions,
                        distance=Distance.COSINE
                    )
                )
                # 创建索引
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="file_path",
                    field_schema="keyword"
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="entity_type",
                    field_schema="keyword"
                )
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="language",
                    field_schema="keyword"
                )
        except Exception as e:
            print(f"警告: 无法创建 collection: {e}")
    
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """调用外部 API 获取向量"""
        url = self.vector_config.api_url
        model = self.vector_config.model
        
        # OpenAI 兼容格式
        if "/embeddings" in url:
            response = await self.http_client.post(
                url,
                json={
                    "model": model,
                    "input": texts
                },
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            data = response.json()
            return [item['embedding'] for item in data['data']]
        
        # 其他格式
        raise ValueError(f"不支持的向量 API: {url}")
    
    async def index_entity(self, entity_id: str, content: str, metadata: Dict):
        """索引单个实体"""
        # 获取向量
        [vector] = await self.get_embeddings([content])
        
        # 存储
        point = PointStruct(
            id=entity_id,
            vector=vector,
            payload={
                **metadata,
                "content": content[:5000],  # 限制存储的内容大小
                "content_hash": str(hash(content))
            }
        )
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point]
        )
    
    async def index_entities(self, entities: List[Dict], batch_size: int = 32):
        """批量索引实体"""
        contents = [e["content"] for e in entities]
        metadatas = [e["metadata"] for e in entities]
        ids = [e["id"] for e in entities]
        
        # 分批处理
        for i in range(0, len(contents), batch_size):
            batch_contents = contents[i:i + batch_size]
            batch_metas = metadatas[i:i + batch_size]
            batch_ids = ids[i:i + batch_size]
            
            # 获取向量
            vectors = await self.get_embeddings(batch_contents)
            
            # 存储
            points = []
            for j, (vector, meta, id_) in enumerate(zip(vectors, batch_metas, batch_ids)):
                point = PointStruct(
                    id=id_,
                    vector=vector,
                    payload={
                        **meta,
                        "content": batch_contents[j][:5000],
                        "content_hash": str(hash(batch_contents[j]))
                    }
                )
                points.append(point)
            
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
    
    async def search(
        self, 
        query: str, 
        limit: int = 10,
        filters: Optional[Dict] = None,
        score_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        # 获取查询向量
        [query_vector] = await self.get_embeddings([query])
        
        # 构建过滤条件
        filter_conditions = []
        if filters:
            if filters.get("file_path"):
                filter_conditions.append(FieldCondition(
                    key="file_path", 
                    match=MatchValue(value=filters["file_path"])
                ))
            if filters.get("entity_type"):
                filter_conditions.append(FieldCondition(
                    key="entity_type",
                    match=MatchValue(value=filters["entity_type"])
                ))
            if filters.get("language"):
                filter_conditions.append(FieldCondition(
                    key="language",
                    match=MatchValue(value=filters["language"])
                ))
        
        query_filter = Filter(must=filter_conditions) if filter_conditions else None
        
        # 搜索
        try:
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
                score_threshold=score_threshold
            )
        except Exception:
            # 如果阈值过滤失败，尝试不带阈值
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter
            )
        
        return self._format_results(results)
    
    async def search_by_entities(
        self, 
        entity_ids: List[str], 
        query: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """基于相关实体的搜索（找邻居）"""
        # 获取相关实体的向量
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=entity_ids
        )
        
        if not points:
            return []
        
        # 计算平均向量
        vectors = [p.vector for p in points]
        avg_vector = np.mean(vectors, axis=0).tolist()
        
        # 搜索相似内容
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=avg_vector,
            limit=limit,
            query_filter=Filter(
                must=[FieldCondition(
                    key="id",
                    match=MatchValue(value="")  # 排除自己
                )]
            )
        )
        
        return self._format_results(results)
    
    def _format_results(self, results) -> List[Dict[str, Any]]:
        """格式化搜索结果"""
        return [
            {
                "id": r.id,
                "score": r.score,
                "content": r.payload.get("content", ""),
                "file_path": r.payload.get("file_path", ""),
                "entity_type": r.payload.get("entity_type", ""),
                "name": r.payload.get("name", ""),
                "language": r.payload.get("language", ""),
                "start_line": r.payload.get("start_line", 0),
                "end_line": r.payload.get("end_line", 0),
                "docstring": r.payload.get("docstring", ""),
            }
            for r in results
        ]
    
    async def delete_by_id(self, entity_id: str):
        """删除实体"""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=[entity_id]
        )
    
    async def delete_by_file(self, file_path: str):
        """删除文件的索引"""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[FieldCondition(
                    key="file_path",
                    match=MatchValue(value=file_path)
                )]
            )
        )
    
    async def clear_all(self):
        """清空所有索引"""
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=Filter(must=[])
        )
    
    async def get_stats(self) -> Dict:
        """获取统计信息"""
        try:
            collection_info = self.client.get_collection(self.collection_name)
            return {
                "vectors_count": collection_info.vectors_count,
                "indexed_points": collection_info.points_count
            }
        except Exception:
            return {"error": "无法获取统计信息"}
    
    async def close(self):
        """关闭连接"""
        await self.http_client.aclose()
