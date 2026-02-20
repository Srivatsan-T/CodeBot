"""Consolidated parser for Python codebase analysis.

Merges file parsing, AST parsing, and dependency analysis into a single module
that outputs a comprehensive symbols_final.json file.
"""

import os
import ast
import json
from pathlib import Path
from typing import List, Dict, Set


# -------------------------
# File Discovery
# -------------------------

def traverse_codebase(repo_name: str) -> List[Path]:
    """Traverse codebase and collect all Python files."""
    files_list = []
    for root, dirs, files in os.walk(repo_name):
        for file in files:
            if file.endswith('.py'):
                files_list.append(Path(root) / file)
    return files_list


def is_test_file(file_path: Path) -> bool:
    """Check if a file is a test file."""
    path_str = str(file_path).lower()
    return (
        "\\tests\\" in path_str
        or "\\test\\" in path_str
        or file_path.name.startswith("test_")
        or file_path.name.endswith("_test.py")
        or file_path.name.startswith("tests_")
        or file_path.name.endswith("_tests.py")
    )


def get_included_files(repo_name: str) -> List[Dict]:
    """Get list of included Python files with metadata."""
    files_list = traverse_codebase(repo_name)
    included_files = []
    
    for file_path in files_list:
        if file_path.stat().st_size == 0 or is_test_file(file_path):
            continue
        
        included_files.append({
            "path": str(file_path),
            "absolute_path": str(file_path.resolve()),
            "extension": file_path.suffix,
        })
    
    return included_files


# -------------------------
# AST Parsing
# -------------------------

def build_import_map(tree: ast.AST) -> Dict[str, str]:
    """Build a map of imported names to their full module paths."""
    import_map = {}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_map[alias.asname or alias.name] = alias.name
        
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                import_map[alias.asname or alias.name] = f"{module}.{alias.name}"
    
    return import_map


def extract_used_names(node: ast.AST) -> Set[str]:
    """Extract all names used in a node."""
    names = set()
    
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            names.add(child.value.id)
    
    return names


class SymbolVisitor(ast.NodeVisitor):
    """Visitor to extract symbols from AST."""
    
    def __init__(self, file_path: str, import_map: Dict[str, str]):
        self.file_path = file_path
        self.import_map = import_map
        self.symbols = []
        self.class_stack = []
    
    @property
    def current_class(self):
        return self.class_stack[-1] if self.class_stack else None
    
    def _handle_function(self, node, is_async=False):
        parent = self.current_class
        
        symbol_type = "method" if parent else "function"
        qualified_name = (
            f"{parent['qualified_name']}.{node.name}"
            if parent
            else node.name
        )
        
        used_names = extract_used_names(node)
        used_imports = [
            self.import_map[n] for n in used_names if n in self.import_map
        ]
        
        self.symbols.append({
            "file_path": self.file_path,
            "symbol_type": symbol_type,
            "name": node.name,
            "qualified_name": qualified_name,
            "parent_class": parent["qualified_name"] if parent else None,
            "start_lineno": node.lineno,
            "end_lineno": getattr(node, "end_lineno", None),
            "docstring": ast.get_docstring(node),
            "imports": list(set(used_imports)),
            "is_async": is_async
        })
        
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        parent = self.current_class
        
        qualified_name = (
            f"{parent['qualified_name']}.{node.name}"
            if parent
            else node.name
        )
        
        used_names = extract_used_names(node)
        used_imports = [
            self.import_map[n] for n in used_names if n in self.import_map
        ]
        
        class_symbol = {
            "file_path": self.file_path,
            "symbol_type": "class",
            "name": node.name,
            "qualified_name": qualified_name,
            "parent_class": parent["qualified_name"] if parent else None,
            "start_lineno": node.lineno,
            "end_lineno": getattr(node, "end_lineno", None),
            "docstring": ast.get_docstring(node),
            "imports": list(set(used_imports)),
        }
        
        self.symbols.append(class_symbol)
        
        self.class_stack.append(class_symbol)
        self.generic_visit(node)
        self.class_stack.pop()
    
    def visit_FunctionDef(self, node):
        self._handle_function(node, is_async=False)
    
    def visit_AsyncFunctionDef(self, node):
        self._handle_function(node, is_async=True)


