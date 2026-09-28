"""
Chainlit UI for Premier League Analytics Agent v2.

Features:
- Settings panel: Model selection (Claude/GPT-4o) + Variant (Full/Semi/No Control)
- Conversation history in sidebar (session-only)
- Inline Plotly visualizations
- Step-by-step agent execution display
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import uuid
import chainlit as cl
from graph import run_agent
from schema_loader import get_season_names
from agents.manager import manager_agent
from state import create_initial_state
from config import set_trace_context
from memory.vector_store_pg import store_feedback
from memory.trajectory_log import update_thumbs
import pandas as pd


# =============================================================================
# Settings Configuration
# =============================================================================

def get_settings():
    """Define the settings panel configuration."""
    return [
        cl.input_widget.Select(
            id="model",
            label="Model",
            values=["claude", "gpt4o"],
            initial_value="claude",
            description="LLM to use for analysis"
        ),
        cl.input_widget.Select(
            id="variant",
            label="Data Agent Freedom",
            values=["full_control", "semi_control", "no_control"],
            initial_value="semi_control",
            description="SQL generation approach"
        )
    ]


# =============================================================================
# Chat Start
# =============================================================================

@cl.on_chat_start
async def start():
    """Initialize the chat session."""

    # Initialize settings
    settings = await cl.ChatSettings(get_settings()).send()

    # Store in session
    cl.user_session.set("model", "claude")
    cl.user_session.set("variant", "semi_control")
    cl.user_session.set("conversation_history", [])

    # Get available seasons
    seasons = get_season_names()
    seasons_str = ", ".join(seasons)

    # Welcome message
    welcome = f"""Welcome back! Ask me questions about Premier League data.

**Available seasons:** {seasons_str}

