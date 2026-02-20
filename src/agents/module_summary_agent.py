"""Module Summary Agent - Generates summaries for code modules."""

import json
from typing import List, Dict
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from tqdm import tqdm

import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent


class ModuleSummaryOutput(BaseModel):
    """Structured output for Module Summary Agent."""
    file_path: str
    uid: str
    purpose: str = Field(description="Primary purpose of this module in 1-2 sentences")
    responsibilities: List[str] = Field(description="3-5 key responsibilities or functions")
    key_components: List[str] = Field(description="Important classes, functions, or constants defined")
    dependencies: List[str] = Field(description="Key external modules or packages this module depends on")
    used_by: List[str] = Field(description="Other modules that import or use this module")
    role_in_system: str = Field(description="How this module fits into the overall architecture")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the summary accuracy")


class ModuleSummaryAgent:
    """Agent for generating module summaries."""
    
    def __init__(self, llm: ChatOpenAI, system_prompt: str):
        self.llm = llm
        self.system_prompt = system_prompt
        # We manually parse to handle markdown blocks
    
    def summarize_module(self, module_symbol: dict) -> dict:
        """Generate summary for a single module."""
        # We perform a targeted extraction to avoid schema confusion
        # We do NOT ask the LLM to echo file_path or uid
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt + "\n\nRespond with a SINGLE VALID JSON object containing specific summary fields: purpose, responsibilities, key_components, dependencies, used_by, role_in_system, confidence.\nDo NOT include file_path or uid in the generated JSON.\n\nIMPORTANT: Return raw JSON only. No markdown."),
            ("user", """
            Module metadata:
            {metadata}
            """),
        ])
        
        chain = prompt | self.llm
        
        response = chain.invoke({
            "metadata": json.dumps(module_symbol, indent=2)
        })
        
        # Robust Parsing Logic
        content = response.content.strip()
        
        # Strip markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        
        if content.endswith("```"):
            content = content[:-3]
            
        content = content.strip()
        
        try:
            data = json.loads(content)
            
            # Inject metadata fields that the LLM was not asked to generate
            data["file_path"] = module_symbol.get("file_path", "")
            data["uid"] = module_symbol.get("uid", "")
            
            # Validate against schema
            return ModuleSummaryOutput.model_validate(data).model_dump()
            
        except json.JSONDecodeError as e:
            # Fallback for empty or malformed JSON - return a partial error object
            print(f"JSON Parse Error: {e}")
            return {
                "file_path": module_symbol.get("file_path", ""),
                "uid": module_symbol.get("uid", ""),
                "purpose": "Error parsing summary response",
                "responsibilities": [],
                "key_components": [],
                "dependencies": [],
                "used_by": [],
                "role_in_system": "Unknown",
                "confidence": 0.0
            }
        except Exception as e:
            # Pydantic validation error or other
            print(f"Validation Error: {e}")
            return {
                "file_path": module_symbol.get("file_path", ""),
                "uid": module_symbol.get("uid", ""),
                "purpose": f"Validation error: {str(e)}",
                "responsibilities": [],
                "key_components": [],
                "dependencies": [],
                "used_by": [],
                "role_in_system": "Unknown",
                "confidence": 0.0
            }


