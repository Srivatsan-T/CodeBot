"""Module Selector Agent - Selects relevant modules for architecture diagrams."""

import json
from typing import List, Dict, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent, normalize_edges


class ModuleSelectionOutput(BaseModel):
    """Structured output for Module Selector Agent."""
    selected_modules: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    notes: Optional[str] = None


class ModuleSelectorAgent:
    """Agent for selecting relevant modules for diagrams."""
    
    def __init__(
        self,
        llm: ChatOpenAI,
        system_prompt: str,
        module_summaries: Dict[str, dict],
        metadata: List[dict],
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.structured_llm = llm.with_structured_output(ModuleSelectionOutput)
        self.module_summaries = module_summaries
        self.module_edges = normalize_edges(self.build_module_edges(metadata))
    
    def select(self, query: str) -> dict:
        """Select modules based on query."""
        context = {
            "modules": self._compact_summaries(),
            "dependencies": self.module_edges,
        }
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", """
User scenario:
{query}

Architecture context:
{context}
"""),
        ])
        
        chain = prompt | self.structured_llm
        
        result = chain.invoke({
            "query": query,
            "context": json.dumps(context, indent=2)
        })
        
        return result.model_dump()
    
    def _compact_summaries(self) -> Dict[str, dict]:
        """Reduce summaries to LLM-relevant fields only."""
        compact = {}
        for uid, summary in self.module_summaries.items():
            compact[uid] = {
                "purpose": summary.get("purpose"),
                "responsibilities": summary.get("responsibilities", []),
                "role_in_system": summary.get("role_in_system"),
            }
        return compact
    
    def build_module_edges(self, metadata) -> list:
        """Build directed module-to-module dependency edges."""
        modules = {
            s["qualified_name"]
            for s in metadata
            if s["symbol_type"] == "module"
        }
        
        edges = []
        
        for symbol in metadata:
            if symbol["symbol_type"] != "module":
                continue
            
            src = symbol["qualified_name"]
            
            for dep in symbol["depends_on"]:
                if dep in modules:
                    edges.append({
                        "from": src,
                        "to": dep,
                        "type": "depends_on"
                    })
        
        return edges


def module_selector_agent(
    llm_config_path: str,
    query: str,
    module_summaries: dict,
    metadata: List[dict],
) -> dict:
    """Module selector agent using LangChain."""
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "module_selector")
    system_prompt = config["agents"][config["active_models"]["module_selector"]]["system_prompt"]
    
    agent = ModuleSelectorAgent(
        llm=llm,
        system_prompt=system_prompt,
        module_summaries=module_summaries,
        metadata=metadata,
    )
    
    return agent.select(query)
