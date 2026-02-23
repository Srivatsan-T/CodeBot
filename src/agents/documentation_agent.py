"""Documentation Agent - Generates documentation for code symbols and modules."""

import json
from pathlib import Path
from datetime import datetime, timezone
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent, build_symbol_index, expand_with_dependencies
from agents.planner_agent import PlannerOutput


# Retrieval constants
SCOPE_ELIGIBILITY = {
    "symbol": {"function", "class", "variable"},
    "module": {"module"},
    "system": {"module"},
}

RECALL_K_BY_SCOPE = {
    "symbol": 10,
    "module": 30,
    "system": 50,
}

FINAL_K_BY_SCOPE = {
    "symbol": 15,
    "module": 10,
    "system": 10,
}


def retrieve_with_scope(*, query: str, scope: str, index, metadata, embedding_model_name: str):
    """Retrieve with scope-based filtering."""
    # Import here to avoid circular dependency
    from core.embedding import search
    
    candidates = search(
        query=query,
        vectorstore=index,
        metadata=metadata,
        EMBEDDING_MODEL_NAME=embedding_model_name,
        k=RECALL_K_BY_SCOPE.get(scope, 30),
    )
    
    # Scope eligibility filter
    eligible = [
        r for r in candidates
        if r["symbol"]["symbol_type"] in SCOPE_ELIGIBILITY.get(scope, set())
    ]
    
    if not eligible:
        return []
    
    return eligible[:FINAL_K_BY_SCOPE.get(scope, 5)]


class DocumentationAgent:
    """Agent for generating code documentation."""
    
    def __init__(
        self,
        llm: ChatOpenAI,
        system_prompt: str,
        index,
        metadata,
        embedding_model_name: str
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.index = index
        self.metadata = metadata
        self.embedding_model_name = embedding_model_name
        self.symbol_index = build_symbol_index(self.metadata)
    
    def run(self, query: str, plan: PlannerOutput) -> str:
        """Generate documentation based on query and plan."""
        if plan.intent != "documentation":
            raise ValueError("DocumentationAgent invoked for non-documentation intent")
        
        retrieved = retrieve_with_scope(
            query=query,
            scope=plan.scope,
            index=self.index,
            metadata=self.metadata,
            embedding_model_name=self.embedding_model_name,
        )
        
        evidence = json.dumps(
            [expand_with_dependencies(item["symbol"], self.symbol_index) for item in retrieved],
            indent=2,
        )
        
        
        return self._ask_llm(query, evidence)
    
    def _ask_llm(self, query: str, evidence: str) -> str:
        """Ask LLM to generate documentation."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", """
User request:
{query}

Evidence:
{evidence}
"""),
        ])
        
        chain = prompt | self.llm
        
        response = chain.invoke({
            "query": query,
            "evidence": evidence
        })
        
        return response.content


def documentation_agent(
    llm_config_path: str,
    plan: PlannerOutput,
    query: str,
    index,
    metadata,
    embedding_model_name: str,
    markdown_path: str,
    module_name: str,
    api_key: str = None
) -> str:
    """
    Documentation agent using LangChain.
    
    Args:
        llm_config_path: Path to LLM config
        plan: Planner output
        query: User query
        index: Vector store
        metadata: Metadata list
        embedding_model_name: Embedding model name
        markdown_path: Path to save documentation
        module_name: Name of the module being documented (used for filename)
        api_key: Optional API key override
        
    Returns:
        Generated documentation content
    """
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "documentation", api_key)
    system_prompt = config["agents"][config["active_models"]["documentation"]]["system_prompt"]
    
    doc_agent = DocumentationAgent(
        llm=llm,
        system_prompt=system_prompt,
        index=index,
        metadata=metadata,
        embedding_model_name=embedding_model_name
    )
    
    content = doc_agent.run(query, plan)
    
    path = Path(f"{markdown_path}/{module_name}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    
    return content
