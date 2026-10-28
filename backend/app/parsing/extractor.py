import logging
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Try to initialize tree-sitter languages
_TREE_SITTER_AVAILABLE = True
_JS_PARSER = None
_TS_PARSER = None
_PY_PARSER = None

def get_js_parser():
    global _JS_PARSER
    if _JS_PARSER is None:
        import tree_sitter
        import tree_sitter_javascript
        lang = tree_sitter.Language(tree_sitter_javascript.language())
        _JS_PARSER = tree_sitter.Parser(lang)
    return _JS_PARSER

def get_ts_parser():
    global _TS_PARSER
    if _TS_PARSER is None:
        import tree_sitter
        import tree_sitter_typescript
        lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
        _TS_PARSER = tree_sitter.Parser(lang)
    return _TS_PARSER

def get_py_parser():
    global _PY_PARSER
    if _PY_PARSER is None:
        import tree_sitter
        import tree_sitter_python
        lang = tree_sitter.Language(tree_sitter_python.language())
        _PY_PARSER = tree_sitter.Parser(lang)
    return _PY_PARSER


@dataclass
class ExtractedSymbol:
    name: str
    kind: str  # function, class, method, import
    signature: Optional[str]
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    docstring: Optional[str] = None


@dataclass
class ExtractedCall:
    caller_name: str
    callee_name: str
    line_number: int
    evidence: str
    receiver: Optional[str] = None


