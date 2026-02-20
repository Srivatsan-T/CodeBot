"""QA Agent - Answers specific questions about the codebase using RAG."""

import json
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent, build_symbol_index, expand_with_dependencies
from agents.planner_agent import PlannerOutput


# Retrieval constants - same as documentation agent
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


class QAAgent:
    """Agent for answering questions about the codebase."""
    
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
        """Answer question based on query and plan."""
        if plan.intent != "qa":
            raise ValueError("QAAgent invoked for non-qa intent")
        
        # Retrieve relevant symbols
        retrieved = retrieve_with_scope(
            query=query,
            scope=plan.scope,
            index=self.index,
            metadata=self.metadata,
            embedding_model_name=self.embedding_model_name,
        )
        
        if not retrieved:
            return "I couldn't find any relevant information in the codebase to answer your question."
        
        # Expand with dependencies for context
        evidence = json.dumps(
            [expand_with_dependencies(item["symbol"], self.symbol_index) for item in retrieved],
            indent=2,
        )
        
        return self._ask_llm(query, evidence)
    
    def _ask_llm(self, query: str, evidence: str) -> str:
        """Ask LLM to answer the question."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", """
User question:
{query}

Relevant code evidence:
{evidence}
"""),
        ])
        
        chain = prompt | self.llm
        
        response = chain.invoke({
            "query": query,
            "evidence": evidence
        })
        
        return response.content


def qa_agent(
    llm_config_path: str,
    plan: PlannerOutput,
    query: str,
    index,
    metadata,
    embedding_model_name: str,
    api_key: str = None
) -> str:
    """
    QA agent using LangChain.
    
    Args:
        llm_config_path: Path to LLM config
        plan: Planner output
        query: User question
        index: Vector store
        metadata: Metadata list
        embedding_model_name: Embedding model name
        api_key: Optional API key override
        
    Returns:
        Answer to the question
    """
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "qa", api_key)
    system_prompt = config["agents"][config["active_models"]["qa"]]["system_prompt"]
    
    agent = QAAgent(
        llm=llm,
        system_prompt=system_prompt,
        index=index,
        metadata=metadata,
        embedding_model_name=embedding_model_name
    )
    
    answer = agent.run(query, plan)
    
    return answer