def extract_module_exports(tree: ast.AST, file_path: str) -> tuple:
    """Extract module-level exports and variables."""
    exports = set()
    variable_symbols = []
    module_qname = '.'.join(file_path.split('.')[0].split('\\')[1:])
    import_map = build_import_map(tree)
    
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    exports.add(target.id)
                    used_names = extract_used_names(node)
                    variable_symbols.append({
                        "file_path": file_path,
                        "symbol_type": "variable",
                        "name": target.id,
                        "parent_class": None,
                        "docstring": None,
                        "qualified_name": f"{module_qname}.{target.id}",
                        "start_lineno": node.lineno,
                        "end_lineno": getattr(node, "end_lineno", node.lineno),
                        "value_repr": ast.unparse(node.value) if hasattr(ast, "unparse") else None,
                        "imports": [import_map[n] for n in used_names if n in import_map]
                    })
        
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                exports.add(node.target.id)
                used_names = extract_used_names(node)
                variable_symbols.append({
                    "file_path": file_path,
                    "symbol_type": "variable",
                    "name": node.target.id,
                    "parent_class": None,
                    "docstring": None,
                    "qualified_name": f"{module_qname}.{node.target.id}",
                    "start_lineno": node.lineno,
                    "end_lineno": getattr(node, "end_lineno", node.lineno),
                    "value_repr": ast.unparse(node.value) if node.value and hasattr(ast, "unparse") else None,
                    "imports": [import_map[n] for n in used_names if n in import_map]
                })
    
    return list(exports), variable_symbols


def parse_file(file_info: Dict, repo_root: str) -> List[Dict]:
    """Parse a single file and extract all symbols."""
    file_path = file_info["path"]
    absolute_path = file_info["absolute_path"]
    
    with open(absolute_path, "r", encoding="utf-8") as f:
        file_code = f.read()
    
    tree = ast.parse(file_code)
    import_map = build_import_map(tree)
    
    # Calculate module qualified name from repo root
    # e.g. "C:/Start/repo/app/main.py" -> "app.main"
    try:
        rel_path = Path(absolute_path).relative_to(repo_root)
        # Remove extension and replace separators with dots
        module_qname = ".".join(rel_path.with_suffix("").parts)
    except ValueError:
        # Fallback if path is not relative (shouldn't happen with correct usage)
        module_qname = Path(file_path).stem

    # Extract functions, classes, methods
    visitor = SymbolVisitor(file_path, import_map)
    # We need to inject the module_qname into the visitor so it can construct full names
    # But wait, the visitor constructs names based on nesting strings. 
    # Current visitor implementation:
    # qualified_name = f"{parent['qualified_name']}.{node.name}" if parent else node.name
    # This generates "ClassName.method_name" or "function_name".
    # It does NOT include the module prefix currently?
    # Let's check the visitor in previous file context...
    # The visitor produces "qualified_name" as just local to the file (e.g. "MyClass.my_method").
    # The final UID generation loop below prepends the module name.
    
    visitor.visit(tree)
    symbols = visitor.symbols
    
    # Extract module-level variables
    exports, variable_symbols = extract_module_exports(tree, file_path)
    # Variable symbols need to be fixed too in extract_module_exports or post-processed
    # The current extract_module_exports calculates module_qname independently. 
    # We should probably update the symbols loop below to fix ALL qualified names.
    
    symbols.extend(variable_symbols)
    
    line_count = sum(1 for _ in file_code.splitlines())
    
    module_symbol = {
        "file_path": file_path,
        "symbol_type": "module",
        "name": Path(file_path).stem,
        "start_lineno": 1,
        "end_lineno": line_count,
        "qualified_name": module_qname,
        "parent_class": None,
        "docstring": ast.get_docstring(tree),
        "exports": exports,
        "imports": list(import_map.values()),
    }
    
    symbols.append(module_symbol)
    
    # Add code snippets and UIDs
    for symbol in symbols:
        start = symbol['start_lineno'] - 1
        end = symbol['end_lineno'] or start + 1
        symbol['code'] = '\n'.join(file_code.splitlines()[start:end])
        
        # FIX: Ensure all symbols use the correct module prefix
        if symbol['symbol_type'] == 'module':
            symbol['UID'] = module_qname
            # qualified_name is already set
            
        elif symbol['symbol_type'] == 'variable':
             # extract_module_exports might have set a bad qname, let's reset it
             # Variable name is symbol['name']
             symbol['qualified_name'] = f"{module_qname}.{symbol['name']}"
             symbol['UID'] = symbol['qualified_name']
             
        else:
            # Functions and Classes
            # symbol['qualified_name'] from visitor is "Class.method" or "func"
            # We want "module.Class.method"
            local_qname = symbol['qualified_name']
            
            # The visitor usually sets qualified_name to just the name for top-level functions?
            # Let's check visitor._handle_function:
            # if parent: f"{parent}.{name}" else: node.name
            # Yes. So we must prepend module_qname
            
            full_qname = f"{module_qname}.{local_qname}"
            symbol['qualified_name'] = full_qname
            symbol['UID'] = full_qname
            
            # Update parent_class to include module prefix if it exists
            if symbol.get('parent_class'):
                 symbol['parent_class'] = f"{module_qname}.{symbol['parent_class']}"

    return symbols


