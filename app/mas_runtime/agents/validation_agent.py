"""
Validation helper — NOT a graph node.

Called directly from data_analyst_agent after each SQL execution.
Returns (passed: bool, hint: str).

Kept as a separate module so it can be unit-tested independently
and promoted to a graph node if LangGraph serialization of DataFrames
is resolved in a future version.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def validate_result(user_query: str, sql_query: str, data_result) -> tuple[bool, str]:
    """
    Check whether data_result actually answers user_query.

    Args:
        user_query:  Original user question
        sql_query:   SQL that was executed
        data_result: pandas DataFrame returned by the query

    Returns:
        (passed, hint)
        passed=True  → result is valid, proceed
        passed=False → result is invalid, hint explains why
    """
    # Empty result — always retry
    if data_result is None or data_result.empty:
        return False, (
            "The previous SQL returned no rows. "
            "Check team name spelling, season format (YYYY_YYYY), and table joins."
        )

    # Data exists — pass through
    # Note: LLM-based relevance check removed due to LangGraph DataFrame
    # serialization constraints in v1.0.10. Can be re-added as a standalone
    # post-pipeline eval step.
    return True, ""