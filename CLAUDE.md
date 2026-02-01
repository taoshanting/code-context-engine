# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Code Context Engine - An intelligent code context retrieval system that provides semantic code search, knowledge graph building, and call chain analysis for AI coding assistants. Similar to Augment ACE but open-source.

**Primary Entry Point**: `mcp_server.py` (MCP protocol server)
**Secondary Entry Point**: `main.py` (REST API)

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start MCP Server (recommended - serves both MCP + REST API)
python mcp_server.py

# Start REST API only
python main.py
```

## External Services Required

This project requires Docker services to be running:
- **Qdrant** (vector database): `docker run -d --name qdrant -p 6333:6333 qdrant/qdrant`
- **Neo4j** (graph database): `docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/codecontext123 neo4j:latest`

## Architecture

```
Input Layer     → File watcher, full/incremental indexing, Git integration
Parsing Layer   → AST parsing (tree-sitter), dependency analysis, call chain tracing
Knowledge Graph → Neo4j for entity and relationship storage
Vector Store    → Qdrant for semantic embeddings
Reasoning Engine → Multi-hop retrieval, context ranking, reranking
Output Layer    → MCP Server, REST API
```

### Core Modules (core/)

| Module | Purpose |
|--------|---------|
| `parser/code_parser.py` | AST parsing using tree-sitter for 12+ languages |
| `graph/knowledge_graph.py` | Neo4j operations for code dependencies |
| `indexer/indexer.py` | Indexing pipeline (embeddings + graph building) |
| `retriever/retriever.py` | Multi-strategy retrieval with reranking |
| `reasoning/reasoning.py` | AI context building engine |
| `watcher.py` | Real-time file change detection (watchdog) |
| `vector_store.py` | Qdrant vector storage operations |

## Configuration

**Config File**: `config/settings.json`

Key configuration sections:
- `vector`: Text embedding API URL and model name
- `neo4j`: Neo4j connection URI, user, password
- `codebase`: Code paths to index
- `indexer`, `watcher`, `reranker`, `server`: Runtime options

Configuration loading is in `config/__init__.py` using Python dataclasses.

## MCP Tools Available

| Tool | Description |
|------|-------------|
| `search_code` | Natural language code search |
| `index_codebase` | Index codebase |
| `get_file_context` | Get file entities + dependencies |
| `find_related_code` | Find related via call chain |
| `get_call_hierarchy` | Call chain analysis |
| `explain_query` | Explain search results |
| `build_context` | Build AI context |
| `get_dependency_graph` | Get dependency graph |

## Technology Stack

- **Language**: Python 3.9+
- **Web Framework**: FastAPI + Uvicorn
- **Vector Database**: Qdrant
- **Graph Database**: Neo4j
- **Code Parsing**: tree-sitter (AST)
- **HTTP Client**: httpx (async)