# -------------------------
# Dependency Analysis
# -------------------------

def add_dependencies(symbols: List[Dict]) -> List[Dict]:
    """Add dependency relationships between symbols."""
    # Build index
    symbol_index = {s['UID']: s for s in symbols}
    
    # Initialize dependency fields
    for symbol in symbols:
        symbol['depends_on'] = set()
        symbol['used_by'] = set()
        symbol['ext_dependencies'] = set()
    
    # Build relationships
    for symbol in symbols:
        for imported in symbol.get('imports', []):
            if imported in symbol_index:
                symbol['depends_on'].add(imported)
                symbol_index[imported]['used_by'].add(symbol['UID'])
            else:
                symbol['ext_dependencies'].add(imported)
    
    # Convert sets to sorted lists
    for symbol in symbols:
        symbol['depends_on'] = sorted(symbol['depends_on'])
        symbol['used_by'] = sorted(symbol['used_by'])
        symbol['ext_dependencies'] = sorted(symbol['ext_dependencies'])
    
    return symbols


# -------------------------
# Main Parser Function
# -------------------------

def parse_repository(repo_name: str, output_path: str) -> Dict:
    """
    Parse entire repository and output comprehensive symbol data.
    
    Args:
        repo_name: Name/path of the repository
        output_path: Path to save symbols_final.json
        
    Returns:
        Dictionary with repo info and all symbols
    """
    print(f"Parsing repository: {repo_name}")
    
    # Discover files
    files = get_included_files(repo_name)
    print(f"Found {len(files)} Python files")
    
    repo_root = str(Path(repo_name).resolve())
    
    # Parse all files
    all_symbols = []
    for file_info in files:
        try:
            symbols = parse_file(file_info, repo_root)
            all_symbols.extend(symbols)
        except Exception as e:
            print(f"Error parsing {file_info['path']}: {e}")
    
    print(f"Extracted {len(all_symbols)} symbols")
    
    # Add dependencies
    all_symbols = add_dependencies(all_symbols)
    
    # Build final output
    result = {
        "repo": {
            "name": repo_name,
            "language": "python",
            "absolute_path": str(Path(repo_name).resolve())
        },
        "symbols": all_symbols
    }
    
    # Save to file
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    print(f"Saved symbols to {output_path}")
    
    return result
