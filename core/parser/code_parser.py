"""
代码解析器 - AST 解析、语法分析
"""

import re
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import tree_sitter
import tree_sitter_languages


@dataclass
class CodeEntity:
    """代码实体（函数、类、变量等）"""
    name: str
    entity_type: str  # function, class, method, variable, import
    file_path: str
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    decorators: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)  # 调用的函数
    children: List[str] = field(default_factory=list)  # 子实体（类的方法）
    complexity: int = 1
    language: str = "python"
    metadata: Dict = field(default_factory=dict)


@dataclass
class Dependency:
    """依赖关系"""
    source_file: str
    target_file: str
    target_entity: str
    import_type: str  # import, from_import, require, include
    line: int


@dataclass
class CallChain:
    """调用链"""
    source_entity: str
    source_file: str
    target_entity: str
    target_file: str
    depth: int = 1
    path: List[str] = field(default_factory=list)


class LanguageParser(ABC):
    """语言解析器基类"""
    
    @abstractmethod
    def parse_file(self, file_path: Path, content: str) -> List[CodeEntity]:
        """解析文件，返回代码实体列表"""
        pass
    
    @abstractmethod
    def extract_imports(self, content: str) -> List[str]:
        """提取导入语句"""
        pass
    
    @abstractmethod
    def extract_calls(self, content: str) -> List[str]:
        """提取函数调用"""
        pass


class PythonParser(LanguageParser):
    """Python 解析器"""
    
    def __init__(self):
        self.parser = tree_sitter_languages.get_parser("python")
        self.language = "python"
        
        # 关键字
        self.keywords = {"def", "class", "import", "from", "return", "if", "else", "for", "while"}
    
    def parse_file(self, file_path: Path, content: str) -> List[CodeEntity]:
        """解析 Python 文件"""
        entities = []
        tree = self.parser.parse(bytes(content, "utf-8"))
        
        # 遍历语法树
        cursor = tree.walk()
        
        for node in self._traverse(cursor.node):
            if node.type == "function_definition":
                entity = self._parse_function(node, content, file_path)
                entities.append(entity)
            elif node.type == "class_definition":
                entity = self._parse_class(node, content, file_path)
                entities.append(entity)
        
        return entities
    
    def _traverse(self, node) -> List:
        """遍历节点"""
        nodes = [node]
        for child in node.children:
            nodes.extend(self._traverse(child))
        return nodes
    
    def _parse_function(self, node, content: str, file_path: Path) -> CodeEntity:
        """解析函数"""
        # 获取函数名
        name = ""
        params = []
        docstring = None
        
        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte:child.end_byte]
            elif child.type == "parameters":
                params = self._parse_params(child, content)
            elif child.type == "block":
                # 尝试提取 docstring
                docstring = self._parse_docstring(child, content)
        
        code = content[node.start_byte:node.end_byte]
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        # 提取调用
        calls = self.extract_calls(code)
        
        return CodeEntity(
            name=name,
            entity_type="function",
            file_path=str(file_path),
            start_line=start_line,
            end_line=end_line,
            code=code,
            docstring=docstring,
            parameters=params,
            calls=calls,
            complexity=self._calculate_complexity(code),
            language=self.language
        )
    
    def _parse_class(self, node, content: str, file_path: Path) -> CodeEntity:
        """解析类"""
        name = ""
        docstring = None
        children = []
        
        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte:child.end_byte]
            elif child.type == "block":
                docstring = self._parse_docstring(child, content)
                # 解析方法
                for grandchild in child.children:
                    if grandchild.type == "function_definition":
                        method = self._parse_function(grandchild, content, file_path)
                        children.append(method.name)
        
        code = content[node.start_byte:node.end_byte]
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        return CodeEntity(
            name=name,
            entity_type="class",
            file_path=str(file_path),
            start_line=start_line,
            end_line=end_line,
            code=code,
            docstring=docstring,
            children=children,
            complexity=self._calculate_complexity(code),
            language=self.language
        )
    
    def _parse_params(self, node, content: str) -> List[str]:
        """解析参数列表"""
        params = []
        for child in node.children:
            if child.type == "identifier":
                params.append(content[child.start_byte:child.end_byte])
        return params
    
    def _parse_docstring(self, node, content: str) -> Optional[str]:
        """解析 docstring"""
        if node.children and node.children[0].type == "string":
            text = content[node.children[0].start_byte:node.children[0].end_byte]
            # 去掉 triple quotes
            return text.strip('"""').strip("'''").strip()
        return None
    
    def _calculate_complexity(self, code: str) -> int:
        """计算圈复杂度（简化版）"""
        complexity = 1
        keywords = ["if", "elif", "for", "while", "and", "or", "except"]
        for keyword in keywords:
            complexity += code.count(keyword)
        return complexity
    
    def extract_imports(self, content: str) -> List[str]:
        """提取导入语句"""
        imports = []
        import_pattern = re.findall(r'^(?:from\s+(\S+)|import\s+(\S+))', content, re.MULTILINE)
        for imp in import_pattern:
            imports.extend([x for x in imp if x])
        return imports
    
    def extract_calls(self, content: str) -> List[str]:
        """提取函数调用"""
        calls = re.findall(r'(\w+)\s*\(', content)
        # 过滤掉关键词和内置函数
        builtins = {'print', 'len', 'str', 'int', 'float', 'list', 'dict', 'set', 'range', 'open'}
        return [c for c in calls if c not in self.keywords and c not in builtins]


