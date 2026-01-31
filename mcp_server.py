"""
MCP Server - 完整 MCP 协议支持
"""

import asyncio
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============ MCP 协议定义 ============

MCP_VERSION = "2024-11-05"


@dataclass
class MCPMessage:
    """MCP 消息"""
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: Optional[str] = None
    params: Optional[Dict] = None
    result: Optional[Any] = None
    error: Optional[Dict] = None


# ============ MCP 工具定义 ============

MCP_TOOLS = [
    {
        "name": "search_code",
        "description": "用自然语言搜索代码库中的相关代码片段，支持多种检索策略",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "自然语言查询"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 10
                },
                "language": {
                    "type": "string",
                    "description": "编程语言过滤（可选）"
                },
                "include_callers": {
                    "type": "boolean",
                    "description": "是否包含调用方",
                    "default": False
                },
                "include_callees": {
                    "type": "boolean",
                    "description": "是否包含被调用方",
                    "default": False
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "index_codebase",
        "description": "索引整个代码库，支持全量和增量索引",
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "代码库路径"
                },
                "incremental": {
                    "type": "boolean",
                    "description": "是否增量更新",
                    "default": True
                }
            },
            "required": ["directory"]
        }
    },
    {
        "name": "get_file_context",
        "description": "获取文件的上下文信息，包括函数、类定义和依赖关系",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "find_related_code",
        "description": "查找与指定代码相关的其他代码片段（通过调用链和依赖关系）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID（格式: file_path:name:line）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 10
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_call_hierarchy",
        "description": "获取函数的调用层次结构（调用链上下游）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "最大追溯深度",
                    "default": 3
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "explain_query",
        "description": "解释搜索结果，说明为什么返回这些代码片段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "查询语句"
                },
                "max_results": {
                    "type": "integer",
                    "description": "分析结果数量",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "build_context",
        "description": "为 AI 生成最佳上下文，用于处理复杂任务",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "任务描述"
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "最大 token 数",
                    "default": 8000
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_dependency_graph",
        "description": "获取文件的依赖图，包括导入和调用关系",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径"
                }
            },
            "required": ["file_path"]
        }
    }
]


