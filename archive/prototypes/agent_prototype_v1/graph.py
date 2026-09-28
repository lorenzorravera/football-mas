from typing import TypedDict, Annotated, Optional, List, Dict, Any
import operator

class MASState(TypedDict):
    """
    Shared state for the football analytics Multi-Agent System.
    State flows: Manager → Data → Analytics → Visualizer
    """
    
    # INPUT - User's natural language query
    user_query: str
    
    # MANAGER AGENT OUTPUT - Parsed query intent
    parsed_query: Optional[Dict[str, Any]]  # {teams, date_range, metrics, query_type}
    
    # DATA AGENT OUTPUT - Raw data from databases/APIs
    raw_data: Optional[Dict[str, Any]]  # {matches: df, league_table: df, ...}
    
    # ANALYTICS AGENT OUTPUT - Computed metrics and aggregations
    analytics_results: Optional[Dict[str, Any]]  # {win_rate: 0.65, rankings: [...], ...}
    
    # VISUALIZER AGENT OUTPUT - Plotly figure objects ready for display
    visualizations: Optional[List[Any]]  # [plotly.graph_objects.Figure, ...]
    
    # ERROR TRACKING - Accumulates errors from any agent
    errors: Annotated[list, operator.add]

from typing import Dict, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def manager_agent_node(state: MASState) -> Dict[str, Any]:
    """
    Execute the Manager Agent node.
    
    This node parses the user's natural language query to extract structured
    information including: target teams, date ranges, requested metrics, and
    query type (comparison, trend analysis, ranking, etc.).
    
    Args:
        state: Current system state containing user query
        
    Returns:
        Dictionary containing parsed_query with structured intent, or errors
        if parsing failed
    """
    from agents.manager_agent import execute
    
    logger.info("Executing Manager Agent node")
    
    try:
        result = execute(state)
        logger.info("Manager Agent execution completed successfully")
        return {"parsed_query": result}
    except Exception as e:
        logger.error(f"Manager Agent execution failed: {str(e)}")
        return {"errors": [f"Manager Agent: {str(e)}"]}


def data_agent_node(state: MASState) -> Dict[str, Any]:
    """
    Execute the Data Agent node.
    
    This node fetches raw data from available sources based on the parsed query.
    It performs no processing or aggregation, only data retrieval and basic
    filtering operations. Data sources may include match results, league tables,
    player statistics, and team information.
    
    Args:
        state: Current system state containing parsed query from Manager Agent
        
    Returns:
        Dictionary containing raw_data with fetched datasets, or errors if
        prerequisites are not met or retrieval failed
    """
    from agents.data_agent import execute
    
    logger.info("Executing Data Agent node")
    
    if not state.get("parsed_query"):
        error_msg = "Data Agent: No parsed query available from Manager Agent"
        logger.error(error_msg)
        return {"errors": [error_msg]}
    
    try:
        result = execute(state)
        logger.info("Data Agent execution completed successfully")
        return {"raw_data": result}
    except Exception as e:
        logger.error(f"Data Agent execution failed: {str(e)}")
        return {"errors": [f"Data Agent: {str(e)}"]}


def analytics_agent_node(state: MASState) -> Dict[str, Any]:
    """
    Execute the Analytics Agent node.
    
    This node performs all computational analysis on raw data, including metric
    calculations, aggregations, statistical comparisons, and rankings. It applies
    domain-specific football analytics logic to derive insights from the raw data.
    
    Args:
        state: Current system state containing raw data from Data Agent
        
    Returns:
        Dictionary containing analytics_results with computed metrics and
        aggregations, or errors if prerequisites are not met or computation failed
    """
    from agents.analytics_agent import execute
    
    logger.info("Executing Analytics Agent node")
    
    if not state.get("raw_data"):
        error_msg = "Analytics Agent: No raw data available from Data Agent"
        logger.error(error_msg)
        return {"errors": [error_msg]}
    
    try:
        result = execute(state)
        logger.info("Analytics Agent execution completed successfully")
        return {"analytics_results": result}
    except Exception as e:
        logger.error(f"Analytics Agent execution failed: {str(e)}")
        return {"errors": [f"Analytics Agent: {str(e)}"]}


def visualizer_agent_node(state: MASState) -> Dict[str, Any]:
    """
    Execute the Visualizer Agent node.
    
    This node generates interactive visualizations using Plotly based on the
    analytics results. It determines appropriate chart types (bar, line, heatmap,
    table) based on the query type and data characteristics. No analytical
    computation is performed at this stage.
    
    Args:
        state: Current system state containing analytics results
        
    Returns:
        Dictionary containing visualizations as Plotly figure objects ready for
        display, or errors if prerequisites are not met or visualization failed
    """
    from agents.visualizer_agent import execute
    
    logger.info("Executing Visualizer Agent node")
    
    if not state.get("analytics_results"):
        error_msg = "Visualizer Agent: No analytics results available from Analytics Agent"
        logger.error(error_msg)
        return {"errors": [error_msg]}
    
    try:
        result = execute(state)
        logger.info("Visualizer Agent execution completed successfully")
        return {"visualizations": result}
    except Exception as e:
        logger.error(f"Visualizer Agent execution failed: {str(e)}")
        return {"errors": [f"Visualizer Agent: {str(e)}"]}
    
from langgraph.graph import StateGraph, END


def create_workflow() -> StateGraph:
    """
    Construct the Multi-Agent System workflow.
    
    The workflow follows a linear pipeline:
    Manager Agent → Data Agent → Analytics Agent → Visualizer Agent
    
    Each agent processes the state and passes enriched information to the next
    agent in the sequence. The workflow terminates after visualization generation.
    
    Returns:
        Compiled StateGraph ready for execution
    """
    # Initialize graph with state schema
    workflow = StateGraph(MASState)
    
    # Register all agent nodes
    workflow.add_node("manager_agent", manager_agent_node)
    workflow.add_node("data_agent", data_agent_node)
    workflow.add_node("analytics_agent", analytics_agent_node)
    workflow.add_node("visualizer_agent", visualizer_agent_node)
    
    # Define linear execution flow
    workflow.set_entry_point("manager_agent")
    workflow.add_edge("manager_agent", "data_agent")
    workflow.add_edge("data_agent", "analytics_agent")
    workflow.add_edge("analytics_agent", "visualizer_agent")
    workflow.add_edge("visualizer_agent", END)
    
    # Compile the workflow into an executable application
    return workflow.compile()


# Create the application instance
app = create_workflow()


if __name__ == "__main__":
    """
    Test the workflow with a sample query.
    """
    test_state = {
        "user_query": "Show me Arsenal's performance this season",
        "errors": []
    }
    
    logger.info("Testing workflow with sample query...")
    result = app.invoke(test_state)
    
    logger.info("Workflow execution completed")
    logger.info(f"Final state keys: {result.keys()}")