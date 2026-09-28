"""
Streamlit App for Football Analytics Multi-Agent System

User interface for querying Premier League match data through a multi-agent
pipeline (Manager → Data → Analytics → Visualizer).
"""

import streamlit as st
from graph import app
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="Premier League Analytics",
    page_icon="⚽",
    layout="wide"
)

# Title and description
st.title("Premier League Analytics Dashboard")
st.markdown("Multi-Agent System for Premier League data analysis (2020-2025)")

# Sidebar
with st.sidebar:
    st.header("System Configuration")
    st.info("Pipeline: Manager → Data → Analytics → Visualizer")
    
    st.markdown("---")
    
    show_debug = st.checkbox("Enable debug mode", value=False)
    
    st.markdown("---")
    
    st.markdown("**Query Examples:**")
    examples = [
        "Show Arsenal statistics for this season",
        "Compare Liverpool and Manchester City",
        "Display the current league table",
        "Arsenal versus Chelsea head to head record",
        "Top 5 teams by goals scored",
        "Liverpool form in last 5 matches"
    ]
    
    for example in examples:
        if st.button(example, key=example, use_container_width=True):
            st.session_state.query = example

# Main query input
query = st.text_input(
    "Enter your query:",
    value=st.session_state.get("query", ""),
    placeholder="Example: Show Arsenal goals this season",
    key="query_input"
)

# Run analysis button
if st.button("Execute Analysis", type="primary", use_container_width=True):
    if not query:
        st.warning("Please enter a query to analyze")
    else:
        with st.spinner("Processing query through multi-agent pipeline..."):
            try:
                # Execute the workflow
                result = app.invoke({
                    "user_query": query,
                    "errors": []
                })
                
                # Check for errors
                if result.get("errors"):
                    st.error("Execution errors occurred:")
                    for error in result["errors"]:
                        st.error(error)
                else:
                    # Display visualizations
                    if result.get("visualizations"):
                        st.success("Analysis completed successfully")
                        
                        for i, fig in enumerate(result["visualizations"]):
                            st.plotly_chart(fig, use_container_width=True, key=f"visualization_{i}")
                    else:
                        st.warning("No visualizations were generated for this query")
                
                # Debug information
                if show_debug:
                    with st.expander("Debug Information"):
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.subheader("Parsed Query")
                            st.json(result.get("parsed_query", {}))
                            
                            st.subheader("Data Metadata")
                            st.json(result.get("raw_data", {}).get("metadata", {}))
                        
                        with col2:
                            st.subheader("Analytics Results")
                            analytics = result.get("analytics_results", {})
                            st.json({
                                "query_type": analytics.get("query_type"),
                                "has_team_stats": analytics.get("team_stats") is not None,
                                "has_comparison": analytics.get("comparison") is not None,
                                "has_league_table": analytics.get("league_table") is not None,
                                "has_head_to_head": analytics.get("head_to_head") is not None
                            })
                
            except Exception as e:
                st.error(f"An error occurred during execution: {str(e)}")
                logger.exception("Pipeline execution failed")
                
                if show_debug:
                    with st.expander("Error Details"):
                        st.exception(e)

# Footer
st.markdown("---")
st.markdown("Data Source: Football-Data.co.uk | Coverage: Seasons 2020-21 through 2024-25")




from langfuse.decorators import observe

@observe()  # This wraps the entire MAS execution
def run_mas(query: str):
    return app.invoke({
        "user_query": query,
        "errors": []
    })

# Replace in button click:
result = run_mas(query)