def build_module_summaries(
    llm_config_path: str,
    metadata: List[dict],
    output_path: str,
    batch_size: int = 10,
    api_key: str = None
) -> Dict[str, dict]:
    """
    Build module summaries using LangChain with batch processing.
    
    Args:
        llm_config_path: Path to LLM configuration
        metadata: List of all symbols
        output_path: Path to save summaries JSON
        batch_size: Number of modules to process before saving checkpoint
        api_key: Optional API key override
        
    Returns:
        Dict mapping file_path to summary dict
    """
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "module_summary", api_key)
    system_prompt = config["agents"][config["active_models"]["module_summary"]]["system_prompt"]
    
    agent = ModuleSummaryAgent(llm=llm, system_prompt=system_prompt)
    
    # Filter for module-level symbols only
    modules = [s for s in metadata if s.get("symbol_type") == "module"]
    
    summaries = {}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating summaries for {len(modules)} modules...")
    
    # Process with progress bar and batch checkpointing
    for i, symbol in enumerate(tqdm(modules, desc="Module summaries")):
        file_path = symbol.get("file_path")
        
        try:
            summary = agent.summarize_module(symbol)
            summaries[file_path] = summary
            
            # Save checkpoint every batch_size modules
            if (i + 1) % batch_size == 0:
                output_path.write_text(
                    json.dumps(summaries, indent=2),
                    encoding="utf-8"
                )
                
        except Exception as e:
            print(f"\nError summarizing {file_path}: {e}")
            summaries[file_path] = {
                "file_path": file_path,
                "uid": symbol.get("uid", "unknown"),
                "purpose": "Error generating summary",
                "responsibilities": [],
                "key_components": [],
                "dependencies": [],
                "used_by": [],
                "role_in_system": "Unknown",
                "confidence": 0.0
            }
    
    # Final save
    output_path.write_text(
        json.dumps(summaries, indent=2),
        encoding="utf-8"
    )
    
    print(f"\n✓ Saved {len(summaries)} module summaries to {output_path}")
    return summaries


def load_or_build_module_summaries(
    llm_config_path: str,
    metadata: List[dict],
    output_path: str,
    api_key: str = None
) -> Dict[str, dict]:
    """Load or build module summaries."""
    output_path = Path(output_path)
    
    if output_path.exists():
        print(f"Loading cached module summaries from {output_path}")
        with output_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    
    print("Module summaries not found. Building…")
    summaries = build_module_summaries(
        llm_config_path=llm_config_path,
        metadata=metadata,
        output_path=str(output_path),
        api_key=api_key,
    )
    
    return summaries


def generate_codebase_overview(
    summaries: Dict[str, dict],
    output_dir: str
) -> str:
    """
    Generate a comprehensive codebase overview from module summaries.
    
    Args:
        summaries: Module summaries from load_or_build_module_summaries
        output_dir: Directory to save the overview markdown
        
    Returns:
        Overview text in markdown format
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Create markdown overview
    overview = "# Codebase Overview\n\n"
    overview += f"**Total Modules:** {len(summaries)}\n\n"
    overview += "This document provides a comprehensive overview of all modules in the codebase.\n\n"
    overview += "---\n\n"
    overview += "## Module Summaries\n\n"
    
    for file_path, summary in sorted(summaries.items()):
        module_name = Path(file_path).stem
        
        # Extract structured fields
        purpose = summary.get("purpose", "No purpose description available")
        responsibilities = summary.get("responsibilities", [])
        key_components = summary.get("key_components", [])
        dependencies = summary.get("dependencies", [])
        used_by = summary.get("used_by", [])
        role = summary.get("role_in_system", "Role not specified")
        
        # Format module section
        overview += f"### `{module_name}`\n\n"
        overview += f"**File:** `{file_path}`  \n"
        overview += f"**UID:** `{summary.get('uid', 'unknown')}`\n\n"
        
        overview += f"**Purpose:** {purpose}\n\n"
        
        if responsibilities:
            overview += "**Responsibilities:**\n"
            for resp in responsibilities:
                overview += f"- {resp}\n"
            overview += "\n"
        
        if key_components:
            overview += "**Key Components:**\n"
            for comp in key_components:
                overview += f"- `{comp}`\n"
            overview += "\n"
        
        if dependencies:
            overview += "**Dependencies:** " + ", ".join(f"`{d}`" for d in dependencies) + "\n\n"
        
        if used_by:
            overview += "**Used By:** " + ", ".join(f"`{u}`" for u in used_by) + "\n\n"
        
        overview += f"**Role in System:** {role}\n\n"
        overview += "---\n\n"
    
    # Save overview
    overview_file = output_path / "codebase_overview.md"
    with overview_file.open("w", encoding="utf-8") as f:
        f.write(overview)
    
    print(f"✓ Saved codebase overview to {overview_file}")
    return overview
