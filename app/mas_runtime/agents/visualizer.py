"""
Visualizer Agent - Generate Plotly charts from data.

Responsibilities:
1. If a predefined SQL function was used (full_control / semi_control-function path),
   dispatch to a styled chart function from viz_functions.py.
2. Otherwise, ask the LLM to choose a chart type and generate a Plotly figure
   following the project's visual style guide.
3. Return both the HTML string (kept for synthesizer context) and the Figure object
   (for cl.Plotly rendering in Chainlit).
"""

import sys
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "agent_v4"))

from state import AgentState
from config import call_llm, get_agent_model
from agent_tools.viz_functions import get_viz_for_function, get_function_name_from_sql_query



def visualizer_agent(state: AgentState) -> AgentState:
    """
    Visualizer agent: generate a Plotly chart for the retrieved data.

    Two paths:
    1. Predefined-function path (full_control or semi_control using a function):
       sql_query starts with "Function: <name>(...)". Dispatch to a styled
       chart function from viz_functions.py.
    2. Custom-SQL path (no_control or semi_control custom SQL):
       Ask the LLM to choose chart type + columns, then build the chart
       programmatically using _build_chart().

    Args:
        state: Current agent state with data_result and sql_query

    Returns:
        Updated state with viz_html, viz_figure, viz_type
    """
    user_query = state["user_query"]
    data_result = state.get("data_result")
    sql_query = state.get("sql_query", "")

    if data_result is None or (isinstance(data_result, pd.DataFrame) and data_result.empty):
        state["error"] = "No data to visualize"
        state["error_stage"] = "visualizer"
        return state

    # ------------------------------------------------------------------
    # Path 1: Predefined function → styled chart from viz_functions.py
    # ------------------------------------------------------------------
    function_name = get_function_name_from_sql_query(sql_query)
    if function_name:
        try:
            fig = get_viz_for_function(function_name, data_result)
            if fig is not None:
                state["viz_html"] = fig.to_html(include_plotlyjs="cdn", full_html=False)
                state["viz_figure"] = fig
                state["viz_type"] = function_name
                return state
        except Exception:
            pass  # Fall through to LLM path if styled function fails

    # ------------------------------------------------------------------
    # Path 2: Custom SQL → LLM picks chart type and generates the figure
    # ------------------------------------------------------------------
    prompt = f"""You are a data visualization expert for Premier League analytics.

User Query: "{user_query}"

Data Preview:
{data_result.head(10).to_string()}

Data Shape: {data_result.shape[0]} rows, {data_result.shape[1]} columns
Columns: {list(data_result.columns)}

Respond in this EXACT format (all keys required):

CHART_TYPE: [hbar/vbar/grouped_bar/stacked_bar/scatter/table]
X_COLUMN: [column name]
Y_COLUMN: [column name]
COLOR_COLUMN: [column name for colour grouping, or "none"]
COLOR_SCALE: [Blues/Oranges/Tealgrn/OrRd_r/Purples, or "none" for categorical colour]
TITLE: [chart title]
ORIENTATION: [h/v]  (h=horizontal, v=vertical)
BARMODE: [group/stack/relative, or "none"]
REASONING: [one-line reason]

Chart type rules:
- hbar: rankings / top-N lists (team_name vs a metric). Use autorange="reversed" so best is at top.
- vbar: time series, non-ranked comparisons with few categories
- grouped_bar: comparing 2+ teams or groups across metrics; set COLOR_COLUMN to the grouping column
- stacked_bar: proportion breakdowns (wins/draws/losses, home/away splits)
- scatter: correlation between two numeric columns across teams/seasons
- table: raw match listings or data with many heterogeneous columns

Colour scale rules (for hbar/vbar with a continuous colour):
- Points / general rank → "Blues"
- Goals scored / attacking metrics → "Oranges"
- Clean sheets / defensive quality (higher=better) → "Tealgrn"
- Goals conceded (lower=better, so more = worse) → "OrRd_r"
- Other rankings → "Purples"
- For grouped_bar or stacked_bar with categorical colour: set COLOR_SCALE to "none"

Examples:

Data: team_name | goals_scored
CHART_TYPE: hbar
X_COLUMN: goals_scored
Y_COLUMN: team_name
COLOR_COLUMN: goals_scored
COLOR_SCALE: Oranges
TITLE: Top Scoring Teams
ORIENTATION: h
BARMODE: none
REASONING: Ranking of teams by goals — horizontal bar with Oranges scale

Data: team_name | wins | draws | losses (two teams)
CHART_TYPE: grouped_bar
X_COLUMN: Result
Y_COLUMN: Count
COLOR_COLUMN: team_name
COLOR_SCALE: none
TITLE: Team Comparison
ORIENTATION: v
BARMODE: group
REASONING: Comparing two teams across result categories

Data: season | total_goals (multiple seasons)
CHART_TYPE: vbar
X_COLUMN: season
Y_COLUMN: total_goals
COLOR_COLUMN: total_goals
COLOR_SCALE: Blues
TITLE: Goals Per Season
ORIENTATION: v
BARMODE: none
REASONING: Time series — vertical bars show trend

Now analyze the data above."""

    model = get_agent_model("visualizer")
    messages = [{"role": "user", "content": prompt}]

    try:
        response = call_llm(messages, model=model, temperature=0.0)

        # Parse structured response
        lines = response.strip().split("\n")
        parsed = {}
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                parsed[key.strip()] = value.strip()

        chart_type = parsed.get("CHART_TYPE", "vbar").lower()
        x_col = parsed.get("X_COLUMN", data_result.columns[0])
        y_col = parsed.get("Y_COLUMN", data_result.columns[1] if len(data_result.columns) > 1 else data_result.columns[0])
        color_col = parsed.get("COLOR_COLUMN", "none")
        color_scale = parsed.get("COLOR_SCALE", "Blues")
        title = parsed.get("TITLE", "Data Visualization")
        barmode = parsed.get("BARMODE", "none").lower()

        # Validate columns exist
        if x_col not in data_result.columns:
            x_col = data_result.columns[0]
        if y_col not in data_result.columns:
            y_col = data_result.columns[1] if len(data_result.columns) > 1 else data_result.columns[0]
        color_val = None if color_col == "none" or color_col not in data_result.columns else color_col

        fig = _build_chart(
            chart_type=chart_type,
            df=data_result,
            x_col=x_col,
            y_col=y_col,
            color_col=color_val,
            color_scale=color_scale,
            title=title,
            barmode=barmode,
        )

        state["viz_html"] = fig.to_html(include_plotlyjs="cdn", full_html=False)
        state["viz_figure"] = fig
        state["viz_type"] = chart_type

    except Exception as e:
        state["error"] = f"Visualization failed: {str(e)}"
        state["error_stage"] = "visualizer"
        state["viz_html"] = None
        state["viz_figure"] = None
        state["viz_type"] = None

    return state