class CodeExtractor:
    """
    Language parser and symbol extractor using Tree-sitter with AST fallback.
    Extracts functions, classes, methods, imports, and source coordinates.
    """

    @classmethod
    def extract_symbols(cls, content: bytes, file_path: str, language: Optional[str] = None) -> List[ExtractedSymbol]:
        if not content:
            return []

        lang = (language or cls.detect_language(file_path)).lower()
        symbols: List[ExtractedSymbol] = []

        if lang == "python":
            symbols = cls._extract_python_builtin_ast(content)
        elif lang in ("javascript", "jsx", "typescript", "tsx"):
            symbols = cls._extract_js_ts_symbols(content)
        else:
            symbols = cls._extract_generic_symbols(content, lang)

        for s in symbols:
            if s.name:
                s.name = s.name.replace("\x00", "")
            if s.signature:
                s.signature = s.signature.replace("\x00", "")
            if s.docstring:
                s.docstring = s.docstring.replace("\x00", "")
        return symbols

    @staticmethod
    def detect_language(file_path: str) -> str:
        fp = file_path.lower()
        if fp.endswith(".py"):
            return "python"
        elif fp.endswith(".js") or fp.endswith(".mjs") or fp.endswith(".cjs"):
            return "javascript"
        elif fp.endswith(".ts"):
            return "typescript"
        elif fp.endswith(".tsx"):
            return "tsx"
        elif fp.endswith(".jsx"):
            return "jsx"
        elif fp.endswith(".go"):
            return "go"
        elif fp.endswith(".rs"):
            return "rust"
        elif fp.endswith(".java"):
            return "java"
        elif fp.endswith(".dart"):
            return "dart"
        elif fp.endswith(".kt") or fp.endswith(".kts"):
            return "kotlin"
        elif fp.endswith(".swift"):
            return "swift"
        elif fp.endswith(".cs"):
            return "csharp"
        elif fp.endswith(".rb"):
            return "ruby"
        elif fp.endswith(".php"):
            return "php"
        elif fp.endswith(".c") or fp.endswith(".h"):
            return "c"
        elif fp.endswith(".cpp") or fp.endswith(".hpp") or fp.endswith(".cc"):
            return "cpp"
        elif fp.endswith(".html") or fp.endswith(".htm"):
            return "html"
        elif fp.endswith(".css") or fp.endswith(".scss") or fp.endswith(".sass") or fp.endswith(".less"):
            return "css"
        elif fp.endswith(".json"):
            return "json"
        elif fp.endswith(".sql"):
            return "sql"
        elif fp.endswith(".yaml") or fp.endswith(".yml"):
            return "yaml"
        elif fp.endswith(".toml"):
            return "toml"
        return "text"

    @staticmethod
    def _extract_docstring(body_node, content: bytes) -> Optional[str]:
        if not body_node:
            return None
        for child in body_node.children:
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        raw = content[sub.start_byte:sub.end_byte].decode("utf-8", "ignore")
                        for q in ('"""', "'''", '"', "'"):
                            if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
                                return raw[len(q):-len(q)].strip()
                        return raw.strip()
            if not child.type.startswith("comment"):
                break
        return None

    @classmethod
    def _extract_python_tree_sitter(cls, content: bytes) -> List[ExtractedSymbol]:
        try:
            parser = get_py_parser()
            parser.reset()
            tree = parser.parse(content)
        except Exception as e:
            logger.debug(f"Tree-sitter Python parse failed: {e}")
            return []
        symbols: List[ExtractedSymbol] = []
        stack = [(tree.root_node, None)]

        while stack:
            node, parent_class = stack.pop()
            ntype = node.type
            new_parent = parent_class

            if ntype == "class_definition":
                name_node = node.child_by_field_name("name")
                name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "unknown"
                if not name:
                    name = "unknown"
                new_parent = name
                body_node = node.child_by_field_name("body")
                doc = cls._extract_docstring(body_node, content)
                symbols.append(ExtractedSymbol(
                    name=name,
                    kind="class",
                    signature=f"class {name}",
                    start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                    end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                    start_column=max(0, min(2147483647, int(node.start_point.column))),
                    end_column=max(0, min(2147483647, int(node.end_point.column))),
                    docstring=doc,
                ))
            elif ntype == "function_definition":
                name_node = node.child_by_field_name("name")
                name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "unknown"
                if not name:
                    name = "unknown"
                kind = "method" if parent_class else "function"
                params_node = node.child_by_field_name("parameters")
                sig = content[params_node.start_byte:params_node.end_byte].decode("utf-8", "ignore") if params_node else "()"
                body_node = node.child_by_field_name("body")
                doc = cls._extract_docstring(body_node, content)
                symbols.append(ExtractedSymbol(
                    name=f"{parent_class}.{name}" if parent_class else name,
                    kind=kind,
                    signature=f"def {name}{sig}",
                    start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                    end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                    start_column=max(0, min(2147483647, int(node.start_point.column))),
                    end_column=max(0, min(2147483647, int(node.end_point.column))),
                    docstring=doc,
                ))
            elif ntype in ("import_statement", "import_from_statement"):
                text = content[node.start_byte:node.end_byte].decode("utf-8", "ignore").strip()
                symbols.append(ExtractedSymbol(
                    name=text or "import",
                    kind="import",
                    signature=text or "import",
                    start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                    end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                    start_column=max(0, min(2147483647, int(node.start_point.column))),
                    end_column=max(0, min(2147483647, int(node.end_point.column))),
                ))

            if ntype in ("module", "class_definition"):
                for child in reversed(node.children):
                    stack.append((child, new_parent))

        try:
            del stack
            del tree
            import gc
            gc.collect()
        except Exception:
            pass

        return symbols

    @classmethod
    def _extract_js_tree_sitter(cls, content: bytes, parser: Any) -> List[ExtractedSymbol]:
        try:
            parser.reset()
            tree = parser.parse(content)
        except Exception as e:
            logger.debug(f"Tree-sitter parse failed: {e}")
            return []

        symbols: List[ExtractedSymbol] = []
        stack = [(tree.root_node, None)]
        allow_recurse = {
            "program",
            "export_statement",
            "export_default_declaration",
            "class_declaration",
            "class_body",
            "interface_declaration",
            "enum_declaration",
            "internal_module",
            "module",
        }

        while stack:
            node, parent_class = stack.pop()
            try:
                ntype = node.type
            except Exception:
                continue

            new_parent = parent_class

            try:
                if ntype == "class_declaration":
                    name_node = node.child_by_field_name("name")
                    name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "unknown"
                    if not name:
                        name = "unknown"
                    new_parent = name
                    symbols.append(ExtractedSymbol(
                        name=name,
                        kind="class",
                        signature=f"class {name}",
                        start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                        end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                        start_column=max(0, min(2147483647, int(node.start_point.column))),
                        end_column=max(0, min(2147483647, int(node.end_point.column))),
                    ))
                elif ntype in ("function_declaration", "method_definition"):
                    name_node = node.child_by_field_name("name")
                    name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "anonymous"
                    if not name:
                        name = "anonymous"
                    kind = "method" if (parent_class or ntype == "method_definition") else "function"
                    params = node.child_by_field_name("parameters")
                    sig = content[params.start_byte:params.end_byte].decode("utf-8", "ignore") if params else "()"
                    symbols.append(ExtractedSymbol(
                        name=f"{parent_class}.{name}" if parent_class else name,
                        kind=kind,
                        signature=f"{name}{sig}",
                        start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                        end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                        start_column=max(0, min(2147483647, int(node.start_point.column))),
                        end_column=max(0, min(2147483647, int(node.end_point.column))),
                    ))
                elif ntype in ("import_statement", "import_declaration"):
                    text = content[node.start_byte:node.end_byte].decode("utf-8", "ignore").strip()
                    symbols.append(ExtractedSymbol(
                        name=text or "import",
                        kind="import",
                        signature=text or "import",
                        start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                        end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                        start_column=max(0, min(2147483647, int(node.start_point.column))),
                        end_column=max(0, min(2147483647, int(node.end_point.column))),
                    ))
                elif ntype in ("lexical_declaration", "variable_declaration"):
                    for child in node.children:
                        if child.type == "variable_declarator":
                            val = child.child_by_field_name("value")
                            if val and val.type in ("arrow_function", "function_expression"):
                                name_node = child.child_by_field_name("name")
                                name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "anonymous"
                                if not name:
                                    name = "anonymous"
                                params = val.child_by_field_name("parameters")
                                sig = content[params.start_byte:params.end_byte].decode("utf-8", "ignore") if params else "()"
                                symbols.append(ExtractedSymbol(
                                    name=f"{parent_class}.{name}" if parent_class else name,
                                    kind="function",
                                    signature=f"{name}{sig}",
                                    start_line=max(1, min(2147483647, int(child.start_point.row + 1))),
                                    end_line=max(1, min(2147483647, int(child.end_point.row + 1))),
                                    start_column=max(0, min(2147483647, int(child.start_point.column))),
                                    end_column=max(0, min(2147483647, int(child.end_point.column))),
                                ))
                elif ntype in ("interface_declaration", "type_alias_declaration", "enum_declaration"):
                    name_node = node.child_by_field_name("name")
                    name = content[name_node.start_byte:name_node.end_byte].decode("utf-8", "ignore").strip() if name_node else "unknown"
                    if not name:
                        name = "unknown"
                    kind = "class" if ntype == "enum_declaration" else "type"
                    symbols.append(ExtractedSymbol(
                        name=name,
                        kind=kind,
                        signature=f"{ntype.replace('_declaration', '')} {name}",
                        start_line=max(1, min(2147483647, int(node.start_point.row + 1))),
                        end_line=max(1, min(2147483647, int(node.end_point.row + 1))),
                        start_column=max(0, min(2147483647, int(node.start_point.column))),
                        end_column=max(0, min(2147483647, int(node.end_point.column))),
                    ))
            except Exception as e:
                logger.debug(f"Error extracting symbol for node {ntype}: {e}")

            if ntype in allow_recurse:
                try:
                    for child in reversed(node.children):
                        stack.append((child, new_parent))
                except Exception:
                    pass

        try:
            del stack
            del tree
            import gc
            gc.collect()
        except Exception:
            pass

        return symbols

    @classmethod
    def _extract_js_ts_symbols(cls, content: bytes) -> List[ExtractedSymbol]:
        import re
        text = content.decode("utf-8", "ignore")
        lines = text.splitlines()
        symbols: List[ExtractedSymbol] = []

        re_class = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z0-9_$]+)")
        re_func = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*([A-Za-z0-9_$]+)?\s*(\([^\)]*\))")
        re_arrow = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?(\([^\)]*\)|[A-Za-z0-9_$]+)\s*=>")
        re_var_fn = re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?function\s*(?:[A-Za-z0-9_$]+)?\s*(\([^\)]*\))")
        re_method = re.compile(r"^\s*(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?([A-Za-z0-9_$]+)\s*(\([^\)]*\))\s*\{")
        re_import = re.compile(r"^\s*(?:import\s+.+?from\s+['\"][^'\"]+['\"]|import\s+['\"][^'\"]+['\"]|const\s+.+?=\s*require\([^\)]+\))")
        re_interface = re.compile(r"^\s*(?:export\s+)?interface\s+([A-Za-z0-9_$]+)")
        re_type = re.compile(r"^\s*(?:export\s+)?type\s+([A-Za-z0-9_$]+)\s*=")
        re_enum = re.compile(r"^\s*(?:export\s+)?enum\s+([A-Za-z0-9_$]+)")

        current_class = None
        class_brace_depth = 0
        total_brace_depth = 0

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if not s or s.startswith("//") or s.startswith("/*") or s.startswith("*"):
                continue

            # Imports
            m_imp = re_import.match(line)
            if m_imp:
                imp_text = m_imp.group(0).strip()
                symbols.append(ExtractedSymbol(
                    name=imp_text,
                    kind="import",
                    signature=imp_text,
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(imp_text) if imp_text in line else 0,
                    end_column=len(line)
                ))
                continue

            # Classes
            m_cls = re_class.match(line)
            if m_cls:
                cname = m_cls.group(1)
                current_class = cname
                class_brace_depth = total_brace_depth
                symbols.append(ExtractedSymbol(
                    name=cname,
                    kind="class",
                    signature=f"class {cname}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(cname) if cname in line else 0,
                    end_column=len(line)
                ))
                total_brace_depth += line.count("{") - line.count("}")
                continue

            # TypeScript interfaces & types & enums
            m_iface = re_interface.match(line)
            if m_iface:
                iname = m_iface.group(1)
                symbols.append(ExtractedSymbol(
                    name=iname,
                    kind="type",
                    signature=f"interface {iname}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(iname) if iname in line else 0,
                    end_column=len(line)
                ))
                total_brace_depth += line.count("{") - line.count("}")
                continue

            m_type = re_type.match(line)
            if m_type:
                tname = m_type.group(1)
                symbols.append(ExtractedSymbol(
                    name=tname,
                    kind="type",
                    signature=f"type {tname}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(tname) if tname in line else 0,
                    end_column=len(line)
                ))
                continue

            m_enum = re_enum.match(line)
            if m_enum:
                ename = m_enum.group(1)
                symbols.append(ExtractedSymbol(
                    name=ename,
                    kind="class",
                    signature=f"enum {ename}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(ename) if ename in line else 0,
                    end_column=len(line)
                ))
                total_brace_depth += line.count("{") - line.count("}")
                continue

            # Methods inside classes
            if current_class and (total_brace_depth > class_brace_depth):
                m_meth = re_method.match(line)
                if m_meth and m_meth.group(1) not in ("if", "for", "while", "switch", "catch", "return"):
                    mname = m_meth.group(1)
                    sig = f"{mname}{m_meth.group(2)}"
                    symbols.append(ExtractedSymbol(
                        name=f"{current_class}.{mname}",
                        kind="method",
                        signature=sig,
                        start_line=idx,
                        end_line=idx,
                        start_column=line.find(mname) if mname in line else 0,
                        end_column=len(line)
                    ))

            # Standard function declarations
            m_fn = re_func.match(line)
            if m_fn:
                fname = m_fn.group(1) or "anonymous"
                params = m_fn.group(2) or "()"
                symbols.append(ExtractedSymbol(
                    name=fname,
                    kind="function",
                    signature=f"function {fname}{params}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(fname) if fname in line else 0,
                    end_column=len(line)
                ))

            # Arrow functions (const foo = () => ...)
            m_arr = re_arrow.match(line)
            if m_arr:
                aname = m_arr.group(1)
                aparams = m_arr.group(2) if m_arr.lastindex and m_arr.lastindex >= 2 else "()"
                symbols.append(ExtractedSymbol(
                    name=aname,
                    kind="function",
                    signature=f"{aname} = {aparams} =>",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(aname) if aname in line else 0,
                    end_column=len(line)
                ))

            # Var functions (const foo = function(...) ...)
            m_vfn = re_var_fn.match(line)
            if m_vfn:
                vname = m_vfn.group(1)
                vparams = m_vfn.group(2) or "()"
                symbols.append(ExtractedSymbol(
                    name=vname,
                    kind="function",
                    signature=f"{vname} = function{vparams}",
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(vname) if vname in line else 0,
                    end_column=len(line)
                ))

            total_brace_depth += line.count("{") - line.count("}")
            if current_class and total_brace_depth <= class_brace_depth:
                current_class = None

        return symbols

    @classmethod
    def _extract_python_builtin_ast(cls, content: bytes) -> List[ExtractedSymbol]:
        import ast
        symbols: List[ExtractedSymbol] = []
        try:
            tree = ast.parse(content.decode("utf-8", "ignore"))
        except Exception:
            return cls._extract_generic_symbols(content, "python")

        class PySymbolVisitor(ast.NodeVisitor):
            def __init__(self):
                self.symbols: List[ExtractedSymbol] = []
                self.class_stack: List[str] = []

            def visit_ClassDef(self, node):
                doc = ast.get_docstring(node)
                self.symbols.append(ExtractedSymbol(
                    name=node.name,
                    kind="class",
                    signature=f"class {node.name}",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    start_column=node.col_offset,
                    end_column=getattr(node, "end_col_offset", 0),
                    docstring=doc
                ))
                self.class_stack.append(node.name)
                self.generic_visit(node)
                self.class_stack.pop()

            def visit_FunctionDef(self, node):
                self._record_func(node)

            def visit_AsyncFunctionDef(self, node):
                self._record_func(node)

            def _record_func(self, node):
                parent_class = self.class_stack[-1] if self.class_stack else None
                name = f"{parent_class}.{node.name}" if parent_class else node.name
                kind = "method" if parent_class else "function"
                doc = ast.get_docstring(node)
                # Build parameter signature
                param_names = [a.arg for a in getattr(node.args, "args", [])]
                sig = f"def {node.name}({', '.join(param_names)})"
                self.symbols.append(ExtractedSymbol(
                    name=name,
                    kind=kind,
                    signature=sig,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    start_column=node.col_offset,
                    end_column=getattr(node, "end_col_offset", 0),
                    docstring=doc
                ))
                self.generic_visit(node)

            def visit_Import(self, node):
                names = [alias.name for alias in node.names]
                self.symbols.append(ExtractedSymbol(
                    name=", ".join(names),
                    kind="import",
                    signature=f"import {', '.join(names)}",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    start_column=node.col_offset,
                    end_column=getattr(node, "end_col_offset", 0),
                ))

            def visit_ImportFrom(self, node):
                mod = node.module or ""
                names = [alias.name for alias in node.names]
                self.symbols.append(ExtractedSymbol(
                    name=f"from {mod} import {', '.join(names)}",
                    kind="import",
                    signature=f"from {mod} import {', '.join(names)}",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    start_column=node.col_offset,
                    end_column=getattr(node, "end_col_offset", 0),
                ))

        visitor = PySymbolVisitor()
        visitor.visit(tree)
        return visitor.symbols

    @classmethod
    def _extract_generic_symbols(cls, content: bytes, language: str) -> List[ExtractedSymbol]:
        import re
        symbols: List[ExtractedSymbol] = []
        lines = content.decode("utf-8", "ignore").splitlines()

        re_class = re.compile(r'^(?:(?:export|public|private|protected|abstract|sealed|final)\s+)*(?:class|interface|struct|enum|trait)\s+([A-Za-z0-9_]+)')
        re_go_struct = re.compile(r'^type\s+([A-Za-z0-9_]+)\s+struct\b')
        re_func = re.compile(
            r'^(?:(?:export|public|private|protected|static|async|override|virtual|final|pub|pub\(crate\))\s+)*'
            r'(?:def|function|fn|fun|func)\s+'
            r'(?:\([A-Za-z0-9_ *&,.\-]+\)\s+)?'  # Go receiver like (r *Repo)
            r'([A-Za-z0-9_]+)\s*\('
        )
        # Typed method signatures like in Java, C#, Dart (e.g. Widget build(BuildContext context), void main())
        re_typed_method = re.compile(
            r'^(?:(?:public|private|protected|static|final|override|async)\s+)+'
            r'(?:[A-Za-z0-9_<>[\]?, ]+)\s+([A-Za-z0-9_]+)\s*\([^{;]*\)\s*(?:\{|=>|throws)'
        )
        re_dart_method = re.compile(
            r'^(?:Widget|void|Future<[^>]*>|Stream<[^>]*>|String|int|double|bool)\s+([A-Za-z0-9_]+)\s*\([^{;]*\)\s*(?:\{|=>)'
        )

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if not s or s.startswith("//") or s.startswith("#") or s.startswith("/*"):
                continue

            # 1. Classes, Structs, Interfaces
            m_cls = re_class.match(s) or re_go_struct.match(s)
            if m_cls:
                name = m_cls.group(1)
                symbols.append(ExtractedSymbol(
                    name=name,
                    kind="class",
                    signature=s[:100],
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(name) if name in line else 0,
                    end_column=len(line)
                ))
                continue

            # 2. Functions & Methods with keywords
            m_fn = re_func.match(s)
            if m_fn:
                name = m_fn.group(1)
                symbols.append(ExtractedSymbol(
                    name=name,
                    kind="function",
                    signature=s[:100],
                    start_line=idx,
                    end_line=idx,
                    start_column=line.find(name) if name in line else 0,
                    end_column=len(line)
                ))
                continue

            # 3. Typed methods (Java, C#, Dart, etc.)
            m_tm = re_typed_method.match(s) or re_dart_method.match(s)
            if m_tm:
                name = m_tm.group(1)
                if name not in ("if", "for", "while", "switch", "catch"):
                    symbols.append(ExtractedSymbol(
                        name=name,
                        kind="function",
                        signature=s[:100],
                        start_line=idx,
                        end_line=idx,
                        start_column=line.find(name) if name in line else 0,
                        end_column=len(line)
                    ))
                    continue

            # 4. Imports & packages
            if s.startswith("import ") or s.startswith("from ") or s.startswith("package ") or s.startswith("use ") or s.startswith("using ") or s.startswith("require("):
                symbols.append(ExtractedSymbol(
                    name=s[:80],
                    kind="import",
                    signature=s[:80],
                    start_line=idx,
                    end_line=idx,
                    start_column=0,
                    end_column=len(line)
                ))

        return symbols

    @classmethod
    def extract_static_calls(cls, content: bytes, file_path: str, language: Optional[str] = None) -> List[ExtractedCall]:
        """
        Extracts verified static call expressions between functions and methods.
        Never infers a CALLS edge solely from name similarity.
        """
        if not content:
            return []

        lang = (language or cls.detect_language(file_path)).lower()
        calls: List[ExtractedCall] = []

        if lang == "python":
            import ast
            try:
                raw_code = content.decode("utf-8", "ignore")
                # Normalize any // headers from chunk texts to # comments so Python AST parse succeeds
                norm_lines = [
                    ("# " + l.strip()[2:]) if l.strip().startswith("//") else l
                    for l in raw_code.splitlines()
                ]
                tree = ast.parse("\n".join(norm_lines))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, getattr(ast, "AsyncFunctionDef", ()))):
                        caller = node.name
                        for child in ast.walk(node):
                            if isinstance(child, ast.Call) and child is not node:
                                callee = None
                                receiver = None
                                if isinstance(child.func, ast.Name):
                                    callee = child.func.id
                                elif isinstance(child.func, ast.Attribute):
                                    callee = child.func.attr
                                    if isinstance(child.func.value, ast.Name):
                                        receiver = child.func.value.id
                                    elif isinstance(child.func.value, ast.Attribute):
                                        receiver = child.func.value.attr
                                if callee:
                                    calls.append(ExtractedCall(
                                        caller_name=caller,
                                        callee_name=callee,
                                        line_number=getattr(child, "lineno", node.lineno),
                                        evidence=f"Call to {callee}() inside def {caller} at line {getattr(child, 'lineno', node.lineno)}",
                                        receiver=receiver,
                                    ))
                for c in calls:
                    if c.caller_name:
                        c.caller_name = c.caller_name.replace("\x00", "")
                    if c.callee_name:
                        c.callee_name = c.callee_name.replace("\x00", "")
                    if c.evidence:
                        c.evidence = c.evidence.replace("\x00", "")
                return calls
            except Exception:
                pass

        # Tree-sitter or regex fallback for JS/TS/other
        import re
        call_pattern = re.compile(r"(?:([a-zA-Z_][a-zA-Z0-9_]*)\.)?([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
        lines = content.decode("utf-8", "ignore").splitlines()
        current_func = None
        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if s.startswith("def ") or s.startswith("function ") or s.startswith("async function "):
                parts = s.split("(")
                current_func = parts[0].split()[-1]
            elif current_func:
                matches = call_pattern.findall(s)
                for receiver, callee in matches:
                    if callee not in ("if", "for", "while", "switch", "catch", "return", "require"):
                        calls.append(ExtractedCall(
                            caller_name=current_func,
                            callee_name=callee,
                            line_number=idx,
                            receiver=receiver if receiver else None,
                            evidence=f"Call to {callee}() in {current_func} at line {idx}: {s[:60]}"
                        ))

        for c in calls:
            if c.caller_name:
                c.caller_name = c.caller_name.replace("\x00", "")
            if c.callee_name:
                c.callee_name = c.callee_name.replace("\x00", "")
            if c.evidence:
                c.evidence = c.evidence.replace("\x00", "")
        return calls
