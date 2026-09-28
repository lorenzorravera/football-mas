"""
Predefined Plotly visualization functions for full_control and semi_control agents.

One styled chart function per SQL function, matching project visualization standards:
- template="plotly_white", height=600
- Horizontal bars with autorange="reversed" for rankings
- Color scales: Blues (standings/points), Oranges (scoring), Tealgrn (defense/clean sheets),
  OrRd (goals conceded — lower is worse), Purples (misc rankings)
- Grouped bars for comparisons (barmode="group")
- Stacked bars for home/away splits (barmode="stack")
- Value labels on all bar charts (textposition="outside")
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _styled_htable(df: pd.DataFrame, title: str) -> go.Figure:
    """Fallback: render a DataFrame as a styled go.Table."""
    header_vals = [f"<b>{c}</b>" for c in df.columns]
    cell_vals = [df[c].astype(str).tolist() for c in df.columns]

    fig = go.Figure(data=[go.Table(
        columnwidth=[120] * len(df.columns),
        header=dict(
            values=header_vals,
            fill_color="#2c3e50",
            font=dict(color="white", size=12),
            align="center",
            height=32,
        ),
        cells=dict(
            values=cell_vals,
            fill_color=[["#f0f3f7" if i % 2 == 0 else "white" for i in range(len(df))]
                        for _ in df.columns],
            align="center",
            height=28,
        )
    )])
    fig.update_layout(title=title, template="plotly_white", margin=dict(t=50, b=20))
    return fig


def get_function_name_from_sql_query(sql_query: str) -> Optional[str]:
    """
    Extract function name from the 'Function: func_name(...)' format
    stored in state["sql_query"] by full_control / semi_control when
    a predefined function is used.
    """
    if sql_query and sql_query.startswith("Function: "):
        name = sql_query[len("Function: "):]
        paren_idx = name.find("(")
        if paren_idx > 0:
            return name[:paren_idx]
    return None


# ---------------------------------------------------------------------------
# 1. League Standings
# ---------------------------------------------------------------------------

def viz_league_standings(
    df: pd.DataFrame,
    title: str = "Premier League Standings",
) -> go.Figure:
    """Horizontal bar: teams ranked by points, Blues colour scale."""
    if df.empty or "team_name" not in df.columns or "points" not in df.columns:
        return _styled_htable(df, title)

    df_plot = df.sort_values("points", ascending=False).reset_index(drop=True)
    teams_ordered = df_plot["team_name"].tolist()

    fig = px.bar(
        df_plot,
        x="points",
        y="team_name",
        orientation="h",
        color="points",
        color_continuous_scale="Blues",
        text="points",
        title=title,
        template="plotly_white",
        height=600,
    )
    fig.update_layout(
        yaxis=dict(
            autorange="reversed",
            categoryorder="array",
            categoryarray=teams_ordered,
        ),
        showlegend=False,
        coloraxis_showscale=False,
        xaxis_title="Points",
        yaxis_title="",
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# 2. Team Season Stats
# ---------------------------------------------------------------------------

def viz_team_season_stats(
    df: pd.DataFrame,
    title: str = None,
) -> go.Figure:
    """
    Bar chart of key team stats. If home/away win counts are available,
    adds a grouped Home vs Away wins comparison.
    """
    if df.empty:
        return _styled_htable(df, title or "Team Season Stats")

    row = df.iloc[0]
    team = str(row.get("team_name", "Team"))
    chart_title = title or f"{team} — Season Performance"

    # -- Overall W/D/L --
    result_data = {
        "Result": ["Wins", "Draws", "Losses"],
        "Count": [
            int(row.get("wins", 0)),
            int(row.get("draws", 0)),
            int(row.get("losses", 0)),
        ],
    }
    color_map = {"Wins": "#2ecc71", "Draws": "#f39c12", "Losses": "#e74c3c"}

    df_results = pd.DataFrame(result_data)
    fig = px.bar(
        df_results,
        x="Result",
        y="Count",
        color="Result",
        color_discrete_map=color_map,
        text="Count",
        title=chart_title,
        template="plotly_white",
        height=450,
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Matches")
    fig.update_traces(textposition="outside")

    # -- Home vs Away wins annotation --
    home_wins = int(row.get("home_wins", 0))
    away_wins = int(row.get("away_wins", 0))
    if home_wins or away_wins:
        fig.add_annotation(
            text=f"Home wins: {home_wins} | Away wins: {away_wins}",
            xref="paper", yref="paper",
            x=0.5, y=-0.15,
            showarrow=False,
            font=dict(size=12, color="#555"),
        )

    return fig


# ---------------------------------------------------------------------------
# 3. Head to Head
# ---------------------------------------------------------------------------

def viz_head_to_head(
    df: pd.DataFrame,
    title: str = "Head-to-Head Record",
) -> go.Figure:
    """
    Single horizontal stacked bar: [team_a wins | draws | team_b wins].
    Falls back to table if team columns can't be identified.
    """
    if df.empty or "winner" not in df.columns:
        return _styled_htable(df, title)

    teams = [t for t in df["winner"].unique() if t != "Draw"]
    if len(teams) < 2:
        return _styled_htable(df, title)

    team_a = teams[0]
    team_b = teams[1]
    draws = int((df["winner"] == "Draw").sum())
    a_wins = int((df["winner"] == team_a).sum())
    b_wins = int((df["winner"] == team_b).sum())

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=team_a, x=[a_wins], y=["H2H"],
        orientation="h", text=[a_wins], textposition="inside",
        marker_color="#3498db",
    ))
    fig.add_trace(go.Bar(
        name="Draws", x=[draws], y=["H2H"],
        orientation="h", text=[draws], textposition="inside",
        marker_color="#95a5a6",
    ))
    fig.add_trace(go.Bar(
        name=team_b, x=[b_wins], y=["H2H"],
        orientation="h", text=[b_wins], textposition="inside",
        marker_color="#e74c3c",
    ))
    fig.update_layout(
        barmode="stack",
        title=title or f"{team_a} vs {team_b} — Head-to-Head",
        template="plotly_white",
        height=280,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
        xaxis_title="Matches",
        yaxis_title="",
    )
    return fig


# ---------------------------------------------------------------------------
# 4. Team Form
# ---------------------------------------------------------------------------

def viz_team_form(
    df: pd.DataFrame,
    title: str = None,
) -> go.Figure:
    """Bar chart of recent matches: goals_scored coloured by W/D/L result."""
    if df.empty or "result" not in df.columns:
        return _styled_htable(df, title or "Team Form")

    team = str(df["team_name"].iloc[0]) if "team_name" in df.columns else "Team"
    chart_title = title or f"{team} — Recent Form"

    # Build match label
    if "match_date" in df.columns and "opponent" in df.columns:
        df = df.copy()
        df["match_label"] = df["match_date"].astype(str) + " vs " + df["opponent"].astype(str)
    elif "match_date" in df.columns:
        df = df.copy()
        df["match_label"] = df["match_date"].astype(str)
    else:
        df = df.copy()
        df["match_label"] = df.index.astype(str)

    color_map = {"W": "#2ecc71", "D": "#f39c12", "L": "#e74c3c"}
    y_col = "goals_scored" if "goals_scored" in df.columns else (df.columns[0])

    fig = px.bar(
        df,
        x="match_label",
        y=y_col,
        color="result",
        color_discrete_map=color_map,
        text=y_col,
        title=chart_title,
        template="plotly_white",
        height=400,
    )
    fig.update_layout(
        xaxis_title="Match",
        yaxis_title="Goals Scored",
        xaxis=dict(tickangle=-30),
        showlegend=True,
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# 5. Top Scorers (teams by goals scored)
# ---------------------------------------------------------------------------

def viz_top_scorers(
    df: pd.DataFrame,
    title: str = "Top Scoring Teams",
) -> go.Figure:
    """Horizontal bar: teams ranked by goals_scored, Oranges colour scale."""
    if df.empty or "goals_scored" not in df.columns:
        return _styled_htable(df, title)

    y_col = "team_name" if "team_name" in df.columns else df.columns[0]
    df_plot = df.sort_values("goals_scored", ascending=False).reset_index(drop=True)

    fig = px.bar(
        df_plot,
        x="goals_scored",
        y=y_col,
        orientation="h",
        color="goals_scored",
        color_continuous_scale="Oranges",
        text="goals_scored",
        title=title,
        template="plotly_white",
        height=600,
    )
    fig.update_layout(
        yaxis=dict(
            autorange="reversed",
            categoryorder="array",
            categoryarray=df_plot[y_col].tolist(),
        ),
        showlegend=False,
        coloraxis_showscale=False,
        xaxis_title="Goals Scored",
        yaxis_title="",
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# 6. Defensive Rankings
# ---------------------------------------------------------------------------

def viz_defensive_rankings(
    df: pd.DataFrame,
    title: str = "Defensive Rankings",
) -> go.Figure:
    """
    Horizontal bar for defensive rankings.
    - clean_sheets: Tealgrn, highest at top (reversed)
    - goals_conceded: OrRd, lowest at top (sorted ascending then reversed)
    """
    if df.empty or "team_name" not in df.columns:
        return _styled_htable(df, title)

    use_clean_sheets = (
        "clean_sheets" in df.columns
        and df["clean_sheets"].sum() > 0
        and "goals_conceded" not in df.columns
    )

    if use_clean_sheets:
        metric = "clean_sheets"
        color_scale = "Tealgrn"
        x_title = "Clean Sheets"
        df_plot = df.sort_values(metric, ascending=False).reset_index(drop=True)
    else:
        metric = "goals_conceded" if "goals_conceded" in df.columns else df.columns[-1]
        color_scale = "OrRd_r"  # reversed: high conceded = red
        x_title = "Goals Conceded"
        # Sort ascending (fewer conceded = better = should appear at top)
        df_plot = df.sort_values(metric, ascending=True).reset_index(drop=True)

    fig = px.bar(
        df_plot,
        x=metric,
        y="team_name",
        orientation="h",
        color=metric,
        color_continuous_scale=color_scale,
        text=metric,
        title=title,
        template="plotly_white",
        height=600,
    )
    fig.update_layout(
        yaxis=dict(
            autorange="reversed",
            categoryorder="array",
            categoryarray=df_plot["team_name"].tolist(),
        ),
        showlegend=False,
        coloraxis_showscale=False,
        xaxis_title=x_title,
        yaxis_title="",
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# 7. Match History
# ---------------------------------------------------------------------------

def viz_match_history(
    df: pd.DataFrame,
    title: str = "Match History",
) -> go.Figure:
    """Table view — match history has too many columns/rows for a bar chart."""
    return _styled_htable(df, title)


# ---------------------------------------------------------------------------
# 8. Compare Teams
# ---------------------------------------------------------------------------

def viz_compare_teams(
    df: pd.DataFrame,
    title: str = "Team Comparison",
) -> go.Figure:
    """
    Grouped bar chart: one bar per team across key performance metrics.
    """
    if df.empty or "team_name" not in df.columns:
        return _styled_htable(df, title)

    # Pick meaningful numeric metrics available in the data
    candidates = [
        "total_points", "wins", "draws", "losses",
        "goals_scored", "goals_conceded",
        "shots_on_target", "corners",
    ]
    metrics = [m for m in candidates if m in df.columns]
    if not metrics:
        return _styled_htable(df, title)

    df_melt = df[["team_name"] + metrics].melt(
        id_vars="team_name",
        var_name="Metric",
        value_name="Value",
    )

    # Friendly metric labels
    label_map = {
        "total_points": "Points",
        "wins": "Wins",
        "draws": "Draws",
        "losses": "Losses",
        "goals_scored": "Goals For",
        "goals_conceded": "Goals Against",
        "shots_on_target": "Shots on Target",
        "corners": "Corners",
    }
    df_melt["Metric"] = df_melt["Metric"].map(lambda x: label_map.get(x, x))

    fig = px.bar(
        df_melt,
        x="Metric",
        y="Value",
        color="team_name",
        barmode="group",
        text="Value",
        title=title,
        template="plotly_white",
        height=500,
    )
    fig.update_layout(
        xaxis_title="",
        yaxis_title="",
        legend_title_text="Team",
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# 9. Referee Stats
# ---------------------------------------------------------------------------

def viz_referee_stats(
    df: pd.DataFrame,
    title: str = "Referee Statistics",
) -> go.Figure:
    """Bar chart of per-match averages and aggregate totals for a referee."""
    if df.empty:
        return _styled_htable(df, title)

    row = df.iloc[0]
    ref = str(row.get("referee_name", "Referee"))
    chart_title = title or f"{ref} — Officiating Statistics"

    per_match_stats = {
        "Yellows/Match": float(row.get("yellows_per_match", 0) or 0),
        "Reds/Match": float(row.get("reds_per_match", 0) or 0),
        "Avg Goals/Match": float(row.get("avg_goals_per_match", 0) or 0),
    }
    win_pct = {
        "Home Win %": float(row.get("home_win_pct", 0) or 0),
    }

    df_per_match = pd.DataFrame({
        "Stat": list(per_match_stats.keys()),
        "Value": list(per_match_stats.values()),
    })

    color_map = {
        "Yellows/Match": "#f1c40f",
        "Reds/Match": "#e74c3c",
        "Avg Goals/Match": "#3498db",
    }

    fig = px.bar(
        df_per_match,
        x="Stat",
        y="Value",
        color="Stat",
        color_discrete_map=color_map,
        text=df_per_match["Value"].round(2),
        title=chart_title,
        template="plotly_white",
        height=400,
    )
    fig.update_layout(
        showlegend=False,
        xaxis_title="",
        yaxis_title="Per Match",
    )
    fig.update_traces(textposition="outside")

    total_matches = int(row.get("matches_officiated", 0))
    home_pct = per_match_stats.copy()
    home_pct.update(win_pct)
    fig.add_annotation(
        text=(f"Matches officiated: {total_matches} | "
              f"Home win %: {win_pct['Home Win %']:.1f}%"),
        xref="paper", yref="paper",
        x=0.5, y=-0.18,
        showarrow=False,
        font=dict(size=11, color="#555"),
    )
    return fig


# ---------------------------------------------------------------------------
# 10. Season Aggregates
# ---------------------------------------------------------------------------

def viz_season_aggregates(
    df: pd.DataFrame,
    title: str = "Season Overview",
) -> go.Figure:
    """Bar chart of key league-wide aggregate statistics."""
    if df.empty:
        return _styled_htable(df, title)

    row = df.iloc[0]

    stats = {
        "Total Goals": int(row.get("total_goals", 0)),
        "Goals/Match": float(row.get("goals_per_match", 0) or 0),
        "Yellows/Match": float(row.get("yellows_per_match", 0) or 0),
        "Home Win %": float(row.get("home_win_pct", 0) or 0),
    }

    df_stats = pd.DataFrame({
        "Stat": list(stats.keys()),
        "Value": list(stats.values()),
    })

    color_map = {
        "Total Goals": "#3498db",
        "Goals/Match": "#2ecc71",
        "Yellows/Match": "#f1c40f",
        "Home Win %": "#9b59b6",
    }

    fig = px.bar(
        df_stats,
        x="Stat",
        y="Value",
        color="Stat",
        color_discrete_map=color_map,
        text=df_stats["Value"].round(2),
        title=title,
        template="plotly_white",
        height=400,
    )
    fig.update_layout(
        showlegend=False,
        xaxis_title="",
        yaxis_title="",
    )
    fig.update_traces(textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_VIZ_DISPATCH = {
    "get_league_standings": viz_league_standings,
    "get_team_season_stats": viz_team_season_stats,
    "get_head_to_head": viz_head_to_head,
    "get_team_form": viz_team_form,
    "get_top_scorers": viz_top_scorers,
    "get_defensive_rankings": viz_defensive_rankings,
    "get_match_history": viz_match_history,
    "compare_teams": viz_compare_teams,
    "get_referee_stats": viz_referee_stats,
    "get_season_aggregates": viz_season_aggregates,
}


def get_viz_for_function(
    function_name: str,
    df: pd.DataFrame,
    title: str = None,
) -> Optional[go.Figure]:
    """
    Dispatch to the appropriate styled chart function.

    Args:
        function_name: One of the 10 keys in FUNCTION_REGISTRY
        df: The DataFrame returned by the SQL function
        title: Optional chart title (auto-generated if None)

    Returns:
        A Plotly Figure, or None if function_name is unknown
    """
    viz_fn = _VIZ_DISPATCH.get(function_name)
    if viz_fn is None:
        return None
    kwargs = {}
    if title:
        kwargs["title"] = title
    return viz_fn(df, **kwargs)