def _build_chart(
    chart_type: str,
    df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color_col,
    color_scale: str,
    title: str,
    barmode: str,
) -> go.Figure:
    """
    Build a styled Plotly figure based on the LLM-chosen parameters.
    Applies project visual style guide (template, text labels, colour scales).
    """
    is_continuous_color = color_col == y_col or (
        color_col is not None and color_col not in ["none"]
        and pd.api.types.is_numeric_dtype(df[color_col])
        and barmode not in ("group", "stack")
    )

    if chart_type in ("hbar", "vbar"):
        # Convention from LLM prompt:
        #   hbar → X_COLUMN = numeric value (horizontal axis), Y_COLUMN = category (vertical)
        #   vbar → X_COLUMN = category (horizontal axis),      Y_COLUMN = numeric value (vertical)
        orientation = "h" if chart_type == "hbar" else "v"
        # text label should show the numeric value at the end of each bar
        text_col = x_col if chart_type == "hbar" else y_col
        kwargs = dict(
            x=x_col,
            y=y_col,
            orientation=orientation,
            text=text_col,
            title=title,
            template="plotly_white",
            height=600,
        )
        if is_continuous_color and color_scale != "none":
            kwargs["color"] = color_col
            kwargs["color_continuous_scale"] = color_scale
        elif color_col:
            kwargs["color"] = color_col

        fig = px.bar(df, **kwargs)

        if chart_type == "hbar":
            fig.update_layout(
                yaxis=dict(
                    autorange="reversed",
                    categoryorder="array",
                    categoryarray=df[y_col].tolist(),  # y_col is the category column
                ),
                showlegend=False,
                coloraxis_showscale=False,
                xaxis_title=x_col.replace("_", " ").title(),  # x_col is the metric
                yaxis_title="",
            )
        else:
            fig.update_layout(
                coloraxis_showscale=False,
                xaxis_title=x_col.replace("_", " ").title(),
                yaxis_title=y_col.replace("_", " ").title(),
            )
        fig.update_traces(textposition="outside")

    elif chart_type == "grouped_bar":
        fig = px.bar(
            df, x=x_col, y=y_col,
            color=color_col,
            barmode="group",
            text=y_col,
            title=title,
            template="plotly_white",
            height=500,
        )
        fig.update_traces(textposition="outside")

    elif chart_type == "stacked_bar":
        color_map = {}
        if color_col and color_col in df.columns:
            unique_vals = df[color_col].unique()
            # Apply semantic colours if it looks like a result column
            result_map = {"won": "#2ecc71", "won_h": "#2ecc71", "won_a": "#27ae60",
                          "drawn": "#f39c12", "draw": "#f39c12",
                          "lost": "#e74c3c", "lost_h": "#e74c3c", "lost_a": "#c0392b",
                          "W": "#2ecc71", "D": "#f39c12", "L": "#e74c3c"}
            for val in unique_vals:
                if str(val).lower() in result_map or str(val) in result_map:
                    color_map[val] = result_map.get(str(val).lower(), result_map.get(str(val), "#95a5a6"))

        kwargs = dict(
            x=x_col, y=y_col, color=color_col,
            barmode="stack", text=y_col,
            title=title, template="plotly_white", height=500,
        )
        if color_map:
            kwargs["color_discrete_map"] = color_map
        fig = px.bar(df, **kwargs)
        fig.update_traces(textposition="inside")

    elif chart_type == "scatter":
        fig = px.scatter(
            df, x=x_col, y=y_col,
            text=color_col if color_col else None,
            color=color_col if color_col else None,
            trendline="ols",
            title=title,
            template="plotly_white",
            height=500,
        )
        fig.update_traces(marker=dict(size=10), textposition="top center")

    else:  # table fallback
        header_vals = [f"<b>{c}</b>" for c in df.columns]
        cell_vals = [df[c].astype(str).tolist() for c in df.columns]
        fig = go.Figure(data=[go.Table(
            header=dict(values=header_vals, fill_color="#2c3e50",
                        font=dict(color="white", size=12), align="center", height=32),
            cells=dict(values=cell_vals,
                       fill_color=[["#f0f3f7" if i % 2 == 0 else "white" for i in range(len(df))]
                                   for _ in df.columns],
                       align="center", height=28),
        )])
        fig.update_layout(title=title, template="plotly_white", margin=dict(t=50, b=20))

    return fig


