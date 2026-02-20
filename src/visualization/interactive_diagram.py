"""Interactive diagram generation using Pyvis for network visualization."""

from typing import List, Dict, Any, Optional
from pathlib import Path
import networkx as nx
from pyvis.network import Network
import json


def build_hierarchical_graph(
    metadata: List[Dict[str, Any]],
    include_functions: bool = True,
    include_classes: bool = True
) -> nx.DiGraph:
    """
    Build a hierarchical dependency graph including modules, classes, and functions.
    
    Args:
        metadata: List of all symbols with their metadata
        include_functions: Whether to include function nodes
        include_classes: Whether to include class nodes
        
    Returns:
        NetworkX directed graph with hierarchical structure
    """
    G = nx.DiGraph()
    
    # Sort for deterministic ordering
    symbols = sorted(metadata, key=lambda s: s.get("uid", ""))
    
    # Add nodes with proper attributes
    for symbol in symbols:
        uid = symbol.get("uid", "")
        symbol_type = symbol.get("symbol_type", "")
        qualified_name = symbol.get("qualified_name", uid)
        file_path = symbol.get("file_path", "")
        
        # Filter based on type
        if symbol_type == "function" and not include_functions:
            continue
        if symbol_type == "class" and not include_classes:
            continue
        
        # Determine node level (for hierarchical layout)
        if symbol_type == "module":
            level = 0
            color = "#4f46e5"  # Indigo for modules
            shape = "box"
            size = 30
        elif symbol_type == "class":
            level = 1
            color = "#10b981"  # Green for classes
            shape = "ellipse"
            size = 20
        elif symbol_type == "function":
            level = 2
            color = "#f59e0b"  # Amber for functions
            shape = "dot"
            size = 15
        else:
            level = 3
            color = "#6b7280"  # Gray for variables
            shape = "dot"
            size = 10
        
        G.add_node(
            uid,
            label=qualified_name.split(".")[-1],  # Show only the last part
            title=f"{symbol_type}: {qualified_name}\nFile: {file_path}",  # Tooltip
            type=symbol_type,
            file_path=file_path,
            qualified_name=qualified_name,
            level=level,
            color=color,
            shape=shape,
            size=size
        )
    
    # Add edges (dependencies)
    for symbol in symbols:
        src = symbol.get("uid", "")
        if src not in G:
            continue
            
        for dep in symbol.get("depends_on", []):
            if dep in G:  # Only add edge if both nodes exist
                G.add_edge(src, dep)
    
    return G


def create_interactive_diagram(
    graph: nx.DiGraph,
    output_path: str,
    title: str = "Codebase Architecture",
    height: str = "750px",
    width: str = "100%",
    physics_enabled: bool = True
) -> str:
    """
    Create an interactive Pyvis network diagram from NetworkX graph.
    
    Args:
        graph: NetworkX graph with node attributes
        output_path: Path to save HTML file
        title: Title of the diagram
        height: Height of the visualization
        width: Width of the visualization
        physics_enabled: Whether to enable physics simulation
        
    Returns:
        Path to generated HTML file
    """
    net = Network(
        height=height,
        width=width,
        directed=True,
        notebook=False,
        heading=title
    )
    
    # Configure physics for better layout
    if physics_enabled:
        net.set_options("""
        {
          "physics": {
            "enabled": true,
            "hierarchicalRepulsion": {
              "centralGravity": 0.0,
              "springLength": 200,
              "springConstant": 0.01,
              "nodeDistance": 150,
              "damping": 0.09
            },
            "solver": "hierarchicalRepulsion"
          },
          "layout": {
            "hierarchical": {
              "enabled": true,
              "direction": "LR",
              "sortMethod": "directed",
              "levelSeparation": 200,
              "nodeSpacing": 150
            }
          },
          "interaction": {
            "hover": true,
            "navigationButtons": true,
            "keyboard": true,
            "zoomView": true
          }
        }
        """)
    
    # Add nodes from NetworkX graph
    for node, attrs in graph.nodes(data=True):
        net.add_node(
            node,
            label=attrs.get("label", node),
            title=attrs.get("title", node),
            color=attrs.get("color", "#97c2fc"),
            shape=attrs.get("shape", "dot"),
            size=attrs.get("size", 15),
            level=attrs.get("level", 0)
        )
    
    # Add edges
    for src, dst in graph.edges():
        net.add_edge(src, dst, arrows="to", color="#999999")
    
    # Save to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(output_file))
    
    return str(output_file)


