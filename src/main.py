"""Main entry point for the codebase intelligence system."""

from config import Config
from core.parser import parse_repository
from core.retrieval import generate_retrievals
from core.embedding import load_or_create_index
from agents import (
    planner_agent,
    documentation_agent,
    qa_agent,
    load_or_build_module_summaries,
    generate_codebase_overview,
    module_selector_agent
)
from arch import graph, module_subgraph


def main():
    """Main workflow for codebase intelligence."""
    config = Config()
    
    # User query - CHANGE THIS TO TEST DIFFERENT INTENTS
    # query = "Document the authentication.py module present in the app.api.dependencies directory"
    # query = "Give me the architecture diagram for the whole codebase"
    query = "How does user authentication work in this codebase?"
    
    # Parse repository (single step, outputs symbols_final.json)
    print("=" * 60)
    print("STEP 1: Parsing Repository")
    print("=" * 60)
    symbols_data = parse_repository(config.repo_name, config.symbols_path)
    
    # Generate retrievals and build vector store
    print("\n" + "=" * 60)
    print("STEP 2: Building Vector Store")
    print("=" * 60)
    retrievals = generate_retrievals(symbols_data)
    vectorstore, metadata = load_or_create_index(
        retrievals,
        config.embedding_model,
        config.vector_dir
    )
    
    # Load module summaries (needed for diagrams and system-level docs)
    print("\n" + "=" * 60)
    print("STEP 3: Loading Module Summaries")
    print("=" * 60)
    module_summaries = load_or_build_module_summaries(
        config.llm_config_path,
        metadata,
        config.module_summary_path
    )
    print(f"Loaded {len(module_summaries)} module summaries")
    
    # Plan the request
    print("\n" + "=" * 60)
    print("STEP 4: Planning Request")
    print("=" * 60)
    plan = planner_agent(config.llm_config_path, query)
    
    if not plan.is_valid:
        print(f"\nRequest Rejected: {plan.validation_error or 'Invalid request'}")
        return

    print(f"Intent: {plan.intent}")
    print(f"Scope: {plan.scope}")
    print(f"Confidence: {plan.confidence}")
    
    # Execute based on intent
    if plan.intent == "documentation":
        print("\n" + "=" * 60)
        print("STEP 5: Generating Documentation")
        print("=" * 60)
        
        # Check if it's full codebase documentation (system scope)
        if plan.scope == "system":
            
            print("\nCreating codebase overview...")
            doc = generate_codebase_overview(
                module_summaries,
                config.docs_dir
            )
            
            print("\nFull codebase documentation generated!")
            print(f"Preview:\n{doc[:500]}...")


        else:
            # Use regular documentation agent for module/symbol scope
            doc = documentation_agent(
                config.llm_config_path,
                plan,
                query,
                vectorstore,
                metadata,
                config.embedding_model,
                config.docs_dir
            )
            print("\nDocumentation generated successfully!")
            print(f"Preview:\n{doc[:500]}...")

    
    elif plan.intent == "qa":
        print("\n" + "=" * 60)
        print("STEP 5: Answering Question")
        print("=" * 60)
        answer = qa_agent(
            config.llm_config_path,
            plan,
            query,
            vectorstore,
            metadata,
            config.embedding_model
        )
        print("\nAnswer:")
        print("=" * 60)
        print(answer)
        print("=" * 60)
    
    elif plan.intent == "diagram":
        print("\n" + "=" * 60)
        print("STEP 5: Generating Architecture Diagram")
        print("=" * 60)
        
        # Build graphs
        symbol_graph, module_graph = graph(metadata, config.arch_dot)
        
        if plan.scope == "symbol":
            # Function-level flow diagram
            from arch import symbol_subgraph
            from agents import symbol_selector_agent
            
            print("\nSelecting functions/classes for flow (using RAG)...")
            selected = symbol_selector_agent(
                config.llm_config_path,
                query,
                vectorstore,
                metadata,
                config.embedding_model
            )
            print(f"Flow type: {selected['flow_type']}")
            print(f"Entry point: {selected['entry_point']}")
            print(f"Flow path: {len(selected['flow_path'])} steps")
            
            # Generate function-level diagram
            symbol_subgraph(
                symbol_graph,
                selected['selected_symbols'],
                selected['flow_path'],
                config.subgraph_dot,
                metadata
            )
            print(f"\nFunction-level flow diagram saved to {config.subgraph_dot}")
        
        elif plan.scope == "module":
            # Module-level architecture diagram
            print("\nSelecting modules...")
            selected_modules = module_selector_agent(
                config.llm_config_path,
                query,
                module_summaries,
                metadata
            )
            print(f"Selected modules: {selected_modules['selected_modules']}")
            
            # Generate module-level diagram
            module_subgraph(
                module_graph,
                module_summaries,
                selected_modules,
                config.subgraph_dot
            )
            print(f"\nModule-level diagram saved to {config.subgraph_dot}")
        
        else:  # scope == "system"
            # Full architecture diagram (already generated)
            print(f"\nFull architecture diagram saved to {config.arch_dot}")
    
    else:
        print(f"\nIntent '{plan.intent}' not yet implemented")
    
    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