if __name__ == "__main__":
    # Test the visualizer agent
    from state import create_initial_state

    # Test 1: Predefined-function path (league standings)
    test_data_standings = pd.DataFrame({
        "position": [1, 2, 3],
        "team_name": ["Man City", "Arsenal", "Liverpool"],
        "points": [91, 89, 82],
    })

    test_state = create_initial_state("Show me the league standings for 2023_2024")
    test_state["data_result"] = test_data_standings
    test_state["sql_query"] = "Function: get_league_standings(season=2023_2024)"
    test_state["intent"] = "full_pipeline"

    print("Testing Visualizer Agent (predefined-function path)...")
    result = visualizer_agent(test_state)
    print(f"Visualization Type: {result.get('viz_type', 'N/A')}")
    print(f"HTML Generated: {len(result.get('viz_html', '')) > 0}")
    if result.get("error"):
        print(f"Error: {result['error']}")

    # Test 2: Custom-SQL path (top scorers)
    test_data_custom = pd.DataFrame({
        "team_name": ["Arsenal", "Man City", "Liverpool"],
        "total_goals": [89, 95, 91],
    })

    test_state2 = create_initial_state("Which teams scored the most goals?")
    test_state2["data_result"] = test_data_custom
    test_state2["sql_query"] = "SELECT team_name, SUM(goals_scored) as total_goals ..."
    test_state2["intent"] = "full_pipeline"

    print("\nTesting Visualizer Agent (custom SQL path)...")
    result2 = visualizer_agent(test_state2)
    print(f"Visualization Type: {result2.get('viz_type', 'N/A')}")
    print(f"HTML Generated: {len(result2.get('viz_html', '')) > 0}")
    if result2.get("error"):
        print(f"Error: {result2['error']}")