class JavaScriptParser(LanguageParser):
    """JavaScript/TypeScript 解析器"""
    
    def __init__(self):
        self.parser = tree_sitter_languages.get_parser("javascript")
        self.language = "typescript" if ".ts" in str(Path) else "javascript"
        self.keywords = {"function", "const", "let", "var", "class", "return", "if", "else", "for", "while"}
    
    def parse_file(self, file_path: Path, content: str) -> List[CodeEntity]:
        """解析 JS/TS 文件"""
        entities = []
        tree = self.parser.parse(bytes(content, "utf-8"))
        
        for node in self._traverse(tree.walk().node):
            if node.type == "function_declaration":
                entity = self._parse_function(node, content, file_path)
                entities.append(entity)
            elif node.type == "class_declaration":
                entity = self._parse_class(node, content, file_path)
                entities.append(entity)
            elif node.type == "method_definition":
                entity = self._parse_method(node, content, file_path)
                entities.append(entity)
        
        return entities
    
    def _traverse(self, node) -> List:
        nodes = [node]
        for child in node.children:
            nodes.extend(self._traverse(child))
        return nodes
    
    def _parse_function(self, node, content: str, file_path: Path) -> CodeEntity:
        name = ""
        params = []
        docstring = None
        
        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte:child.end_byte]
            elif child.type == "formal_parameters":
                params = self._parse_params(child, content)
        
        code = content[node.start_byte:node.end_byte]
        calls = self.extract_calls(code)
        
        return CodeEntity(
            name=name,
            entity_type="function",
            file_path=str(file_path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            code=code,
            parameters=params,
            calls=calls,
            complexity=self._calculate_complexity(code),
            language=self.language
        )
    
    def _parse_class(self, node, content: str, file_path: Path) -> CodeEntity:
        name = ""
        children = []
        
        for child in node.children:
            if child.type == "identifier":
                name = content[child.start_byte:child.end_byte]
            elif child.type == "class_body":
                for grandchild in child.children:
                    if grandchild.type == "method_definition":
                        children.append(self._get_method_name(grandchild, content))
        
        return CodeEntity(
            name=name,
            entity_type="class",
            file_path=str(file_path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            code=content[node.start_byte:node.end_byte],
            children=children,
            language=self.language
        )
    
    def _parse_method(self, node, content: str, file_path: Path) -> CodeEntity:
        name = ""
        params = []
        
        for child in node.children:
            if child.type == "property_name":
                name = content[child.start_byte:child.end_byte]
            elif child.type == "formal_parameters":
                params = self._parse_params(child, content)
        
        return CodeEntity(
            name=name,
            entity_type="method",
            file_path=str(file_path),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            code=content[node.start_byte:node.end_byte],
            parameters=params,
            language=self.language
        )
    
    def _get_method_name(self, node, content: str) -> str:
        for child in node.children:
            if child.type == "property_name":
                return content[child.start_byte:child.end_byte]
        return ""
    
    def _parse_params(self, node, content: str) -> List[str]:
        params = []
        for child in node.children:
            if child.type == "identifier":
                params.append(content[child.start_byte:child.end_byte])
        return params
    
    def _calculate_complexity(self, code: str) -> int:
        complexity = 1
        keywords = ["if", "else if", "for", "while", "&&", "||", "?"]
        for keyword in keywords:
            complexity += code.count(keyword)
        return complexity
    
    def extract_imports(self, content: str) -> List[str]:
        imports = re.findall(r'(?:from\s+["\']([^"\']+)|import\s+(?:["\']([^"\']+))', content)
        return [x for tup in imports for x in tup if x]
    
    def extract_calls(self, content: str) -> List[str]:
        calls = re.findall(r'(\w+)\s*\(', content)
        return calls


class CodeParser:
    """代码解析器主类"""
    
    def __init__(self):
        self.parsers: Dict[str, LanguageParser] = {}
        self._init_parsers()
    
    def _init_parsers(self):
        """初始化解析器"""
        self.parsers = {
            "python": PythonParser(),
            "javascript": JavaScriptParser(),
            "typescript": JavaScriptParser(),
        }
    
    def detect_language(self, file_path: Path) -> str:
        """检测语言"""
        ext = file_path.suffix.lower()
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
        }
        return lang_map.get(ext, 'python')
    
    def parse_file(self, file_path: Path) -> List[CodeEntity]:
        """解析单个文件"""
        language = self.detect_language(file_path)
        parser = self.parsers.get(language)
        
        if not parser:
            return []
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            return parser.parse_file(file_path, content)
        except Exception as e:
            print(f"解析失败 {file_path}: {e}")
            return []
    
    def parse_directory(self, directory: Path, exclude_patterns: List[str] = None) -> List[CodeEntity]:
        """解析整个目录"""
        from fnmatch import fnmatch
        import os
        
        all_entities = []
        exclude_patterns = exclude_patterns or []
        
        for root, dirs, files in os.walk(directory):
            # 过滤目录
            dirs[:] = [d for d in dirs if not any(
                fnmatch(d, pattern.rstrip('*')) for pattern in exclude_patterns
            )]
            
            for file in files:
                file_path = Path(root) / file
                rel_path = str(file_path.relative_to(directory))
                
                if any(fnmatch(rel_path, pattern) for pattern in exclude_patterns):
                    continue
                
                entities = self.parse_file(file_path)
                all_entities.extend(entities)
        
        return all_entities
