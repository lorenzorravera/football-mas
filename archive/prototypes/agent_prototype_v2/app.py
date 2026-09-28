import chainlit as cl
import chainlit.data as cl_data
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from graph import app  # your existing LangGraph workflow
import os

# --- Persistent memory: point to your existing PostgreSQL ---
cl_data._data_layer = SQLAlchemyDataLayer(
    conninfo=os.getenv("DATABASE_URI")
)

@cl.on_chat_start
async def on_chat_start():
    # Cache the graph once per session
    cl.user_session.set("graph", app)
    await cl.Message(
        content="⚽ Welcome to Football Analytics Agent! Ask me anything."
    ).send()

@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")

    # Show a loading indicator
    async with cl.Step(name="Thinking..."):
        result = graph.invoke({
            "user_query": message.content,
            "errors": []
        })

    # Handle errors
    if result.get("errors"):
        await cl.Message(content=f"⚠️ {result['errors']}").send()
        return

    # Send analytics as text
    if result.get("analytics_results"):
        await cl.Message(content=str(result["analytics_results"])).send()

    # Send visualizations as Plotly charts
    if result.get("visualizations"):
        for fig in result["visualizations"]:
            elements = [cl.Plotly(name="chart", figure=fig, display="inline")]
            await cl.Message(content="", elements=elements).send()