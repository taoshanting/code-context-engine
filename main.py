"""
REST API Server - Code Context Engine
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    print("启动 Code Context Engine...")

    from config import config
    from core import VectorStore, KnowledgeGraph, CodeIndexer, RetrievalEngine, ReasoningEngine

    vector_store = VectorStore(config)
    graph_store = KnowledgeGraph(config)
    indexer = CodeIndexer(config, vector_store, graph_store)
    retriever = RetrievalEngine(vector_store, graph_store)
    reasoning = ReasoningEngine(retriever)

    app.state.retriever = retriever
    app.state.reasoning = reasoning
    app.state.indexer = indexer

    print(f"服务启动完成")
    print(f"API 文档: http://{config.server.host}:{config.server.port}/docs")

    yield

    await vector_store.close()
    graph_store.close()


app = FastAPI(
    title="Code Context Engine API",
    description="代码库上下文引擎 - 智能代码检索",
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


# ============ API 端点 ============

@app.get("/health")
async def health():
    """健康检查"""
    try:
        stats = await app.state.indexer.vector_store.get_stats()
        return {
            "status": "healthy",
            "version": "0.2.0",
            "stats": stats
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@app.post("/api/v1/search")
async def search(request: dict):
    """搜索代码"""
    from core import RetrievalContext

    context = RetrievalContext(
        query=request.get("query", ""),
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


@app.post("/api/v1/index")
async def index(request: dict):
    """索引代码库"""
    progress = await app.state.indexer.index_directory(
        request["directory"],
        incremental=request.get("incremental", True)
    )
    return {"status": "completed", "progress": progress.to_dict()}


@app.post("/api/v1/context")
async def build_context(request: dict):
    """为 AI 构建上下文"""
    result = await app.state.reasoning.build_context_for_ai(
        request.get("query", ""),
        max_tokens=request.get("max_tokens", 8000)
    )
    return result


@app.get("/api/v1/progress")
async def get_progress():
    """索引进度"""
    return app.state.indexer.progress.to_dict()


@app.get("/api/v1/graph/{entity_id}")
async def get_call_hierarchy(entity_id: str):
    """获取调用层次"""
    return await app.state.retriever.get_call_hierarchy(entity_id)


@app.get("/api/v1/files/{file_path:path}/entities")
async def get_file_entities(file_path: str):
    """获取文件中的实体"""
    return app.state.indexer.graph_store.get_file_entities(file_path)


@app.get("/api/v1/files/{file_path:path}/dependencies")
async def get_dependencies(file_path: str):
    """获取文件依赖图"""
    return app.state.indexer.graph_store.get_dependency_graph(file_path)


if __name__ == "__main__":
    from config import config

    uvicorn.run(
        "main:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.debug
    )
