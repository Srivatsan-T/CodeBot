"""Codebase manager component for uploading and indexing codebases."""

import streamlit as st
from pathlib import Path
import zipfile
import tempfile
import shutil
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import Config
from core.parser import parse_repository
from core.retrieval import generate_retrievals
from core.embedding import load_or_create_index


def render_codebase_manager():
    """Render the codebase upload and management interface."""
    
    st.header("📁 Codebase Manager")
    
    config = Config()
    
    # Current codebase info
    if st.session_state.current_codebase:
        st.success(f"✅ Currently loaded: **{st.session_state.current_codebase}**")
        
        if st.session_state.metadata:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Symbols", len(st.session_state.metadata))
            with col2:
                modules = set(s.get("file_path", "") for s in st.session_state.metadata)
                st.metric("Modules", len(modules))
            with col3:
                functions = sum(1 for s in st.session_state.metadata if s.get("symbol_type") == "function")
                st.metric("Functions", functions)
    
    st.divider()
    
    # Upload options
    st.subheader("Upload New Codebase")
    
    upload_method = st.radio(
        "Choose upload method:",
        ["📦 Upload ZIP file", "📂 Use local directory"],
        horizontal=True
    )
    
    if upload_method == "📦 Upload ZIP file":
        uploaded_file = st.file_uploader(
            "Upload a ZIP file containing your codebase",
            type=["zip"],
            help="Upload a ZIP archive of your Python codebase"
        )
        
        if uploaded_file:
            if st.button("🚀 Process Codebase", type="primary", use_container_width=True):
                process_uploaded_zip(uploaded_file, config)
    
    else:  # Local directory
        directory_path = st.text_input(
            "Enter path to local codebase directory:",
            value=str(config.base_dir / "fastapi-realworld-example-app"),
            help="Absolute path to your Python codebase"
        )
        
        if st.button("🚀 Process Codebase", type="primary", use_container_width=True):
            process_local_directory(directory_path, config)


def process_uploaded_zip(uploaded_file, config: Config):
    """Process an uploaded ZIP file."""
    
    with st.status("Processing codebase...", expanded=True) as status:
        try:
            # Create temp directory
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                st.write("📦 Extracting ZIP file...")
                # Extract ZIP
                zip_path = temp_path / uploaded_file.name
                with open(zip_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_path / "codebase")
                
                codebase_path = temp_path / "codebase"
                
                # Find the actual root (sometimes ZIP has a wrapper folder)
                subdirs = list(codebase_path.iterdir())
                if len(subdirs) == 1 and subdirs[0].is_dir():
                    codebase_path = subdirs[0]
                
                st.write("🔍 Parsing repository...")
                # Parse the codebase
                symbols_data = parse_repository(
                    str(codebase_path),
                    config.symbols_path
                )
                
                st.write("🧠 Building vector store...")
                # Generate retrievals and build index
                retrievals = generate_retrievals(symbols_data)
                vectorstore, metadata = load_or_create_index(
                    retrievals,
                    config.embedding_model,
                    config.vector_dir
                )
                
                # Update session state
                st.session_state.current_codebase = uploaded_file.name
                st.session_state.vectorstore = vectorstore
                st.session_state.metadata = metadata
                
                status.update(label="✅ Codebase processed successfully!", state="complete")
                st.success(f"🎉 Processed {len(metadata)} symbols from {uploaded_file.name}")
                st.balloons()
        
        except Exception as e:
            status.update(label="❌ Processing failed", state="error")
            st.error(f"Error processing codebase: {str(e)}")
            import traceback
            st.code(traceback.format_exc())


def process_local_directory(directory_path: str, config: Config):
    """Process a local directory."""
    
    dir_path = Path(directory_path)
    
    if not dir_path.exists():
        st.error(f"❌ Directory not found: {directory_path}")
        return
    
    if not dir_path.is_dir():
        st.error(f"❌ Path is not a directory: {directory_path}")
        return
    
    with st.status("Processing codebase...", expanded=True) as status:
        try:
            st.write("🔍 Parsing repository...")
            # Parse the codebase
            symbols_data = parse_repository(
                str(dir_path),
                config.symbols_path
            )
            
            st.write("🧠 Building vector store...")
            # Generate retrievals and build index
            retrievals = generate_retrievals(symbols_data)
            vectorstore, metadata = load_or_create_index(
                retrievals,
                config.embedding_model,
                config.vector_dir
            )
            
            # Update session state
            st.session_state.current_codebase = dir_path.name
            st.session_state.vectorstore = vectorstore
            st.session_state.metadata = metadata
            
            status.update(label="✅ Codebase processed successfully!", state="complete")
            st.success(f"🎉 Processed {len(metadata)} symbols from {dir_path.name}")
            st.balloons()
        
        except Exception as e:
            status.update(label="❌ Processing failed", state="error")
            st.error(f"Error processing codebase: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
