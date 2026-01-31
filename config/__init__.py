"""
Code Context Engine - 配置
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VectorConfig:
    """向量配置"""
    api_url: str = "http://localhost:8000/v1/embeddings"
    model: str = "text-embedding-3-small"
    batch_size: int = 32
    dimensions: int = 1536


@dataclass
class QdrantConfig:
    """Qdrant 向量数据库配置"""
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "code_context_embeddings"


@dataclass
class Neo4jConfig:
    """Neo4j 图数据库配置"""
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"


@dataclass
class IndexerConfig:
    """索引器配置"""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    max_file_size_mb: int = 5
    exclude_patterns: List[str] = field(default_factory=lambda: [
        "node_modules/**",
        ".git/**",
        "dist/**",
        "build/**",
        "*.min.js",
        "*.min.css",
        "*.log",
        ".env",
        "*.pyc",
        "__pycache__/**"
    ])
    languages: List[str] = field(default_factory=lambda: [
        "python", "javascript", "typescript", "go", "rust", 
        "java", "cpp", "c", "ruby", "php", "swift", "kotlin"
    ])


@dataclass
class WatcherConfig:
    """文件监听配置"""
    enabled: bool = True
    debounce_ms: int = 1000
    auto_index: bool = True


@dataclass
class RerankerConfig:
    """重排序模型配置"""
    enabled: bool = True
    api_url: Optional[str] = None
    model: str = "cross-encoder/ms-marco-MiniLM"
    top_k: int = 10


@dataclass
class ServerConfig:
    """服务配置"""
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = True
    workers: int = 1


@dataclass
class CodebaseConfig:
    """代码库配置"""
    paths: List[str] = field(default_factory=lambda: [])
    watch_paths: List[str] = field(default_factory=lambda: [])


class Config:
    """配置单例"""
    
    _instance: Optional['Config'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance
    
    def _load(self):
        """加载配置"""
        config_path = Path(__file__).parent / "settings.json"
        
        if config_path.exists():
            with open(config_path) as f:
                data = json.load(f)
                self.vector = VectorConfig(**data.get("vector", {}))
                self.qdrant = QdrantConfig(**data.get("qdrant", {}))
                self.neo4j = Neo4jConfig(**data.get("neo4j", {}))
                self.indexer = IndexerConfig(**data.get("indexer", {}))
                self.watcher = WatcherConfig(**data.get("watcher", {}))
                self.reranker = RerankerConfig(**data.get("reranker", {}))
                self.server = ServerConfig(**data.get("server", {}))
                self.codebase = CodebaseConfig(**data.get("codebase", {}))
        else:
            self._defaults()
    
    def _defaults(self):
        """默认配置"""
        self.vector = VectorConfig()
        self.qdrant = QdrantConfig()
        self.neo4j = Neo4jConfig()
        self.indexer = IndexerConfig()
        self.watcher = WatcherConfig()
        self.reranker = RerankerConfig()
        self.server = ServerConfig()
        self.codebase = CodebaseConfig()
    
    def save(self):
        """保存配置"""
        config_path = Path(__file__).parent / "settings.json"
        data = {
            "vector": self.vector.__dict__,
            "qdrant": self.qdrant.__dict__,
            "neo4j": self.neo4j.__dict__,
            "indexer": self.indexer.__dict__,
            "watcher": self.watcher.__dict__,
            "reranker": self.reranker.__dict__,
            "server": self.server.__dict__,
            "codebase": self.codebase.__dict__
        }
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def reload(self):
        """重新加载配置"""
        self._load()


# 全局配置
config = Config()
