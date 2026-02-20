"""Planner Agent - Classifies user requests into intents and scopes."""

from typing import Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from utils import load_config, create_llm_for_agent


class PlannerOutput(BaseModel):
    """Structured output for the Planner Agent."""
    is_valid: bool = Field(
        description="Whether the request is related to the codebase/software engineering. Set false for general chitchat/irrelevant queries."
    )
    validation_error: Optional[str] = Field(
        default=None,
        description="Polite refusal message if is_valid is false"
    )
    intent: Literal["qa", "documentation", "diagram", "none"] = Field(
        description="The type of request: qa, documentation, diagram, or none (if invalid)"
    )
    scope: Literal["symbol", "module", "system", "none"] = Field(
        description="The scope of the request: symbol, module, system, or none (if invalid)"
    )
    needs_dependencies: bool = Field(
        description="Whether dependency information is needed"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score between 0 and 1"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes about the classification"
    )


def planner_agent(llm_config_path: str, query: str) -> PlannerOutput:
    """
    Planner agent using LangChain structured outputs.
    
    Args:
        llm_config_path: Path to LLM config JSON
        query: User query
        
    Returns:
        PlannerOutput with classification
    """
    config = load_config(llm_config_path)
    llm = create_llm_for_agent(config, "planner")
    
    from langchain_core.output_parsers import PydanticOutputParser
    
    # Create parser
    parser = PydanticOutputParser(pydantic_object=PlannerOutput)
    
    # Get system prompt from config
    system_prompt = config["agents"]["planner_bedrock"]["system_prompt"]
    
    # Create prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt + "\n\n{format_instructions}"),
        ("user", 'User request:\n"{query}"'),
    ])
    
    # Create chain
    chain = prompt | llm | parser
    
    # Invoke
    result = chain.invoke({
        "query": query, 
        "format_instructions": parser.get_format_instructions()
    })
    
    return result
