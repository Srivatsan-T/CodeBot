
from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
import networkx as nx
from typing import List, Dict, Tuple
import pydot

def get_module_label(file_path: str) -> str:
    """Generate a concise label for the module (filename)."""
    return Path(file_path).name

def build_module_graph(metadata: List[Dict]) -> nx.DiGraph:
    """
    Build a module-level dependency graph directly from metadata.
    
    Nodes: Modules (files)
    Edges: Import relationships derived from 'depends_on' and 'used_by'
    """
    G = nx.DiGraph()
    
    # 1. Index all modules
    # Map: qualified_name_prefix -> file_path
    # e.g. "app.main" -> "app/main.py"
    # We also need a way to map symbol UIDs to their home modules.
    
    uid_to_module_file = {}
    module_files = set()
    
    # First pass: Identify modules and build UID map
    for symbol in metadata:
        if symbol.get("symbol_type") == "module":
            fpath = symbol.get("file_path")
            if fpath:
                module_files.add(fpath)
                # Register module UID itself
                if "uid" in symbol:
                    uid_to_module_file[symbol["uid"]] = fpath
                
        # Register all symbols to their file_path
        # This allows us to resolve "app.core.config.get_app_settings" -> "config.py"
        if "uid" in symbol and "file_path" in symbol:
             uid_to_module_file[symbol["uid"]] = symbol["file_path"]

    # Add nodes for all modules found
    for fpath in module_files:
        G.add_node(
            fpath,
            type="module",
            label=get_module_label(fpath),
            tooltip=fpath
        )

    # 2. Add Edges based on 'depends_on' in MODULE entries
    # The user specifically asked to use the module's depends_on/used_by tags.
    
    for symbol in metadata:
        if symbol.get("symbol_type") != "module":
            continue
            
        src_file = symbol.get("file_path")
        if not src_file:
            continue
            
        # Check dependencies
        # depends_on: ["app.core.config.get_app_settings", ...]
        for dep_uid in symbol.get("depends_on", []):
            # Resolve dep_uid to its module file
            dst_file = uid_to_module_file.get(dep_uid)
            
            # Additional fallback: strict module match if UID is just a module prefix?
            # But the map should cover it if metadata is complete.
            
            if dst_file and dst_file != src_file:
                 G.add_edge(src_file, dst_file)

    return G

def export_to_dot(graph: nx.DiGraph, output_path: Path, cluster=True) -> None:
    """Export graph to a DOT file with readable styling and clusters."""
    
    # Create base Pydot graph
    dot = pydot.Dot(graph_type="digraph", rankdir="LR", splines="ortho", nodesep="0.6", ranksep="1.0")
    
    # Track nodes added
    processed_nodes = set()
    
    if cluster:
        clusters = defaultdict(list)
        for node, attrs in graph.nodes(data=True):
            node_id = str(node)
            path_obj = Path(node_id)
            # Group by parent directory (normalized for Windows)
            parent_dir = str(path_obj.parent).replace('\\', '/')
            clusters[parent_dir].append((node, attrs))

        for group, nodes in clusters.items():
            # Sanitize cluster name
            safe_group = group.replace(':', '').replace('/', '_').replace('.', '_').replace('\\', '_').replace(' ', '_')
            cluster_name = f"cluster_{safe_group}"
            cluster_label = group.split('/')[-1] if '/' in group else group
            
            subg = pydot.Subgraph(cluster_name, label=cluster_label, style="rounded", color="#cbd5e1", bgcolor="#f8fafc")
            
            for node, attrs in nodes:
                if node in processed_nodes: continue
                node_str = str(node)
                label = attrs.get("label", Path(node_str).name)
                tooltip = attrs.get("tooltip", node_str)
                
                n = pydot.Node(
                    f'"{node_str}"', 
                    label=label, 
                    tooltip=tooltip, 
                    shape="box", 
                    style="filled", 
                    fillcolor="#ffffff", 
                    fontname="Inter"
                )
                subg.add_node(n)
                processed_nodes.add(node)
            
            dot.add_subgraph(subg)
            
    # Add Edges
    for u, v in graph.edges():
        edge = pydot.Edge(f'"{str(u)}"', f'"{str(v)}"', color="#64748b", arrowsize="0.7")
        dot.add_edge(edge)
    
    output_path.write_text(dot.to_string(), encoding="utf-8")

def graph(metadata: List[Dict], output_dot: str) -> Tuple[nx.DiGraph, nx.DiGraph]:
    """Generate module architecture graph."""
    module_graph = build_module_graph(metadata)
    Path(output_dot).parent.mkdir(parents=True, exist_ok=True)
    export_to_dot(module_graph, Path(output_dot), cluster=True)
    return module_graph, module_graph

def module_subgraph(graph: nx.DiGraph, module_summaries, selected_module_ids: dict, output_dot) -> nx.DiGraph:
    selected_paths = selected_module_ids.get('selected_modules', [])
    if not selected_paths:
        return nx.DiGraph()
    subgraph = graph.subgraph(selected_paths).copy()
    export_to_dot(subgraph, Path(output_dot), cluster=True)
    return subgraph

def symbol_subgraph(symbol_graph: nx.DiGraph, selected_symbols: list, flow_path: list, output_dot: str, metadata: list) -> nx.DiGraph:
    return nx.DiGraph()
