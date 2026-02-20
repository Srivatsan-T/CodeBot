import streamlit as st
import os
import time
from pathlib import Path
from config import Config
from agents import (
    planner_agent,
    module_selector_agent,
    symbol_selector_agent,
    load_or_build_module_summaries
)
from core.embedding import load_or_create_index
from core.parser import parse_repository
from arch import graph, module_subgraph, symbol_subgraph
import json



from utils import load_projects, save_project, get_config_for_project, clone_repository

# Page Config
st.set_page_config(
    page_title="Architecture Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize Session State
if "messages" not in st.session_state:
    st.session_state.messages = []
if "config" not in st.session_state:
    st.session_state.config = None
if "active_project" not in st.session_state:
    st.session_state.active_project = None

def initialize_system(project_name, repo_path):
    """Initialize the AI system with the given repository."""
    status_container = st.status(f"Initializing {project_name}...", expanded=True)
    
    try:
        # Create config for this project
        config = get_config_for_project(project_name)
        
        # 1. Parse Repository
        status_container.write("🔍 Parsing repository structure...")
        metadata = parse_repository(repo_path, config.symbols_path)
        
        # 2. Build/Load Vector Index
        status_container.write("📚 Building vector index...")
        from core.retrieval import generate_retrievals
        retrievals = generate_retrievals(metadata)
        
        vectorstore, metadata_list = load_or_create_index(
            retrievals,
            config.embedding_model,
            config.vector_dir
        )
        
        # 3. Load Module Summaries
        status_container.write("📑 Loading module summaries...")
        
        # Get API Key from session state or env (handled in utils)
        api_key = st.session_state.get("api_key")
        
        module_summaries = load_or_build_module_summaries(
            config.llm_config_path,
            metadata_list,
            config.module_summary_path,
            api_key=api_key
        )
        
        # 4. Pre-compute Full Graph
        status_container.write("🕸️ Building dependency graph...")
        symbol_graph, module_graph = graph(metadata_list, config.arch_dot)
        
        # Save project to registry
        save_project(project_name, repo_path)
        
        # Store in session state
        st.session_state.config = config
        st.session_state.metadata = metadata_list
        st.session_state.vectorstore = vectorstore
        st.session_state.module_summaries = module_summaries
        st.session_state.symbol_graph = symbol_graph
        st.session_state.module_graph = module_graph
        st.session_state.repo_path = repo_path
        st.session_state.active_project = project_name
        
        status_container.update(label="System Ready!", state="complete", expanded=False)
        time.sleep(1)
        st.rerun()
        
    except Exception as e:
        status_container.update(label="Initialization Failed", state="error", expanded=True)
        st.error(f"Error: {str(e)}")
        raise e

def process_query(query):
    """Process user query using planner and appropriate agents."""
    config = st.session_state.config
    
    api_key = st.session_state.get("api_key")

    # 1. Planning
    with st.spinner("Thinking..."):
        plan = planner_agent(config.llm_config_path, query, api_key=api_key)
    
    response = {
        "intent": plan.intent,
        "content": "",
        "artifacts": []
    }
    
    # 2. Execution
    if not plan.is_valid:
        response["content"] = plan.validation_error or "I can't help with that request as it seems unrelated to the codebase."
        return response

    if plan.intent == "diagram":
        with st.spinner("Generating Architecture Diagram..."):
            if plan.scope == "symbol":
                # Function-level flow
                selected = symbol_selector_agent(
                    config.llm_config_path,
                    query,
                    st.session_state.vectorstore,
                    st.session_state.metadata,
                    config.embedding_model,
                    api_key=api_key
                )
                
                symbol_subgraph(
                    st.session_state.symbol_graph,
                    selected['selected_symbols'],
                    selected['flow_path'],
                    config.subgraph_dot,
                    st.session_state.metadata
                )
                response["content"] = f"Generated **function-level** flow diagram based on your request.\n\n**Flow Type:** {selected['flow_type']}\n**Steps:** {len(selected['flow_path'])}"
                response["artifacts"].append({"type": "graphviz", "path": config.subgraph_dot})
                
            elif plan.scope == "module":
                # Module-level flow
                selected_modules = module_selector_agent(
                    config.llm_config_path,
                    query,
                    st.session_state.module_summaries,
                    st.session_state.metadata,
                    api_key=api_key
                )
                
                module_subgraph(
                    st.session_state.module_graph,
                    st.session_state.module_summaries,
                    selected_modules,
                    config.subgraph_dot
                )
                response["content"] = f"Generated **module-level** architecture diagram involving {len(selected_modules['selected_modules'])} modules."
                response["artifacts"].append({"type": "graphviz", "path": config.subgraph_dot})
                
            else: # System scope
                response["content"] = "Here is the high-level system architecture."
                response["artifacts"].append({"type": "graphviz", "path": config.arch_dot})

    elif plan.intent == "documentation":
        with st.spinner("Generating Documentation..."):
            from agents import documentation_agent, generate_codebase_overview
            print(plan.scope)
            if plan.scope == "system":
                # Full system overview
                doc = generate_codebase_overview(
                    config.llm_config_path,
                    st.session_state.module_summaries
                )
                response["content"] = doc
            else:
                # Targeted documentation
                doc_path = config.docs_dir
                doc = documentation_agent(
                    config.llm_config_path,
                    plan,
                    query,
                    st.session_state.vectorstore,
                    st.session_state.metadata,
                    config.embedding_model,
                    doc_path,
                    api_key=api_key
                )
                response["content"] = doc

    elif plan.intent == "qa":
        with st.spinner("Analyzing codebase..."):
            from agents import qa_agent
            answer = qa_agent(
                config.llm_config_path,
                plan,
                query,
                st.session_state.vectorstore,
                st.session_state.metadata,
                config.embedding_model,
                api_key=api_key
            )
            response["content"] = answer
    
    else:
        response["content"] = f"I understood your intent as '{plan.intent}' but I'm not sure how to handle it yet."
        
    return response

# --- Sidebar: Project Selection ---
with st.sidebar:
    st.title("📂 Projects")
    projects = load_projects()
    project_names = list(projects.keys())
    
    # Selection logic
    selected_option = st.selectbox(
        "Select Project",
        ["➕ New Project"] + project_names,
        index=0 if not st.session_state.active_project else (project_names.index(st.session_state.active_project) + 1 if st.session_state.active_project in project_names else 0)
    )
    
    # API Key Input
    st.divider()
    api_key_input = st.text_input("🔑 Bedrock API Key", type="password", help="Enter your AWS Access Key ID if not set in environment.")
    if api_key_input:
        st.session_state.api_key = api_key_input
    
    if selected_option == "➕ New Project":
        if st.session_state.active_project is not None:
            st.session_state.active_project = None
            st.session_state.config = None
            st.rerun()
    else:
        # Load existing project if changed
        if st.session_state.active_project != selected_option:
            # Load project data (Simplified loading - ideally we'd cache this)
            repo_path = projects[selected_option]
            # Verify path exists
            if os.path.exists(repo_path):
                initialize_system(selected_option, repo_path)
            else:
                st.error(f"Repository path not found: {repo_path}")

# --- Main Interface ---

if not st.session_state.active_project:
    # Setup Screen
    st.title("🧠 Architecture Intelligence")
    st.markdown("### 🚀 Create New Project")
    
    with st.form("setup_form"):
        project_name = st.text_input("Project Name", placeholder="e.g., My Web App")
        
        # Tabs for Source Selection
        tab_local, tab_git = st.tabs(["📁 Local Path", "🌐 Clone from URL"])
        
        with tab_local:
            repo_path_local = st.text_input("Repository Path", placeholder="C:/path/to/your/repo")
            
        with tab_git:
            git_url = st.text_input("Git Repository URL", placeholder="https://github.com/username/repo.git")
            
        submitted = st.form_submit_button("Initialize Project", type="primary")
        
        if submitted:
            repo_path = repo_path_local
            
            # Handle Git Clone
            if git_url and not repo_path_local:
                try:
                    with st.spinner(f"Cloning {git_url}..."):
                        # Clone to a 'cloned_repos' directory
                        base_clone_dir = Path("cloned_repos").absolute()
                        # Sanitize project name for directory
                        safe_name = "".join(c if c.isalnum() else "_" for c in project_name).lower()
                        target_dir = base_clone_dir / safe_name
                        
                        cloned_path = clone_repository(git_url, str(target_dir))
                        repo_path = str(cloned_path)
                        st.success(f"Successfully cloned to: {repo_path}")
                except Exception as e:
                    st.error(f"Clone failed: {str(e)}")
                    st.stop()
            
            if project_name and repo_path and os.path.exists(repo_path):
                initialize_system(project_name, repo_path)
            else:
                st.error("Please enter a valid project name and repository path/URL.")

else:
    # Authenticated View
    st.title(f"🧠 {st.session_state.active_project}")
    
    tab_dashboard, tab_chat, tab_services = st.tabs(["📊 Dashboard", "💬 Chat", "⚙️ Services"])
    
    with tab_dashboard:
        st.markdown("### System Architecture")
        config = st.session_state.config
        
        # Display System Diagram
        if os.path.exists(config.arch_dot):
            try:
                with open(config.arch_dot, "r", encoding="utf-8") as f:
                    dot_source = f.read()
                st.graphviz_chart(dot_source, use_container_width=True)
            except Exception as e:
                st.error(f"Could not load architecture diagram: {e}")
        else:
            st.info(f"Architecture diagram not found at: `{config.arch_dot}`")
            st.warning("Try re-initializing the project or check permissions.")
            
        # Stats
        st.markdown("### Repository Stats")
        if "metadata" in st.session_state:
            stats_cols = st.columns(3)
            with stats_cols[0]:
                st.metric("Total Symbols", len(st.session_state.metadata))
            with stats_cols[1]:
                module_count = len(set(s['file_path'] for s in st.session_state.metadata))
                st.metric("Modules", module_count)
            with stats_cols[2]:
                st.metric("Last Indexed", "Just now")

    with tab_chat:
        st.markdown("### 💬 Chat with your Codebase")
        
        # Display History
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                if msg.get("intent") == "documentation":
                    st.markdown("### 📄 Generated Documentation")
                    with st.expander("View Full Documentation", expanded=False):
                        st.markdown(msg["content"])
                    st.download_button(
                        label="Download Markdown",
                        data=msg["content"],
                        file_name=f"documentation_{int(time.time())}.md",
                        mime="text/markdown",
                        key=f"dl_{time.time()}_{msg['content'][:10]}"
                    )
                else:
                    st.markdown(msg["content"])
                    
                if "artifacts" in msg:
                    for artifact in msg["artifacts"]:
                        if artifact["type"] == "graphviz":
                            try:
                                with open(artifact["path"], "r", encoding="utf-8") as f:
                                    dot_source = f.read()
                                st.graphviz_chart(dot_source)
                            except Exception as e:
                                st.error(f"Failed to render diagram: {e}")
        
        # Input
        if prompt := st.chat_input("Ask about architecture, flows, or code..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
                
            response_data = process_query(prompt)
            
            with st.chat_message("assistant"):
                if response_data.get("intent") == "documentation":
                    st.markdown("### 📄 Generated Documentation")
                    with st.expander("View Full Documentation", expanded=True):
                        st.markdown(response_data["content"])
                    st.download_button(
                        label="Download Markdown",
                        data=response_data["content"],
                        file_name=f"documentation_{int(time.time())}.md",
                        mime="text/markdown",
                        key=f"dl_new_{int(time.time())}"
                    )
                else:
                    st.markdown(response_data["content"])
                    
                if response_data["artifacts"]:
                    for artifact in response_data["artifacts"]:
                        if artifact["type"] == "graphviz":
                            try:
                                with open(artifact["path"], "r", encoding="utf-8") as f:
                                    dot_source = f.read()
                                st.graphviz_chart(dot_source)
                            except Exception as e:
                                st.error(f"Failed to render diagram: {e}")
            
            st.session_state.messages.append({
                "role": "assistant",
                "content": response_data["content"],
                "artifacts": response_data["artifacts"],
                "intent": response_data.get("intent")
            })

    with tab_services:
        st.markdown("### 🔌 Services & Integrations")
        
        st.info("Continuous Documentation is available via the Webhook Server.")
        
        st.markdown("#### 1. GitHub Webhook Setup")
        st.markdown(f"""
        To enable automatic documentation updates on `git push`:
        1. Run the webhook server: `uv run python webhook_server.py`
        2. Expose port 8000 to the internet (e.g., `ngrok http 8000`)
        3. Add a Webhook in your GitHub Repo Settings:
           - **Payload URL**: `https://<your-ngrok-url>/webhook`
           - **Content type**: `application/json`
           - **Secret**: `my-secret-token` (or configure in `.env`)
        """)
        
        st.divider()
        
        st.markdown("#### 2. Manual Trigger")
        st.write("Generate comprehensive documentation for all modules in this project.")
        
        if st.button("📚 Generate Full Documentation", type="primary"):
            try:
                from core.pipeline import generate_full_documentation
                with st.spinner("Generating documentation for all modules... This may take a while."):
                    docs = generate_full_documentation(st.session_state.active_project)
                    st.success(f"Successfully generated documentation for {len(docs)} modules!")
                    st.balloons()
            except Exception as e:
                st.error(f"Failed to generate documentation: {e}")