class MCPServer:
    """MCP 服务器"""
    
    def __init__(self, retriever, indexer, reasoning_engine):
        self.retriever = retriever
        self.indexer = indexer
        self.reasoning = reasoning_engine
        self._request_id = 0
    
    async def handle_request(self, message: dict) -> dict:
        """处理 MCP 请求"""
        msg = MCPMessage(**message)
        
        handlers = {
            "initialize": self._handle_initialize,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
        }
        
        handler = handlers.get(msg.method)
        if handler:
            return await handler(msg.params or {})
        else:
            return {"error": {"code": -32601, "message": f"Unknown method: {msg.method}"}}
    
    async def _handle_initialize(self, params: dict) -> dict:
        """初始化"""
        return {
            "serverInfo": {
                "name": "code-context-engine",
                "version": "0.2.0"
            },
            "protocolVersion": MCP_VERSION,
            "capabilities": {
                "tools": {
                    "list": True,
                    "call": True
                },
                "resources": {
                    "list": True,
                    "read": True
                }
            }
        }
    
    async def _handle_tools_list(self, params: dict) -> dict:
        """列出工具"""
        return {"tools": MCP_TOOLS}
    
    async def _handle_tools_call(self, params: dict) -> dict:
        """调用工具"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        handlers = {
            "search_code": self._tool_search_code,
            "index_codebase": self._tool_index_codebase,
            "get_file_context": self._tool_get_file_context,
            "find_related_code": self._tool_find_related_code,
            "get_call_hierarchy": self._tool_get_call_hierarchy,
            "explain_query": self._tool_explain_query,
            "build_context": self._tool_build_context,
            "get_dependency_graph": self._tool_get_dependency_graph,
        }
        
        handler = handlers.get(tool_name)
        if handler:
            try:
                result = await handler(arguments)
                return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]}
            except Exception as e:
                import traceback
                traceback.print_exc()
                return {"content": [{"type": "text", "text": f"Error: {str(e)}"}]}
        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]}
    
    async def _tool_search_code(self, args: dict) -> dict:
        """搜索代码"""
        context = {
            "query": args["query"],
            "language": args.get("language"),
            "max_results": args.get("limit", 10),
            "include_callers": args.get("include_callers", False),
            "include_callees": args.get("include_callees", False),
        }
        
        from core import RetrievalContext
        retriever_context = RetrievalContext(**context)
        results = await self.retriever.search(retriever_context)
        
        return {
            "results": [
                {
                    "name": r.name,
                    "entity_type": r.entity_type,
                    "file_path": r.file_path,
                    "lines": f"{r.start_line}-{r.end_line}",
                    "score": round(r.score, 3),
                    "content_preview": r.content[:200]
                }
                for r in results
            ],
            "total": len(results)
        }
    
    async def _tool_index_codebase(self, args: dict) -> dict:
        """索引代码库"""
        progress = await self.indexer.index_directory(
            args["directory"],
            incremental=args.get("incremental", True)
        )
        return {"status": "completed", "progress": progress.to_dict()}
    
    async def _tool_get_file_context(self, args: dict) -> dict:
        """获取文件上下文"""
        file_path = args["file_path"]
        
        # 获取文件中的实体
        entities = self.indexer.graph_store.get_file_entities(file_path)
        
        # 获取依赖图
        dep_graph = self.indexer.graph_store.get_dependency_graph(file_path)
        
        return {
            "file_path": file_path,
            "entities_count": len(entities),
            "entities": entities[:20],
            "dependency_graph": dep_graph
        }
    
    async def _tool_find_related_code(self, args: dict) -> dict:
        """查找相关代码"""
        results = await self.retriever.find_related(
            args["entity_id"],
            limit=args.get("limit", 10)
        )
        
        return {
            "entity_id": args["entity_id"],
            "related": [
                {
                    "name": r.name,
                    "entity_type": r.entity_type,
                    "file_path": r.file_path,
                    "relation": r.metadata.get("relation", "unknown")
                }
                for r in results
            ]
        }
    
    async def _tool_get_call_hierarchy(self, args: dict) -> dict:
        """获取调用层次"""
        return await self.retriever.get_call_hierarchy(
            args["entity_id"],
            max_depth=args.get("max_depth", 3)
        )
    
    async def _tool_explain_query(self, args: dict) -> dict:
        """解释查询"""
        return await self.retriever.explain_query(
            args["query"],
            max_results=args.get("max_results", 5)
        )
    
    async def _tool_build_context(self, args: dict) -> dict:
        """构建上下文"""
        return await self.reasoning.build_context_for_ai(
            args["query"],
            max_tokens=args.get("max_tokens", 8000)
        )
    
    async def _tool_get_dependency_graph(self, args: dict) -> dict:
        """获取依赖图"""
        return self.indexer.graph_store.get_dependency_graph(args["file_path"])
    
    async def _handle_resources_list(self, params: dict) -> dict:
        """列出资源"""
        return {
            "resources": [
                {
                    "uri": "code://status",
                    "name": "索引状态",
                    "description": "当前代码库的索引状态"
                },
                {
                    "uri": "code://stats",
                    "name": "统计信息",
                    "description": "索引统计信息"
                }
            ]
        }
    
    async def _handle_resources_read(self, params: dict) -> dict:
        """读取资源"""
        uri = params.get("uri")
        
        if uri == "code://status":
            progress = self.indexer.progress.to_dict()
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(progress, ensure_ascii=False)
                }]
            }
        elif uri == "code://stats":
            stats = await self.indexer.vector_store.get_stats()
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(stats, ensure_ascii=False)
                }]
            }
        
        return {"error": f"Unknown resource: {uri}"}


# ============ FastAPI 集成 ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    print("🚀 启动 Code Context Engine...")
    
    # 初始化组件
    from config import config
    from core import VectorStore, KnowledgeGraph, CodeIndexer, RetrievalEngine, ReasoningEngine
    
    vector_store = VectorStore(config)
    graph_store = KnowledgeGraph(config)
    indexer = CodeIndexer(config, vector_store, graph_store)
    retriever = RetrievalEngine(vector_store, graph_store)
    reasoning = ReasoningEngine(retriever)
    
    # 创建 MCP Server
    mcp_server = MCPServer(retriever, indexer, reasoning)
    
    app.state.mcp_server = mcp_server
    app.state.retriever = retriever
    app.state.reasoning = reasoning
    app.state.indexer = indexer
    
    print(f"✅ 服务启动完成")
    print(f"📚 REST API: http://{config.server.host}:{config.server.port}/docs")
    print(f"🔌 MCP Endpoint: http://{config.server.host}:{config.server.port}/mcp")
    
    yield
    
    await vector_store.close()
    graph_store.close()


app = FastAPI(
    title="Code Context Engine (MCP + API)",
    description="代码库上下文引擎 - 超越 Augment ACE 的智能代码检索",
    version="0.2.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ MCP 端点 ============

@app.post("/mcp")
async def mcp_endpoint(request: dict):
    """MCP 协议端点"""
    mcp_server = app.state.mcp_server
    return await mcp_server.handle_request(request)


# ============ REST API ============

from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/health")
async def health():
    """健康检查"""
    try:
        stats = await app.state.indexer.vector_store.get_stats()
        return {
            "status": "healthy",
            "mcp_enabled": True,
            "version": "0.2.0",
            "stats": stats
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.post("/api/v1/search")
async def search(request: dict):
    """搜索代码"""
    from core import RetrievalContext
    
    context = RetrievalContext(
        query=request["query"],
        language=request.get("language"),
        file_path=request.get("file_path"),
        max_results=request.get("limit", 10),
        include_callers=request.get("include_callers", False),
        include_callees=request.get("include_callees", False)
    )
    
    results = await app.state.retriever.search(context)
    
    return {
        "results": [
            {
                "id": r.id,
                "name": r.name,
                "entity_type": r.entity_type,
                "file_path": r.file_path,
                "lines": f"{r.start_line}-{r.end_line}",
                "score": round(r.score, 3),
                "content_preview": r.content[:200]
            }
            for r in results
        ],
        "total": len(results)
    }


@router.post("/api/v1/index")
async def index(request: dict):
    """索引代码"""
    progress = await app.state.indexer.index_directory(
        request["directory"],
        incremental=request.get("incremental", True)
    )
    return {"status": "completed", "progress": progress.to_dict()}


@router.post("/api/v1/context")
async def build_context(request: dict):
    """为 AI 构建上下文"""
    result = await app.state.reasoning.build_context_for_ai(
        request["query"],
        max_tokens=request.get("max_tokens", 8000)
    )
    return result


@router.get("/api/v1/progress")
async def get_progress():
    """索引进度"""
    return app.state.indexer.progress.to_dict()


@router.get("/api/v1/graph/{entity_id}")
async def get_call_hierarchy(entity_id: str):
    """获取调用层次"""
    return await app.state.retriever.get_call_hierarchy(entity_id)


if __name__ == "__main__":
    import uvicorn
    from config import config
    
    uvicorn.run(
        "mcp_server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug
    )