def create_module_level_diagram(
    metadata: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    Create a module-level architecture diagram (high-level view).
    
    Args:
        metadata: List of all symbols
        output_path: Path to save HTML file
        
    Returns:
        Path to generated HTML file
    """
    # Build module-level graph
    module_graph = nx.DiGraph()
    
    # Group symbols by module
    modules = {}
    for symbol in metadata:
        file_path = symbol.get("file_path", "")
        if file_path not in modules:
            modules[file_path] = []
        modules[file_path].append(symbol)
    
    # Add module nodes
    for file_path, symbols in modules.items():
        module_name = Path(file_path).stem
        num_symbols = len(symbols)
        
        module_graph.add_node(
            file_path,
            label=module_name,
            title=f"Module: {file_path}\n{num_symbols} symbols",
            color="#4f46e5",
            shape="box",
            size=20 + min(num_symbols * 2, 40)  # Size based on symbol count
        )
    
    # Add module dependencies
    for symbol in metadata:
        src_module = symbol.get("file_path", "")
        for dep_uid in symbol.get("depends_on", []):
            # Find the module of the dependency
            for other_symbol in metadata:
                if other_symbol.get("uid") == dep_uid:
                    dst_module = other_symbol.get("file_path", "")
                    if src_module != dst_module and src_module and dst_module:
                        module_graph.add_edge(src_module, dst_module)
                    break
    
    return create_interactive_diagram(
        module_graph,
        output_path,
        title="Module-Level Architecture"
    )


def create_intra_module_diagram(
    module_path: str,
    metadata: List[Dict[str, Any]],
    output_path: str
) -> str:
    """
    Create a detailed diagram showing functions and classes within a specific module.
    
    Args:
        module_path: Path to the module to visualize
        metadata: List of all symbols
        output_path: Path to save HTML file
        
    Returns:
        Path to generated HTML file
    """
    # Filter symbols for this module
    module_symbols = [
        s for s in metadata
        if s.get("file_path") == module_path
    ]
    
    # Build intra-module graph
    intra_graph = build_hierarchical_graph(
        module_symbols,
        include_functions=True,
        include_classes=True
    )
    
    module_name = Path(module_path).stem
    return create_interactive_diagram(
        intra_graph,
        output_path,
        title=f"Intra-Module View: {module_name}"
    )


def create_full_hierarchical_diagram(
    metadata: List[Dict[str, Any]],
    output_path: str,
    max_nodes: int = 200
) -> str:
    """
    Create a full hierarchical diagram with modules, classes, and functions.
    
    For large codebases, this may be overwhelming. Consider using filtered views.
    
    Args:
        metadata: List of all symbols
        output_path: Path to save HTML file
        max_nodes: Maximum number of nodes to include (to avoid overwhelming visualization)
        
    Returns:
        Path to generated HTML file
    """
    # Build full graph
    full_graph = build_hierarchical_graph(
        metadata,
        include_functions=True,
        include_classes=True
    )
    
    # If too many nodes, filter to most connected
    if len(full_graph.nodes()) > max_nodes:
        print(f"Graph has {len(full_graph.nodes())} nodes, filtering to top {max_nodes} by degree...")
        
        # Get nodes sorted by degree (most connected first)
        node_degrees = sorted(
            full_graph.degree(),
            key=lambda x: x[1],
            reverse=True
        )
        top_nodes = [node for node, degree in node_degrees[:max_nodes]]
        
        # Create subgraph
        full_graph = full_graph.subgraph(top_nodes).copy()
    
    return create_interactive_diagram(
        full_graph,
        output_path,
        title="Full Hierarchical Architecture"
    )
