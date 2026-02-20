"""Diagram viewer component for interactive architecture visualization."""

import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from visualization.interactive_diagram import (
    create_module_level_diagram,
    create_intra_module_diagram,
    create_full_hierarchical_diagram
)
from config import Config


def render_diagram_viewer():
    """Render the interactive diagram viewer."""
    
    st.header("📊 Architecture Diagram")
    
    # Check if codebase is loaded
    if not st.session_state.current_codebase or not st.session_state.metadata:
        st.warning("⚠️ Please upload a codebase first in the Codebase Manager!")
        return
    
    config = Config()
    
    # Diagram options
    col1, col2 = st.columns([3, 1])
    
    with col1:
        diagram_type = st.selectbox(
            "Select Diagram Type:",
            [
                "📦 Module-Level Architecture",
                "🔍 Intra-Module View",
                "🌳 Full Hierarchical View"
            ]
        )
    
    with col2:
        if st.button("🔄 Regenerate", use_container_width=True):
            # Clear cached diagram
            if "current_diagram_html" in st.session_state:
                del st.session_state.current_diagram_html
    
    # Module selector for intra-module view
    selected_module = None
    if diagram_type == "🔍 Intra-Module View":
        # Get unique modules
        modules = sorted(set(s.get("file_path", "") for s in st.session_state.metadata))
        selected_module = st.selectbox(
            "Select module to visualize:",
            modules,
            format_func=lambda x: Path(x).name if x else "Unknown"
        )
    
    # Generate diagram button
    if st.button("🎨 Generate Diagram", type="primary", use_container_width=True):
        with st.spinner("Generating interactive diagram..."):
            try:
                output_path = Path(config.arch_dir) / "interactive_diagram.html"
                
                if diagram_type == "📦 Module-Level Architecture":
                    diagram_path = create_module_level_diagram(
                        st.session_state.metadata,
                        str(output_path)
                    )
                
                elif diagram_type == "🔍 Intra-Module View":
                    if not selected_module:
                        st.error("Please select a module first!")
                        return
                    
                    diagram_path = create_intra_module_diagram(
                        selected_module,
                        st.session_state.metadata,
                        str(output_path)
                    )
                
                else:  # Full hierarchical
                    diagram_path = create_full_hierarchical_diagram(
                        st.session_state.metadata,
                        str(output_path),
                        max_nodes=200
                    )
                
                # Read the HTML file
                with open(diagram_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                st.session_state.current_diagram_html = html_content
                st.success("✅ Diagram generated successfully!")
            
            except Exception as e:
                st.error(f"❌ Error generating diagram: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    
    # Display diagram if available
    if "current_diagram_html" in st.session_state:
        st.divider()
        st.subheader("Interactive Diagram")
        st.info("💡 **Tip:** You can zoom, pan, and click on nodes to explore the architecture!")
        
        # Embed the interactive diagram
        components.html(
            st.session_state.current_diagram_html,
            height=800,
            scrolling=True
        )
        
        # Download button
        st.download_button(
            label="💾 Download Diagram (HTML)",
            data=st.session_state.current_diagram_html,
            file_name="architecture_diagram.html",
            mime="text/html",
            use_container_width=True
        )
    
    # Legend
    with st.expander("📖 Diagram Legend"):
        st.markdown("""
        **Node Colors:**
        - 🟦 **Blue (Indigo)**: Modules/Files
        - 🟩 **Green**: Classes
        - 🟨 **Amber**: Functions
        - ⚪ **Gray**: Variables
        
        **Interactions:**
        - **Click and drag** to pan the diagram
        - **Scroll** to zoom in/out
        - **Hover** over nodes to see details
        - **Click** on nodes to highlight connections
        
        **Diagram Types:**
        - **Module-Level**: Shows high-level module dependencies
        - **Intra-Module**: Shows functions and classes within a specific module
        - **Full Hierarchical**: Shows complete codebase structure (may be large!)
        """)
