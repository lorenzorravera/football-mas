"""
Agent nodes for the multi-agent system.

Each agent is a function that takes AgentState and returns updated state.
"""

from .manager import manager_agent
from .data_discovery import data_discovery_agent
from .data_analyst import data_analyst_agent
from .visualizer import visualizer_agent
from .synthesizer import synthesizer_agent
from .prediction_agent import prediction_agent

__all__ = [
    "manager_agent",
    "data_discovery_agent",
    "data_analyst_agent",
    "visualizer_agent",
    "synthesizer_agent",
    "prediction_agent",
]
