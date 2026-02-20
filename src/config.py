"""Configuration management for the codebase intelligence system."""

from pathlib import Path
from dataclasses import dataclass


@dataclass
class Config:
    """Configuration for the codebase intelligence system."""
    
    # Project Identity
    project_name: str = "fastapi-realworld-example-app"
    
    # Paths
    base_dir: Path = Path(__file__).parent
    artifacts_dir: Path = base_dir / 'artifacts'
    
    # These will be updated in __post_init__ based on project_name
    symbols_path: str = ''
    vector_dir: str = ''
    metadata_path: str = ''
    module_summary_path: str = ''
    docs_dir: str = ''
    arch_dir: str = ''
    arch_dot: str = ''
    subgraph_dot: str = ''
    
    # LLM configuration (shared)
    llm_config_path: str = 'llm_config.json'
    
    # Embedding model
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    
    def __post_init__(self):
        """Ensure paths are absolute and scoped to the project."""
        project_artifacts = self.artifacts_dir / self.project_name
        
        # Define project-specific paths
        self.symbols_path = str(project_artifacts / 'symbols_final.json')
        self.vector_dir = str(project_artifacts / 'vector/')
        self.metadata_path = str(project_artifacts / 'vector/metadata.json')
        self.module_summary_path = str(project_artifacts / 'module_summary.json')
        self.docs_dir = str(project_artifacts / 'docs/')
        self.arch_dir = str(project_artifacts / 'arch/')
        self.arch_dot = str(project_artifacts / 'arch/arch.dot')
        self.subgraph_dot = str(project_artifacts / 'arch/subgraph.dot')

        # Shared config
        if not Path(self.llm_config_path).is_absolute():
            self.llm_config_path = str(self.base_dir / self.llm_config_path)
            
        # Create directories
        project_artifacts.mkdir(parents=True, exist_ok=True)
        Path(self.vector_dir).mkdir(parents=True, exist_ok=True)
        Path(self.docs_dir).mkdir(parents=True, exist_ok=True)
        Path(self.arch_dir).mkdir(parents=True, exist_ok=True)

