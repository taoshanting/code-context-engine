# Code Context Engine

> 超越 Augment ACE 的智能代码库上下文引擎

## 🚀 特性

- **🔍 智能检索** - 自然语言搜索代码，支持多种检索策略
- **🕸️ 知识图谱** - 构建完整的代码依赖和调用关系图
- **🔗 调用链分析** - 追踪函数调用链，理解代码流程
- **🧠 推理引擎** - 智能选择最佳上下文
- **⚡ 实时更新** - 文件保存自动增量索引
- **🔌 MCP 协议** - 无缝集成 Cursor、Claude Code 等 AI IDE
- **🌐 多协议支持** - MCP + REST API

## 📊 架构

```
┌────────────────────────────────────────────────────────────────┐
│                    Code Context Engine                          │
├────────────────────────────────────────────────────────────────┤
│  📥 输入层         文件监听器、全量/增量索引、Git 集成              │
├────────────────────────────────────────────────────────────────┤
│  🔍 解析层         AST 解析、依赖分析、调用链追踪、数据流分析         │
├────────────────────────────────────────────────────────────────┤
│  🕸️ 知识图谱       Neo4j 图数据库存储实体和关系                      │
├────────────────────────────────────────────────────────────────┤
│  📦 向量存储       Qdrant 存储语义向量，支持高效检索                  │
├────────────────────────────────────────────────────────────────┤
│  🧠 推理引擎       多跳检索、上下文排序、重排序模型                   │
├────────────────────────────────────────────────────────────────┤
│  🔌 输出层         MCP Server、REST API、Web UI                   │
└────────────────────────────────────────────────────────────────┘
```

## 🛠️ 安装

### 环境要求

- Python 3.9+
- Docker（运行 Qdrant 和 Neo4j）
- 文本向量 API（OpenAI/Azure/本地）

### 1. 启动依赖服务

```bash
# Qdrant（向量数据库）
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant

# Neo4j（图数据库）
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/codecontext123 \
  neo4j:latest
```

### 2. 安装 Python 依赖

```bash
git clone <repo>
cd code-context-engine

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置

编辑 `config/settings.json`：

```json
{
  "vector": {
    "api_url": "http://localhost:8000/v1/embeddings",
    "model": "text-embedding-3-small"
  },
  "neo4j": {
    "uri": "bolt://localhost:7687",
    "user": "neo4j",
    "password": "codecontext123"
  },
  "codebase": {
    "paths": ["/path/to/your/code"]
  }
}
```

### 4. 启动

```bash
# 方式1: 启动 MCP Server（推荐）
python mcp_server.py

# 方式2: 启动 REST API
python main.py
```

服务启动后：
- **MCP Endpoint:** `POST http://localhost:8080/mcp`
- **API 文档:** `http://localhost:8080/docs`

## 🔌 MCP 工具

| 工具 | 描述 |
|------|------|
| `search_code` | 自然语言搜索代码 |
| `index_codebase` | 索引代码库 |
| `get_file_context` | 获取文件上下文 |
| `find_related_code` | 查找相关代码 |
| `get_call_hierarchy` | 获取调用层次 |
| `explain_query` | 解释搜索结果 |
| `build_context` | 为 AI 构建上下文 |
| `get_dependency_graph` | 获取依赖图 |

## 🖥️ IDE 集成

### Cursor

```json
{
  "mcpServers": {
    "code-context": {
      "command": "python",
      "args": ["/path/to/code-context-engine/mcp_server.py"]
    }
  }
}
```

### Claude Code

```json
{
  "mcpServers": {
    "code-context": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

## 📖 API 示例

### 搜索代码

```bash
curl -X POST "http://localhost:8080/api/v1/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "用户认证相关的代码",
    "limit": 10,
    "language": "python"
  }'
```

### 构建 AI 上下文

```bash
curl -X POST "http://localhost:8080/api/v1/context" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "分析用户模块的整体架构",
    "max_tokens": 8000
  }'
```

## 🏗️ 项目结构

```
code-context-engine/
├── config/
│   ├── __init__.py          # 配置加载
│   └── settings.json        # 配置文件
├── core/
│   ├── parser/
│   │   └── code_parser.py   # AST 解析
│   ├── graph/
│   │   └── knowledge_graph.py  # Neo4j 图谱
│   ├── indexer/
│   │   └── indexer.py       # 索引器
│   ├── retriever/
│   │   └── retriever.py     # 检索引擎
│   ├── reasoning/
│   │   └── reasoning.py     # 推理引擎
│   └── watcher.py           # 文件监听
├── mcp_server.py            # MCP Server（推荐入口）
├── main.py                  # REST API 入口
├── requirements.txt         # Python 依赖
└── README.md               # 本文档
```

## 🎯 超越 Augment ACE

| 能力 | Augment ACE | Code Context Engine |
|------|-------------|---------------------|
| 向量检索 | ✅ | ✅ |
| 依赖图谱 | ✅ | ✅ Neo4j |
| 调用链分析 | ✅ | ✅ 完整追溯 |
| 实时索引 | ✅ | ✅ 文件监听 |
| 智能上下文 | ✅ | ✅ 推理引擎 |
| MCP 协议 | ❌ | ✅ 原生支持 |
| 重排序模型 | ❌ | ✅ 可配置 |
| 开源 | ❌ | ✅ MIT |

## 📝 License

MIT
