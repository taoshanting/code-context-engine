"""
知识图谱存储 - Neo4j 图数据库
"""

from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass
from neo4j import GraphDatabase
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """图节点"""
    id: str
    labels: List[str]
    properties: Dict


@dataclass
class GraphRelationship:
    """图关系"""
    start_node: str
    end_node: str
    relation_type: str
    properties: Dict


class KnowledgeGraph:
    """知识图谱"""
    
    def __init__(self, config):
        self.config = config.neo4j
        self.driver = GraphDatabase.driver(
            self.config.uri,
            auth=(self.config.user, self.config.password)
        )
        self._init_schema()
    
    def _init_schema(self):
        """初始化图谱 schema"""
        with self.driver.session() as session:
            # 创建约束
            session.run("""
                CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) 
                REQUIRE e.id IS UNIQUE
            """)
            session.run("""
                CREATE CONSTRAINT IF NOT EXISTS FOR (f:File) 
                REQUIRE f.path IS UNIQUE
            """)
    
    def close(self):
        """关闭连接"""
        self.driver.close()
    
    # ============ 节点操作 ============
    
    def upsert_file(self, file_path: str, **properties):
        """创建/更新文件节点"""
        with self.driver.session() as session:
            session.run("""
                MERGE (f:File {path: $path})
                SET f += $props,
                    f.updated_at = datetime()
                RETURN f
            """, path=file_path, props=properties)
    
    def upsert_entity(self, entity_id: str, entity_type: str, **properties):
        """创建/更新实体节点"""
        with self.driver.session() as session:
            session.run("""
                MERGE (e:Entity {id: $id})
                SET e.type = $type,
                    e += $props,
                    e.updated_at = datetime()
                RETURN e
            """, id=entity_id, type=entity_type, props=properties)
    
    def delete_entity(self, entity_id: str):
        """删除实体"""
        with self.driver.session() as session:
            session.run("""
                MATCH (e:Entity {id: $id})
                DETACH DELETE e
            """, id=entity_id)
    
    # ============ 关系操作 ============
    
    def create_calls_relation(self, caller_id: str, callee_id: str, line: int = 0):
        """创建调用关系"""
        with self.driver.session() as session:
            session.run("""
                MATCH (caller:Entity {id: $caller_id})
                MATCH (callee:Entity {id: $callee_id})
                MERGE (caller)-[r:CALLS {
                    line: $line,
                    created_at: datetime()
                }]->(callee)
                RETURN r
            """, caller_id=caller_id, callee_id=callee_id, line=line)
    
    def create_contains_relation(self, container_id: str, contained_id: str):
        """创建包含关系（类包含方法、模块包含函数）"""
        with self.driver.session() as session:
            session.run("""
                MATCH (container:Entity {id: $container_id})
                MATCH (contained:Entity {id: $contained_id})
                MERGE (container)-[r:CONTAINS {
                    created_at: datetime()
                }]->(contained)
                RETURN r
            """, container_id=container_id, contained_id=contained_id)
    
    def create_imports_relation(self, file_path: str, imported_entity: str, imported_file: str):
        """创建导入关系"""
        with self.driver.session() as session:
            session.run("""
                MATCH (file:File {path: $file_path})
                MATCH (entity:Entity {id: $entity_id})
                MERGE (file)-[r:IMPORTS {
                    target_file: $target_file,
                    created_at: datetime()
                }]->(entity)
                RETURN r
            """, file_path=file_path, entity_id=imported_entity, target_file=imported_file)
    
    def create_defines_relation(self, file_path: str, entity_id: str):
        """创建文件定义实体的关系"""
        with self.driver.session() as session:
            session.run("""
                MATCH (file:File {path: $file_path})
                MATCH (entity:Entity {id: $entity_id})
                MERGE (file)-[r:DEFINES {
                    created_at: datetime()
                }]->(entity)
                RETURN r
            """, file_path=file_path, entity_id=entity_id)
    
    # ============ 查询操作 ============
    
    def get_entity(self, entity_id: str) -> Optional[Dict]:
        """获取实体信息"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity {id: $id})
                RETURN e
            """, id=entity_id)
            record = result.single()
            return dict(record["e"]) if record else None
    
    def get_callers(self, entity_id: str, depth: int = 1) -> List[Dict]:
        """获取调用该实体的实体（向上追溯）"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (caller:Entity)-[:CALLS*1..$depth]->(target:Entity {id: $id})
                UNWIND nodes(path) AS node
                RETURN DISTINCT node.id AS id, node.name AS name, node.type AS type
                LIMIT 50
            """, id=entity_id, depth=depth)
            return [dict(record) for record in result]
    
    def get_callees(self, entity_id: str, depth: int = 1) -> List[Dict]:
        """获取该实体调用的实体（向下追溯）"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (target:Entity {id: $id})-[:CALLS*1..$depth]->(callee:Entity)
                UNWIND nodes(path) AS node
                RETURN DISTINCT node.id AS id, node.name AS name, node.type AS type
                LIMIT 50
            """, id=entity_id, depth=depth)
            return [dict(record) for record in result]
    
    def get_call_chain(self, source_id: str, target_id: str) -> List[str]:
        """获取两个实体之间的调用链"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (source:Entity {id: $source_id})-[:CALLS*]->(target:Entity {id: $target_id})
                RETURN [node IN nodes(path) | node.id] AS path
                LIMIT 1
            """, source_id=source_id, target_id=target_id)
            record = result.single()
            return record["path"] if record else []
    
    def get_related_entities(self, entity_id: str, limit: int = 20) -> List[Dict]:
        """获取相关实体（通过多种关系）"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity {id: $id})-[r:CALLS|CONTAINS|IMPORTS]-(related)
                RETURN related.id AS id, related.name AS name, related.type AS type,
                       type(r) AS relation, r.line AS line
                LIMIT $limit
            """, id=entity_id, limit=limit)
            return [dict(record) for record in result]
    
    def get_file_entities(self, file_path: str) -> List[Dict]:
        """获取文件中的所有实体"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (file:File {path: $path})-[:DEFINES]->(entity:Entity)
                RETURN entity.id AS id, entity.name AS name, entity.type AS type,
                       entity.start_line AS start_line, entity.end_line AS end_line
            """, path=file_path)
            return [dict(record) for record in result]
    
    def get_module_structure(self, root_entity_id: str, depth: int = 2) -> Dict:
        """获取模块结构树"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (root:Entity {id: $root_id})-[:CONTAINS*1..$depth]->(child)
                RETURN root, collect(child) AS children
            """, root_id=root_entity_id, depth=depth)
            record = result.single()
            if record:
                return {
                    "root": dict(record["root"]),
                    "children": [dict(c) for c in record["children"]]
                }
            return None
    
    def search_entities_by_type(self, entity_type: str, limit: int = 100) -> List[Dict]:
        """按类型搜索实体"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (e:Entity)
                WHERE e.type = $type
                RETURN e.id AS id, e.name AS name, e.file_path AS file_path
                LIMIT $limit
            """, type=entity_type, limit=limit)
            return [dict(record) for record in result]
    
    def get_dependency_graph(self, file_path: str) -> Dict:
        """获取文件的依赖图"""
        with self.driver.session() as session:
            # 获取导入
            result = session.run("""
                MATCH (file:File {path: $path})-[:IMPORTS]->(imported:Entity)
                RETURN {imported: imported.name, file: imported.file_path} AS dependency
            """, path=file_path)
            imports = [dict(r) for r in result]
            
            # 获取被导入
            result = session.run("""
                MATCH (importer:Entity)-[:CALLS]->(callee:Entity)
                WHERE importer.file_path = $path
                RETURN callee.name AS name, callee.file_path AS file_path
                LIMIT 50
            """, path=file_path)
            calls = [dict(r) for r in result]
            
            return {"imports": imports, "calls": calls}
    
    def clear_all(self):
        """清空所有数据"""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
