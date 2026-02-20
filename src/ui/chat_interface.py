"""Chat interface component for Streamlit app."""

import streamlit as st
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from agents import planner_agent, documentation_agent
from agents.module_summary_agent import (
    load_or_build_module_summaries,
    generate_codebase_overview
)
from config import Config


def render_chat_interface():
    """Render the chat interface with message history."""
    
    st.header("💬 Chat with CodeBot")
    
    # Check if codebase is loaded
    if not st.session_state.current_codebase:
        st.warning("⚠️ Please upload a codebase first in the Codebase Manager!")
        return
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Ask about your codebase..."):
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": prompt})
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Process with agent
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    config = Config()
                    
                    # Plan the request
                    plan = planner_agent(config.llm_config_path, prompt)
                    
                    # Check if clarification is needed (low confidence)
                    if plan.confidence < 0.7:
                        # Ask user to clarify
                        clarification_msg = f"🤔 I'm not entirely sure if you want:\n\n"
                        clarification_msg += "**A) QA** - A direct answer to your question\n"
                        clarification_msg += "**B) Documentation** - Generate comprehensive written documentation\n\n"
                        
                        if plan.notes:
                            clarification_msg += f"*Note: {plan.notes}*\n\n"
                        
                        clarification_msg += "Please clarify by typing 'A' for QA or 'B' for Documentation."
                        
                        st.markdown(clarification_msg)
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": clarification_msg
                        })
                        
                        # Store the pending plan for next message
                        st.session_state.pending_plan = {
                            "plan": plan,
                            "query": prompt
                        }
                        return
                    
                    # Check if we're responding to a clarification
                    if "pending_plan" in st.session_state:
                        user_choice = prompt.strip().upper()
                        if user_choice == 'A':
                            # User wants QA
                            plan = st.session_state.pending_plan["plan"]
                            plan.intent = "qa"
                            plan.confidence = 1.0
                            prompt = st.session_state.pending_plan["query"]
                        elif user_choice == 'B':
                            # User wants documentation
                            plan = st.session_state.pending_plan["plan"]
                            plan.intent = "documentation"
                            plan.confidence = 1.0
                            prompt = st.session_state.pending_plan["query"]
                        else:
                            # Invalid response, ask again
                            st.warning("Please respond with 'A' for QA or 'B' for Documentation.")
                            return
                        
                        # Clear pending plan
                        del st.session_state.pending_plan
                    
                    # Handle based on intent
                    if plan.intent == "documentation":
                        # Check if it's full codebase request
                        if plan.scope == "system":
                            # Generate module summaries
                            with st.status("Generating codebase overview...", expanded=True) as status:
                                st.write("📝 Analyzing modules...")
                                summaries = load_or_build_module_summaries(
                                    config.llm_config_path,
                                    st.session_state.metadata,
                                    config.module_summary_path
                                )
                                
                                st.write("📚 Creating overview document...")
                                overview = generate_codebase_overview(
                                    summaries,
                                    config.docs_dir
                                )
                                
                                status.update(label="✅ Overview generated!", state="complete")
                            
                            response = overview
                        else:
                            # Use existing documentation agent
                            response = documentation_agent(
                                config.llm_config_path,
                                plan,
                                prompt,
                                st.session_state.vectorstore,
                                st.session_state.metadata,
                                config.embedding_model,
                                config.docs_dir
                            )
                    
                    elif plan.intent == "diagram":
                        response = "📊 Please switch to the **Architecture Diagram** view to see interactive visualizations!"
                    
                    elif plan.intent == "qa":
                        # Use QA agent for answering questions
                        from agents import qa_agent
                        
                        response = qa_agent(
                            config.llm_config_path,
                            plan,
                            prompt,
                            st.session_state.vectorstore,
                            st.session_state.metadata,
                            config.embedding_model
                        )
                    
                    else:
                        response = f"Intent '{plan.intent}' is not yet fully implemented."
                    
                    # Display response
                    st.markdown(response)
                    
                    # Add to message history
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response
                    })
                
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_msg
                    })
    
    # Helpful suggestions
    if len(st.session_state.messages) == 0:
        st.info("💡 **Try asking:**\n"
                "**Documentation:**\n"
                "- Document the authentication module\n"
                "- Document the entire codebase\n\n"
                "**Questions (QA):**\n"
                "- How does user authentication work?\n"
                "- What does the UserService class do?\n"
                "- Where is the login function defined?\n"
                "- How are database connections handled?\n\n"
                "**Diagrams:**\n"
                "- Show me the architecture diagram")

