"""Symbol Selector Agent - Selects functions/classes for flow diagrams."""

import json
from typing import List, Dict
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

import sys
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent, expand_with_dependencies


class SymbolSelectionOutput(BaseModel):
    """Structured output for Symbol Selector Agent."""
    selected_symbols: List[str] = Field(
        description="UIDs of selected functions/classes in the flow"
    )
    flow_path: List[str] = Field(
        description="Ordered list of symbol UIDs showing execution sequence"
    )
    flow_type: str = Field(
        description="Type of flow: 'sequential', 'branching', or 'cyclic'"
    )
    entry_point: str = Field(
        description="UID of the function/class where the flow starts"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class SymbolSelectorAgent:
    """Agent for selecting functions/classes for flow diagrams using RAG."""
    
    def __init__(
        self,
        llm: ChatOpenAI,
        system_prompt: str,
        index,
        metadata: List[dict],
        embedding_model_name: str,
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.structured_llm = llm.with_structured_output(SymbolSelectionOutput)
        self.index = index
        self.metadata = metadata
        self.embedding_model_name = embedding_model_name
        self.symbol_index = build_symbol_index(metadata)
    
    def select(self, query: str) -> dict:
        """Select symbols based on flow query using RAG."""
        # Step 1: Retrieve relevant functions/classes using RAG
        retrieved = self._retrieve_relevant_symbols(query)
        
        if not retrieved:
            return {
                "selected_symbols": [],
                "flow_path": [],
                "flow_type": "unknown",
                "entry_point": "",
                "confidence": 0.0
            }
        
        # Step 2: Build context with retrieved symbols and their relationships
        context = self._build_symbol_context(retrieved)
        
        # Step 3: Use LLM to select flow path from retrieved symbols
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", """
User flow query:
{query}

Relevant functions and classes (retrieved via semantic search):
{context}
"""),
        ])
        
        chain = prompt | self.structured_llm
        
        result = chain.invoke({
            "query": query,
            "context": json.dumps(context, indent=2)
        })
        
        return result.model_dump()
    
    def _retrieve_relevant_symbols(self, query: str, k: int = 20) -> List[dict]:
        """Retrieve relevant functions/classes using vector search."""
        from core.embedding import search
        
        # Search for relevant symbols
        candidates = search(
            query=query,
            vectorstore=self.index,
            metadata=self.metadata,
            EMBEDDING_MODEL_NAME=self.embedding_model_name,
            k=k,
        )
        
        # Filter to only functions and classes
        relevant = [
            r for r in candidates
            if r["symbol"]["symbol_type"] in {"function", "class"}
        ]
        
        return relevant[:15]  # Limit to top 15 for context
    
    def _build_symbol_context(self, retrieved: List[dict]) -> List[dict]:
        """Build context from retrieved symbols with their relationships."""
        context = []
        for item in retrieved:
            symbol = item["symbol"]
            
            # Expand with dependencies for richer context
            expanded = expand_with_dependencies(symbol, self.symbol_index)
            
            context.append({
                "uid": symbol['uid'],
                "name": symbol['qualified_name'],
                "type": symbol['symbol_type'],
                "module": symbol['file_path'],
                "calls": [dep for dep in symbol.get('depends_on', []) if dep in self.symbol_index][:5],
                "called_by": [user for user in symbol.get('used_by', []) if user in self.symbol_index][:5],
                "relevance_score": item.get("score", 0.0)
            })
        
        return context


def symbol_selector_agent(
    llm_config_path: str,
    query: str,
    index,
    metadata: List[dict],
    embedding_model_name: str,
) -> dict:
    """Symbol selector agent using RAG and LangChain."""
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "symbol_selector")
    system_prompt = config["agents"][config["active_models"]["symbol_selector"]]["system_prompt"]
    
    agent = SymbolSelectorAgent(
        llm=llm,
        system_prompt=system_prompt,
        index=index,
        metadata=metadata,
        embedding_model_name=embedding_model_name,
    )
    
    return agent.select(query)