*Settings are in the panel above - choose your preferred model and agent approach.*"""

    await cl.Message(content=welcome).send()


# =============================================================================
# Settings Update
# =============================================================================

@cl.on_settings_update
async def settings_update(settings):
    """Handle settings changes."""
    cl.user_session.set("model", settings["model"])
    cl.user_session.set("variant", settings["variant"])

    # Show confirmation
    model_name = "Claude Sonnet 4.5" if settings["model"] == "claude" else "GPT-4o"
    variant_name = {
        "full_control": "Full Control (Structured)",
        "semi_control": "Semi Control (Hybrid)",
        "no_control": "No Control (Agentic)"
    }[settings["variant"]]

    await cl.Message(
        content=f"✓ Settings updated: **{model_name}** | **{variant_name}**",
        author="System"
    ).send()


# =============================================================================
# Message Handler
# =============================================================================

@cl.on_message
async def main(message: cl.Message):
    """Handle user messages."""

    # Assign a unique trace ID for this query — all LLM calls share it in Langfuse
    set_trace_context(str(uuid.uuid4()), trace_name=message.content[:80])

    # Get settings from session
    variant = cl.user_session.get("variant", "semi_control")
    model   = cl.user_session.get("model", "claude")  # now a real arm (A3)

    # -------------------------------------------------------------------------
    # Phase 1: Run manager to classify intent (sync, fast)
    # -------------------------------------------------------------------------
    processing_msg = cl.Message(content="🤔 Classifying your question...")
    await processing_msg.send()

    state = create_initial_state(message.content)
    state = manager_agent(state)

    await processing_msg.remove()

    # -------------------------------------------------------------------------
    # Phase 2: If PL-related data query, ask user about visualization
    # -------------------------------------------------------------------------
    if state.get("is_premier_league_related") and not state.get("error"):
        res = await cl.AskActionMessage(
            content="Do you want a text response with data, or also include a visualization?",
            actions=[
                cl.Action(name="text", label="Text + Data", payload={"intent": "data_request"}),
                cl.Action(name="viz", label="Text + Visualization", payload={"intent": "full_pipeline"}),
            ],
            timeout=60,
        ).send()

        if res is None:
            # Timed out — default to text only
            state["intent"] = "data_request"
        else:
            state["intent"] = res.get("payload", {}).get("intent", "data_request")  # type: ignore

    # -------------------------------------------------------------------------
    # Phase 3: Run the full pipeline with pre-classified state
    # -------------------------------------------------------------------------
    # Initialise variables used after the try block
    final_response = ""
    sql_query = ""
    intent = "conversational"
    data_result = None
    viz_html = None
    viz_figure = None

    processing_msg = cl.Message(content="🤔 Analyzing your question...")
    await processing_msg.send()

    # Create step for agent execution
    async with cl.Step(name="Agent Pipeline", type="run") as step:

        # Step 1: Show manager result
        async with cl.Step(name="Manager: Intent classified", parent_id=step.id):
            intent_label = state.get("intent", "conversational")
            step.output = f"✓ Intent: {intent_label}"

        # Step 2: Run the rest of the pipeline with the pre-classified state
        try:
            result = run_agent(
                user_query=message.content,
                variant=variant,
                verbose=False,
                initial_state=state,
                model=model,
                experiment="live",
                condition="mas",
            )

            # Extract results
            intent = result.get("intent", "unknown")
            is_pl_related = result.get("is_premier_league_related", False)
            error = result.get("error")
            final_response = result.get("final_response", "")
            sql_query = result.get("sql_query", "")
            data_result = result.get("data_result")
            viz_html = result.get("viz_html")
            viz_figure = result.get("viz_figure")

            # Show SQL/Function (if applicable)
            if intent != "conversational" and sql_query:
                async with cl.Step(name="Data Analysis", parent_id=step.id):
                    if sql_query.startswith("Function:"):
                        step.output = f"📦 {sql_query}"
                    else:
                        step.output = f"```sql\n{sql_query[:200]}{'...' if len(sql_query) > 200 else ''}\n```"

            # Step 5: Show data shape (if applicable)
            if data_result is not None and isinstance(data_result, pd.DataFrame):
                if not data_result.empty:
                    async with cl.Step(name="Data Retrieved", parent_id=step.id):
                        step.output = f"✓ {data_result.shape[0]} rows × {data_result.shape[1]} columns"
                else:
                    async with cl.Step(name="Data Retrieved", parent_id=step.id):
                        step.output = "⚠️ Query returned no results"

            # Step 6: Visualization (if applicable)
            if viz_html:
                async with cl.Step(name="Visualization Generated", parent_id=step.id):
                    step.output = f"✓ {result.get('viz_type', 'chart')} created"

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            step.output = f"❌ Error: {str(e)}"

            # Show detailed error
            error_msg = f"An error occurred: {str(e)}\n\n```\n{error_details[:500]}\n```"
            await cl.Message(content=error_msg).send()
            return

    # Update processing message
    await processing_msg.remove()

    # Build response message
    elements = []

    # Add visualization if present (viz_figure set inside try block above)
    if viz_figure is not None:
        elements.append(cl.Plotly(figure=viz_figure, name="chart"))

    # Add data table if present (show up to 50 rows)
    if data_result is not None and isinstance(data_result, pd.DataFrame) and not data_result.empty:
        if len(data_result) <= 50:
            # Format as markdown table for small results
            try:
                table_md = "\n\n**Data:**\n```\n" + data_result.to_string(index=False) + "\n```"
                final_response += table_md
            except Exception as e:
                final_response += f"\n\n*(Could not display table: {str(e)})*"
        else:
            final_response += f"\n\n**Data:** {len(data_result)} rows (showing first 10):\n```\n{data_result.head(10).to_string(index=False)}\n```"

    # Send final response
    response_msg = cl.Message(
        content=final_response if final_response else "No response generated.",
        elements=elements if elements else None
    )
    await response_msg.send()

    # Store in conversation history
    history = cl.user_session.get("conversation_history", [])
    history.append({
        "user": message.content,
        "assistant": final_response,
        "intent": intent,
        "sql": sql_query if sql_query else None
    })
    cl.user_session.set("conversation_history", history)

    # Store memory_id and last query for feedback handler
    memory_id = result.get("memory_id") if "result" in dir() else None
    if memory_id:
        cl.user_session.set("last_memory_id", memory_id)
        cl.user_session.set("last_query", message.content)
        cl.user_session.set("last_variant", variant)




# =============================================================================
# Thumbs Feedback Handler
# =============================================================================

@cl.on_message_feedback
async def feedback(feedback: cl.MessageFeedback):
    """Handle thumbs up/down feedback — write to Aiven feedback table."""
    memory_id = cl.user_session.get("last_memory_id")
    user_query = cl.user_session.get("last_query", "")
    variant    = cl.user_session.get("last_variant", "unknown")

    if not memory_id:
        return

    score = 1 if feedback.value == "LIKE" else -1

    try:
        store_feedback(
            memory_id  = memory_id,
            user_query = user_query,
            score      = score,
            variant    = variant,
        )
    except Exception:
        pass  # best-effort — never surface storage errors to user

    # Patch the thumbs onto the turn's trajectory row (bandit/preference substrate).
    try:
        update_thumbs(memory_id, score)
    except Exception:
        pass


if __name__ == "__main__":
    # For local testing
    import os
    os.environ["CHAINLIT_HOST"] = "0.0.0.0"
    os.environ["CHAINLIT_PORT"] = "8000"