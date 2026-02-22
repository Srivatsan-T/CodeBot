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

def generate_full_documentation(project_name: str, progress_callback=None, api_key: str = None):
    """
    Generate documentation for all modules in the project.
    Accepts an optional progress_callback(current, total, current_item_name).
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
    modules_list = list(modules)
    total_modules = len(modules_list)
    
    docs_generated = []
    
    for i, module_path in enumerate(modules_list):
        module_name = Path(module_path).name
        print(f"Documenting module: {module_name}")
        
        if progress_callback:
            progress_callback(i, total_modules, module_name)
            
        plan = PlannerOutput(
            intent="documentation",
            scope="module",
            is_valid=True,
            confidence=1.0,
            original_query=f"Document the module {module_name}",
            needs_dependencies=False
        )
        
        doc_content = documentation_agent(
            config.llm_config_path,
            plan,
            f"Generate comprehensive documentation for {module_name}",
            vectorstore,
            metadata_list,
            config.embedding_model,
            config.docs_dir,
            api_key=api_key
        )
        docs_generated.append(module_name)
        
    if progress_callback:
        progress_callback(total_modules, total_modules, "Complete")
        
    print(f"Generated documentation for {len(docs_generated)} modules.")
    return docs_generated

def incremental_update(project_name: str, modified_files: List[str]):
    """
    Handle updates triggered by webhooks.
    As requested, simply reloads the repo with a git pull and re-initializes from scratch.
    """
    import subprocess
    print(f"Update for {project_name}. Triggered by files: {modified_files}")
    projects = load_projects()
    project_info = projects.get(project_name)
    
    if not project_info:
        raise ValueError(f"Project {project_name} not found.")
        
    repo_path = project_info.get("path")
    git_url = project_info.get("git_url")
    
    # 1. Pull latest changes if it's a cloned git repo
    if git_url and Path(repo_path).joinpath(".git").exists():
        print(f"Pulling latest changes for {project_name} from {git_url}...")
        try:
            subprocess.run(
                ["git", "-C", repo_path, "pull"],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to git pull for {project_name}: {e.stderr}")
            # Continuing initialization even if pull fails, just in case.
            
    # 2. Total Rebuild
    print(f"Re-initializing project {project_name} completely...")
    config, metadata_list = initialize_project(project_name, repo_path)
    
    # 3. Generate Documentation directly into the repository
    print(f"Generating updated documentation into the repository for {project_name}...")
    
    # Store original docs dir to restore later just in case
    original_docs_dir = config.docs_dir
    
    # Map the docs directory to be inside the cloned repository
    repo_docs_dir = Path(repo_path) / "docs"
    repo_docs_dir.mkdir(exist_ok=True)
    config.docs_dir = str(repo_docs_dir)
    
    docs_generated = []
    
    # Iterating over modules to generate docs (similar to generate_full_documentation but overriding docs_dir)
    from agents.planner_agent import PlannerOutput
    modules = set(m['file_path'] for m in metadata_list if m['symbol_type'] == 'module')
    
    for module_path in modules:
        module_name = Path(module_path).name
        print(f"Documenting module: {module_name}")
        
        plan = PlannerOutput(
            intent="documentation",
            scope="module",
            is_valid=True,
            confidence=1.0,
            original_query=f"Document the module {module_name}",
            needs_dependencies=False
        )
        
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv(override=True)
            webhook_api_key = os.getenv("AWS_ACCESS_KEY_ID")

            # We must pass the correct docs_dir to the agent
            documentation_agent(
                config.llm_config_path,
                plan,
                f"Generate comprehensive documentation for {module_name}",
                None,  # Not used in our mock implementation
                metadata_list,
                config.embedding_model,
                config.docs_dir,
                api_key=webhook_api_key
            )
            docs_generated.append(module_name)
        except Exception as e:
            print(f"Error documenting {module_name}: {e}")
            
    # Restore original dir
    config.docs_dir = original_docs_dir
            
    # 4. Git Push the generated docs back
    if git_url and Path(repo_path).joinpath(".git").exists():
        print(f"Pushing documentation updates to GitHub for {project_name}...")
        try:
            # Add ONLY the docs directory to avoid accidentally committing user's unpushed config
            subprocess.run(["git", "-C", repo_path, "add", "docs/"], check=True, capture_output=True)
            
            # Commit. 
            # Note: We use a specific prefix [CodeBot] so the webhook server can ignore its own commits.
            commit_res = subprocess.run(
                ["git", "-C", repo_path, "commit", "-m", "[CodeBot] Auto-generated documentation update"],
                capture_output=True, text=True
            )
            
            if "nothing to commit" not in commit_res.stdout:
                subprocess.run(["git", "-C", repo_path, "push"], check=True, capture_output=True)
                print("Successfully pushed documentation to repository!")
            else:
                print("Documentation was already up to date. Nothing to push.")
                
        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to git push docs for {project_name}: {e.stderr}")
    
    return [m["file_path"] for m in metadata_list if m["symbol_type"] == "module"]
