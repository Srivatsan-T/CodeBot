import os
from pathlib import Path
from typing import List, Optional
import time
import logging

logger = logging.getLogger("webhook")

from config import Config
from utils import get_config_for_project, save_project, load_projects
from core.parser import parse_repository
from core.embedding import load_or_create_index
from core.retrieval import generate_retrievals
from agents import load_or_build_module_summaries, generate_codebase_overview, documentation_agent
from arch import graph

def initialize_project(project_name: str, repo_path: str, git_url: str = None, force_rebuild: bool = False):
    """
    Full initialization of a project:
    1. Parse repo
    2. Build vector index
    3. Generate module summaries
    4. Build graph
    """
    logger.info(f"Initializing {project_name} at {repo_path}...")
    config = get_config_for_project(project_name)
    
    # 1. Parse
    metadata = parse_repository(repo_path, config.symbols_path)
    
    # 2. Vector Index
    retrievals = generate_retrievals(metadata)
    vectorstore, metadata_list = load_or_create_index(
        retrievals,
        config.embedding_model,
        config.vector_dir,
        force_rebuild=force_rebuild
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
    save_project(project_name, repo_path, git_url)
    
    return config, metadata_list, vectorstore

def generate_full_documentation(project_name: str, progress_callback=None, api_key: str = None):
    """
    Generate documentation for all modules in the project.
    Accepts an optional progress_callback(current, total, current_item_name).
    """
    logger.info(f"Generating full documentation for {project_name}...")
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
        logger.info(f"Documenting module: {module_name}")
        
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
            module_name=module_name,
            api_key=api_key
        )
        docs_generated.append(module_name)
        
    if progress_callback:
        progress_callback(total_modules, total_modules, "Complete")
        
    logger.info(f"Generated documentation for {len(docs_generated)} modules.")
    return docs_generated

