import os
from pathlib import Path
from typing import List, Optional
import time

from config import Config
from utils import get_config_for_project, save_project, load_projects
from core.parser import parse_repository
from core.embedding import load_or_create_index
from core.retrieval import generate_retrievals
from agents import load_or_build_module_summaries, generate_codebase_overview, documentation_agent
from arch import graph

def initialize_project(project_name: str, repo_path: str):
    """
    Full initialization of a project:
    1. Parse repo
    2. Build vector index
    3. Generate module summaries
    4. Build graph
    """
    print(f"Initializing {project_name} at {repo_path}...")
    config = get_config_for_project(project_name)
    
    # 1. Parse
    metadata = parse_repository(repo_path, config.symbols_path)
    
    # 2. Vector Index
    retrievals = generate_retrievals(metadata)
    vectorstore, metadata_list = load_or_create_index(
        retrievals,
        config.embedding_model,
        config.vector_dir
    )
    
    # 3. Module Summaries
    module_summaries = load_or_build_module_summaries(
        config.llm_config_path,
        metadata_list,
        config.module_summary_path
    )
    
    # 4. Graph
    graph(metadata_list, config.arch_dot)
    
    # Register project
    save_project(project_name, repo_path)
    
    return config, metadata_list

def generate_full_documentation(project_name: str):
    """
    Generate documentation for all modules in the project.
    """
    print(f"Generating full documentation for {project_name}...")
    config = get_config_for_project(project_name)
    
    # Load state
    # We need to reload the vector store and metadata
    # This assumes initialize_project has been run
    from core.embedding import load_or_create_index # re-import to avoid circular
    from core.retrieval import generate_retrievals
    import json
    
    if not os.path.exists(config.symbols_path):
        raise ValueError(f"Project {project_name} not initialized.")
        
    with open(config.symbols_path, "r", encoding="utf-8") as f:
        metadata_raw = json.load(f)
        
    retrievals = generate_retrievals(metadata_raw)
    vectorstore, metadata_list = load_or_create_index(
        retrievals,
        config.embedding_model,
        config.vector_dir
    )
    
    # Mock planner output for documentation
    from agents.planner_agent import PlannerOutput
    
    # Iterate over all modules
    modules = set(m['file_path'] for m in metadata_list if m['symbol_type'] == 'module')
    
    docs_generated = []
    
    for module_path in modules:
        module_name = Path(module_path).name
        print(f"Documenting module: {module_name}")
        
        plan = PlannerOutput(
            intent="documentation",
            scope="module",
            is_valid=True,
            confidence=1.0,
            original_query=f"Document the module {module_name}"
        )
        
        doc_content = documentation_agent(
            config.llm_config_path,
            plan,
            f"Generate comprehensive documentation for {module_name}",
            vectorstore,
            metadata_list,
            config.embedding_model,
            config.docs_dir
        )
        docs_generated.append(module_name)
        
    print(f"Generated documentation for {len(docs_generated)} modules.")
    return docs_generated

def incremental_update(project_name: str, modified_files: List[str]):
    """
    Handle incremental updates triggered by webhooks.
    1. Re-parse specific files (or full repo for simplicity in prototype)
    2. Update vector index
    3. Re-generate docs for modified modules
    """
    print(f"Incremental update for {project_name}. Files: {modified_files}")
    projects = load_projects()
    repo_path = projects.get(project_name)
    if not repo_path:
        raise ValueError(f"Project {project_name} not found.")
        
    # For prototype simplicity: Re-initialize to update index/graph
    # Optimization: Parsing only modified files would be better but requires more logic
    config, metadata_list = initialize_project(project_name, repo_path)
    
    # Re-generate docs for modified files
    # Check if modified file corresponds to a module in metadata
    # Simple check: filename match
    
    docs_updated = []
    
    # Load vector store again (returned from init)
    # We need strictly the object, but initialize_project returns config/metadata tuple
    # Let's reload to be safe and consistent with generate_full_documentation structure
    # Actually initialize_project already loads it. We can just use the config to get path.
    
    # Reload vectorstore for the agent
    retrievals = generate_retrievals({"symbols": metadata_list}) # metadata_list is slightly different structure than raw parse?
    # parse_repository returns dict with 'symbols' key. initialize_project returns list of dicts.
    # generate_retrievals expects dict with 'symbols' key OR path.
    # Let's align.
    
    # Fix: initialize_project returns metadata_list which IS the list of retrieval units/dicts?
    # No, load_or_create_index returns metadata_list.
    # Let's just reload cleanly.
    
    from core.embedding import load_or_create_index
    vectorstore, metadata_list = load_or_create_index(
        retrievals, # Wait, retrievals is needed.
        config.embedding_model,
        config.vector_dir
    )
    
    from agents.planner_agent import PlannerOutput
    
    for file_path in modified_files:
        # Normalize path separators
        file_path = file_path.replace("/", "\\") if os.name == 'nt' else file_path.replace("\\", "/")
        
        # Check if this file is in our modules
        # This is a loose check. Ideally we match absolute paths.
        
        # We'll just try to document it if it looks like a python file
        if file_path.endswith(".py"):
             module_name = Path(file_path).name
             print(f"Updating docs for: {module_name}")
             
             plan = PlannerOutput(
                intent="documentation",
                scope="module",
                is_valid=True,
                confidence=1.0,
                original_query=f"Update documentation for modified module {module_name}"
             )
             
             documentation_agent(
                config.llm_config_path,
                plan,
                f"Update documentation for {module_name} following recent changes.",
                vectorstore,
                metadata_list,
                config.embedding_model,
                config.docs_dir
             )
             docs_updated.append(module_name)
             
    return docs_updated
