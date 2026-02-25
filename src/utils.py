"""Shared utility functions used across multiple modules."""

import json
import os
from typing import Dict, List
from pathlib import Path
import subprocess
import datetime
import shutil
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from config import Config


def load_projects() -> dict:
    """Load the list of registered projects."""
    projects_file = Path(__file__).parent / "artifacts/projects.json"
    if not projects_file.exists():
        return {}
    try:
        with open(projects_file, "r") as f:
            data = json.load(f)
            # Handle backward compatibility: older projects.json had string values
            for k, v in data.items():
                if isinstance(v, str):
                    data[k] = {"path": v, "git_url": None}
            return data
    except Exception:
        return {}

def save_project(name: str, path: str, git_url: str = None):
    """Save a new project to the registry."""
    projects = load_projects()
    
    # Preserve existing git_url if not provided
    if git_url is None and name in projects:
        git_url = projects[name].get("git_url")
        
    projects[name] = {
        "path": path,
        "created_at": datetime.datetime.now().isoformat(),
        "git_url": git_url
    }
    projects_file = Path(__file__).parent / "artifacts/projects.json"
    projects_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(projects_file, "w") as f:
        json.dump(projects, f, indent=2)

def delete_project(name: str):
    """Delete a project from the registry and clean up its files."""
    projects = load_projects()
    if name not in projects:
        return
        
    project_info = projects[name]
    repo_path = Path(project_info["path"])
    
    # 1. Remove from registry
    del projects[name]
    projects_file = Path(__file__).parent / "artifacts/projects.json"
    with open(projects_file, "w") as f:
        json.dump(projects, f, indent=2)
        
    # 2. Remove artifacts directory
    artifacts_dir = Path(__file__).parent / "artifacts" / name
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        
    # 3. Clean up cloned/uploaded repositories
    if "cloned_repos" in repo_path.parts or "uploaded_repos" in repo_path.parts:
        # Avoid deleting the base clone/upload dir, just the project dir
        if repo_path.exists() and repo_path.is_dir():
             shutil.rmtree(repo_path, ignore_errors=True)

def get_config_for_project(project_name: str) -> Config:
    """Create a Config instance for a specific project."""
    return Config(project_name=project_name)


def load_config(path: str) -> dict:
    """Load JSON configuration file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_llm_for_agent(config: dict, agent_type: str, api_key: str = None) -> ChatOpenAI:
    """
    Factory to create an LLM instance for a specific agent type.
    
    Args:
        config: Full config dict
        agent_type: Type of agent (planner, symbol_selector, etc.)
        api_key: Optional API key override (e.g. from UI)
        
    Returns:
        ChatOpenAI instance configured for the active provider
    """
    # 1. Resolve active model config name
    if "active_models" in config and agent_type in config["active_models"]:
        config_name = config["active_models"][agent_type]
    else:
        raise ValueError(f"No configuration found for agent type: {agent_type}")

    return create_llm_from_config(config, config_name, api_key)


def create_llm_from_config(config: dict, agent_config_name: str, api_key: str = None) -> ChatOpenAI:
    """
    Create a LangChain ChatOpenAI instance from a specific config name.
    
    Args:
        config: Full config dict
        agent_config_name: Key in config['agents'] (e.g., 'planner_bedrock')
        api_key: Optional API key override
    
    Returns:
        ChatOpenAI instance
    """
    load_dotenv(override=True)
    
    if agent_config_name not in config["agents"]:
        raise ValueError(f"Agent config '{agent_config_name}' not found in llm_config.json")
        
    agent_cfg = config["agents"][agent_config_name]
    provider_name = agent_cfg["provider"]
    
    if provider_name not in config["providers"]:
        raise ValueError(f"Provider '{provider_name}' not found in llm_config.json")
        
    provider_cfg = config["providers"][provider_name]
    
    # Priority: Explicit Argument > Environment Variable
    if not api_key:
        api_key = os.getenv(provider_cfg["env_key"])
    
    # Provider-specific logic
    if provider_name == "openai":
        if not api_key: raise ValueError(f"Missing API Key for OpenAI. Please enter it in the UI or set {provider_cfg['env_key']}.")
    elif provider_name == "gemini":
        if not api_key: raise ValueError(f"Missing API Key for Gemini. Please enter it in the UI or set {provider_cfg['env_key']}.")
    
    return ChatOpenAI(
        model=agent_cfg["model"],
        temperature=agent_cfg["temperature"],
        base_url=provider_cfg["base_url"],
        api_key=api_key,
    )


def build_symbol_index(metadata: List[dict]) -> Dict[str, dict]:
    """Build a lookup index for symbols by qualified name."""
    return {
        s["qualified_name"]: s
        for s in metadata
    }


def expand_with_dependencies(symbol: dict, symbol_index: Dict[str, dict]) -> dict:
    """
    Expand a symbol with its dependencies and usage.
    
    Args:
        symbol: Symbol dict
        symbol_index: Lookup dict of all symbols
        
    Returns:
        Dict with primary symbol, depends_on, and used_by
    """
    def resolve(names):
        resolved = []
        for name in names or []:
            if name in symbol_index:
                resolved.append(symbol_index[name])
        return resolved
    
    return {
        "primary": symbol,
        "depends_on": resolve(symbol.get("depends_on")),
        "used_by": resolve(symbol.get("used_by")),
    }


def normalize_edges(edges: list) -> list:
    """Remove duplicate edges and sort."""
    seen = set()
    unique = []
    
    for e in edges:
        key = (e["from"], e["to"], e["type"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    
    return sorted(
        unique,
        key=lambda x: (x["from"], x["to"])
    )


def save_json(data: dict, path: str):
    """Save data to JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_json(path: str) -> dict:
    """Load data from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def clone_repository(git_url: str, target_dir: str) -> str:
    """
    Clone a git repository to a target directory.
    
    Args:
        git_url: URL of the git repository
        target_dir: Directory where to clone the repo
        
    Returns:
        Path to the cloned repository
    """
    target_path = Path(target_dir)
    
    # Clean up if exists and not empty
    if target_path.exists() and any(target_path.iterdir()):
        # Check if it's already a git repo
        if (target_path / ".git").exists():
             return str(target_path)
        else:
             raise ValueError(f"Target directory {target_dir} exists and is not empty/not a git repo.")

    try:
        subprocess.run(
            ["git", "clone", git_url, str(target_path)],
            check=True,
            capture_output=True,
            text=True
        )
        return str(target_path)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to clone repository: {e.stderr}")