def incremental_update(project_name: str, modified_files: List[str] = None, removed_files: List[str] = None, full_rebuild: bool = False):
    """
    Handle updates triggered by webhooks.
    As requested, simply reloads the repo with a git pull and re-initializes from scratch.
    """
    import subprocess
    modified_files = modified_files or []
    removed_files = removed_files or []
    logger.info(f"Update for {project_name}. Full Rebuild: {full_rebuild}, Modified: {modified_files}, Removed: {removed_files}")
    projects = load_projects()
    project_info = projects.get(project_name)
    
    if not project_info:
        raise ValueError(f"Project {project_name} not found.")
        
    repo_path = project_info.get("path")
    git_url = project_info.get("git_url")
    
    # 1. Pull latest changes if it's a cloned git repo
    if git_url and Path(repo_path).joinpath(".git").exists():
        logger.info(f"Pulling latest changes for {project_name} from {git_url}...")
        try:
            subprocess.run(
                ["git", "-C", repo_path, "pull"],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to git pull for {project_name}: {e.stderr}")
            # Continuing initialization even if pull fails, just in case.
            
    # 2. Total Rebuild
    logger.info(f"Re-initializing project {project_name} completely...")
    config, metadata_list, vectorstore = initialize_project(project_name, repo_path, git_url, force_rebuild=True)
    
    # 3. Generate Documentation directly into the repository
    logger.info(f"Generating updated documentation into the repository for {project_name}...")
    
    # Store original docs dir to restore later just in case
    original_docs_dir = config.docs_dir
    
    # Map the docs directory to be inside the cloned repository
    repo_docs_dir = Path(repo_path) / "docs"
    repo_docs_dir.mkdir(exist_ok=True)
    config.docs_dir = str(repo_docs_dir)
    
    # 3.1 Handle removed files
    if removed_files:
        logger.info(f"Removing documentation for {len(removed_files)} deleted files...")
        for removed in removed_files:
            # Files are typically e.g. 'src/utils.py'. The doc is 'utils.py.md'
            filename = Path(removed).name + ".md"
            doc_file = repo_docs_dir / filename
            if doc_file.exists():
                try:
                    doc_file.unlink()
                    logger.info(f"Deleted outdated doc file: {doc_file}")
                except Exception as e:
                    logger.error(f"Error deleting doc file {doc_file}: {e}")
    
    docs_generated = []
    
    # Iterating over modules to generate docs (similar to generate_full_documentation but overriding docs_dir)
    from agents.planner_agent import PlannerOutput
    modules = set(m['file_path'] for m in metadata_list if m['symbol_type'] == 'module')
    
    # 3.2 Filter for modified files (if any are provided)
    if not full_rebuild:
        logger.info(f"Filtering {len(modules)} modules to only those modified...")
        filtered_modules = set()
        for mod in modules:
            mod_posix = Path(mod).as_posix()
            if any(mod_posix.endswith(mf) for mf in modified_files):
                filtered_modules.add(mod)
        modules = filtered_modules
        logger.info(f"Found {len(modules)} modules requiring documentation updates.")
    
    for module_path in modules:
        module_name = Path(module_path).name
        logger.info(f"Documenting module: {module_name}")
        
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
                vectorstore,
                metadata_list,
                config.embedding_model,
                config.docs_dir,
                module_name=module_name,
                api_key=webhook_api_key
            )
            docs_generated.append(module_name)
        except Exception as e:
            logger.error(f"Error documenting {module_name}: {e}")
            
    # 3.3 Generate Master Document
    logger.info(f"Compiling Master Document for {project_name}...")
    try:
        from core.embedding import load_or_create_index
        from agents import load_or_build_module_summaries, generate_codebase_overview
        import os
        from dotenv import load_dotenv
        load_dotenv(override=True)
        webhook_api_key = os.getenv("AWS_ACCESS_KEY_ID")
        
        # Load module summaries to write the overview
        module_summaries = load_or_build_module_summaries(
            config.llm_config_path,
            metadata_list,
            config.module_summary_path,
            api_key=webhook_api_key
        )
        
        overview_text = generate_codebase_overview(
            module_summaries,
            config.docs_dir
        )
        
        # Concatenate everything
        master_content = f"# {project_name} Codebase Overview\n\n{overview_text}\n\n---\n\n## Module Documentation\n\n"
        
        for md_file in repo_docs_dir.glob("*.md"):
            if md_file.name == "CODEBASE_SUMMARY.md":
                continue
            master_content += f"### {md_file.name}\n\n"
            master_content += md_file.read_text(encoding="utf-8") + "\n\n---\n\n"
            
        master_path = repo_docs_dir / "CODEBASE_SUMMARY.md"
        master_path.write_text(master_content, encoding="utf-8")
        logger.info(f"Successfully generated Master Document at {master_path}")
        
    except Exception as e:
        logger.error(f"Failed to generate Master Document: {e}")
            
    # Restore original dir
    config.docs_dir = original_docs_dir
            
    # 4. Git Push the generated docs back
    logger.info(f"Evaluating push conditions for {project_name}: git_url={bool(git_url)}, repo_path={repo_path}")
    logger.info(f"Does .git exist? {Path(repo_path).joinpath('.git').exists()}")
    if git_url and Path(repo_path).joinpath(".git").exists():
        logger.info(f"Preparing to push documentation updates to GitHub for {project_name}...")
        try:
            # Set git identity for the CodeBot container
            subprocess.run(["git", "-C", repo_path, "config", "user.name", "CodeBot"], check=True, capture_output=True, text=True)
            subprocess.run(["git", "-C", repo_path, "config", "user.email", "bot@codebot.ai"], check=True, capture_output=True, text=True)

            # Add ONLY the docs directory to avoid accidentally committing user's unpushed config
            subprocess.run(["git", "-C", repo_path, "add", "docs/"], check=True, capture_output=True, text=True)
            
            # Commit. 
            # Note: We use a specific prefix [CodeBot] so the webhook server can ignore its own commits.
            commit_res = subprocess.run(
                ["git", "-C", repo_path, "commit", "-m", "[CodeBot] Auto-generated documentation update"],
                capture_output=True, text=True
            )
            
            if "nothing to commit" not in commit_res.stdout:
                logger.info("Changes committed successfully. Executing git push...")
                push_res = subprocess.run(["git", "-C", repo_path, "push"], capture_output=True, text=True)
                if push_res.returncode == 0:
                     logger.info("Successfully pushed documentation to repository!")
                else:
                     logger.error(f"Failed to git push docs for {project_name}. Error: {push_res.stderr}")
            else:
                logger.info("Documentation was already up to date. Nothing to commit.")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to git execute docs generation step for {project_name}: {e.stderr}")
    
    return [m["file_path"] for m in metadata_list if m["symbol_type"] == "module"]
