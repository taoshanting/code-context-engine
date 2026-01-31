"""
索引器 - 完整代码索引流程
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict
from datetime import datetime
from tqdm import tqdm
import hashlib
import json
import logging

from .parser.code_parser import CodeParser
from .vector_store import VectorStore
from .graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


@dataclass
class IndexProgress:
    """索引进度"""
    total_files: int = 0
    indexed_files: int = 0
    total_entities: int = 0
    current_file: Optional[str] = None
    status: str = "idle"
    start_time: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    
    def to_dict(self):
        return {
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "total_entities": self.total_entities,
            "current_file": self.current_file,
            "status": self.status,
            "elapsed_seconds": (
                (datetime.now() - self.start_time).total_seconds() 
                if self.start_time else 0
            ),
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


@dataclass
class EntityDocument:
    """实体文档"""
    id: str
    name: str
    entity_type: str
    file_path: str
    language: str
    content: str
    docstring: str
    start_line: int
    end_line: int
    parameters: List[str]
    calls: List[str]
    children: List[str]
    complexity: int
    code_hash: str
    metadata: Dict


class CodeIndexer:
    """代码索引器 - 整合解析、向量存储、图存储"""
    
    def __init__(self, config, vector_store: VectorStore, graph_store: KnowledgeGraph):
        self.config = config.indexer
        self.vector_store = vector_store
        self.graph_store = graph_store
        self.parser = CodeParser()
        
        self.progress = IndexProgress()
        self._file_hashes: Dict[str, str] = {}  # 文件内容哈希
    
    async def index_directory(
        self, 
        directory: str, 
        show_progress: bool = True,
        incremental: bool = True
    ) -> IndexProgress:
        """索引整个目录"""
        dir_path = Path(directory)
        if not dir_path.exists():
            raise ValueError(f"目录不存在: {directory}")
        
        self.progress.status = "indexing"
        self.progress.start_time = datetime.now()
        
        # 收集文件
        files = self._collect_files(dir_path)
        self.progress.total_files = len(files)
        
        if show_progress:
            files = tqdm(files, desc="索引文件中")
        
        all_entities = []
        
        for file_path in files:
            if show_progress:
                self.progress.current_file = str(file_path)
            
            try:
                # 检查是否需要重新索引
                if incremental and not self._needs_reindex(file_path):
                    if show_progress:
                        files.set_postfix({"skip": "✓"})
                    continue
                
                # 解析文件
                entities = self.parser.parse_file(file_path)
                
                if not entities:
                    continue
                
                # 创建文档
                for entity in entities:
                    doc = self._entity_to_document(entity, file_path)
                    all_entities.append(doc)
                    
                    # 更新图谱
                    await self._update_graph(entity, file_path)
                
                self.progress.total_entities += len(entities)
                self.progress.indexed_files += 1
                self.progress.last_updated = datetime.now()
                
                # 批量索引到向量存储
                if len(all_entities) >= 50:
                    await self._batch_index(all_entities)
                    all_entities = []
                    
            except Exception as e:
                logger.error(f"索引失败 {file_path}: {e}")
                if show_progress:
                    print(f"\n警告: {file_path} - {e}")
                continue
        
        # 索引剩余实体
        if all_entities:
            await self._batch_index(all_entities)
        
        self.progress.status = "completed"
        return self.progress
    
    def _collect_files(self, directory: Path) -> List[Path]:
        """收集所有需要索引的文件"""
        files = []
        
        for root, dirs, filenames in directory.walk():
            root_path = Path(root)
            
            # 过滤目录
            dirs[:] = [d for d in dirs if not any(
                self._match_pattern(d, pattern)
                for pattern in self.config.exclude_patterns
            )]
            
            for filename in filenames:
                file_path = root_path / filename
                
                # 检查排除模式
                rel_path = str(file_path.relative_to(directory))
                if any(self._match_pattern(rel_path, pattern) 
                       for pattern in self.config.exclude_patterns):
                    continue
                
                # 检查文件大小
                try:
                    if file_path.stat().st_size > self.config.max_file_size_mb * 1024 * 1024:
                        continue
                except Exception:
                    continue
                
                files.append(file_path)
        
        return files
    
    def _match_pattern(self, path: str, pattern: str) -> bool:
        """简单的模式匹配"""
        from fnmatch import fnmatch
        return fnmatch(path, pattern) or fnmatch(path, pattern.rstrip('/'))
    
    def _needs_reindex(self, file_path: Path) -> bool:
        """检查文件是否需要重新索引"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            file_hash = hashlib.md5(content.encode()).hexdigest()
            
            rel_path = str(file_path)
            old_hash = self._file_hashes.get(rel_path)
            
            if old_hash != file_hash:
                self._file_hashes[rel_path] = file_hash
                return True
            
            return False
        except Exception:
            return True
    
    def _entity_to_document(self, entity, file_path: Path) -> EntityDocument:
        """将实体转换为文档"""
        content = entity.code
        code_hash = hashlib.md5(content.encode()).hexdigest()
        
        # 生成唯一 ID
        entity_id = f"{file_path}:{entity.name}:{entity.start_line}"
        
        return EntityDocument(
            id=entity_id,
            name=entity.name,
            entity_type=entity.entity_type,
            file_path=str(file_path),
            language=entity.language,
            content=content,
            docstring=entity.docstring or "",
            start_line=entity.start_line,
            end_line=entity.end_line,
            parameters=entity.parameters,
            calls=entity.calls,
            children=entity.children,
            complexity=entity.complexity,
            code_hash=code_hash,
            metadata={
                "decorators": entity.decorators,
                "imports": entity.imports
            }
        )
    
    async def _update_graph(self, entity, file_path: Path):
        """更新知识图谱"""
        entity_id = f"{file_path}:{entity.name}:{entity.start_line}"
        
        # 创建实体节点
        self.graph_store.upsert_entity(
            entity_id=entity_id,
            entity_type=entity.entity_type,
            name=entity.name,
            file_path=str(file_path),
            start_line=entity.start_line,
            end_line=entity.end_line,
            complexity=entity.complexity,
            language=entity.language
        )
        
        # 创建文件节点和关系
        self.graph_store.upsert_file(str(file_path))
        self.graph_store.create_defines_relation(str(file_path), entity_id)
        
        # 创建调用关系
        for i, call in enumerate(entity.calls[:20]):  # 限制调用数量
            callee_id = f"*:{call}:*"  # 简化处理
            self.graph_store.create_calls_relation(entity_id, callee_id, i)
        
        # 创建包含关系（类的方法）
        if entity.entity_type == "class":
            for child_name in entity.children[:50]:
                child_id = f"{file_path}:{child_name}:*"
                self.graph_store.create_contains_relation(entity_id, child_id)
    
    async def _batch_index(self, documents: List[EntityDocument]):
        """批量索引到向量存储"""
        entities = []
        for doc in documents:
            # 生成内容（包含 docstring 和签名）
            full_content = f"""
{self._generate_description(doc)}
{doc.content}
"""
            
            entities.append({
                "id": doc.id,
                "content": full_content,
                "metadata": {
                    "id": doc.id,
                    "name": doc.name,
                    "entity_type": doc.entity_type,
                    "file_path": doc.file_path,
                    "language": doc.language,
                    "docstring": doc.docstring,
                    "start_line": doc.start_line,
                    "end_line": doc.end_line,
                    "complexity": doc.complexity,
                    "parameters": doc.parameters,
                    "children": doc.children
                }
            })
        
        await self.vector_store.index_entities(entities)
    
    def _generate_description(self, doc: EntityDocument) -> str:
        """生成自然语言描述"""
        lines = []
        
        # 函数/方法签名
        if doc.entity_type in ["function", "method"]:
            params = ", ".join(doc.parameters) if doc.parameters else ""
            lines.append(f"Function: {doc.name}({params})")
        elif doc.entity_type == "class":
            lines.append(f"Class: {doc.name}")
        
        # Docstring
        if doc.docstring:
            lines.append(f"Description: {doc.docstring}")
        
        # 复杂度
        if doc.complexity > 10:
            lines.append(f"Complexity: {doc.complexity} (high)")
        
        # 调用关系
        if doc.calls:
            lines.append(f"Calls: {', '.join(doc.calls[:5])}")
        
        return "\n".join(lines)
    
    async def remove_file(self, file_path: str):
        """删除文件索引"""
        await self.vector_store.delete_by_file(file_path)
        # 图谱中的删除需要在图谱类中实现
    
    async def reindex_file(self, file_path: str):
        """重新索引文件"""
        await self.remove_file(file_path)
        path = Path(file_path)
        if path.exists():
            await self.index_directory(str(path.parent), show_progress=False)
    
    async def reindex_all(self, directories: List[str], show_progress: bool = True):
        """重新索引所有"""
        # 清空现有索引
        await self.vector_store.clear_all()
        self.graph_store.clear_all()
        self._file_hashes.clear()
        
        # 重新索引
        for directory in directories:
            await self.index_directory(directory, show_progress)
