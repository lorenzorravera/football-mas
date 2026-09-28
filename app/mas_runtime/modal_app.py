"""
Modal deployment for Premier League Agent v2.

Deploys the Chainlit UI as a serverless web app on Modal.
Secrets are managed via Modal's web interface.
"""

import modal
from pathlib import Path

# Resolve local paths relative to this file
_HERE = Path(__file__).parent        # till/agent_v2/
_DB_DIR = _HERE.parent / "db"        # till/db/


# =============================================================================
# Container Image
# =============================================================================

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "chainlit==2.9.6",
        "langgraph>=0.2.0",
        "litellm==1.82.0",
        "pandas>=2.0.0",
        "plotly>=5.0.0",
        "langfuse<3.0.0",       # litellm 1.82.0 uses langfuse v2 API (sdk_integration kwarg)
        "statsmodels",          # required for plotly trendline="ols"
        "sqlalchemy>=2.0.0",
        "psycopg2-binary",
        "python-dotenv",
        "pyyaml",
    )
    # Add local source directories into the image (replaces modal.Mount in v1.x)
    .add_local_dir(_HERE, remote_path="/app/agent_v2")
    .add_local_dir(_DB_DIR, remote_path="/app/db")
)


# =============================================================================
# Modal App
# =============================================================================

app = modal.App("premier-league-agent-v2")


# =============================================================================
# Secrets
# =============================================================================

# Secrets are configured in the Modal web UI under "Secrets".
# Required secrets:
#   pl-agent-database  → DATABASE_URI
#   pl-agent-anthropic → ANTHROPIC_API_KEY
#   pl-agent-openai    → OPENAI_API_KEY

REQUIRED_SECRETS = [
    modal.Secret.from_name("pl-agent-database"),
    modal.Secret.from_name("pl-agent-anthropic"),
    modal.Secret.from_name("pl-agent-openai"),
    modal.Secret.from_name("pl-agent-langfuse"),   # LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL
]


# =============================================================================
# Web Application
# =============================================================================

@app.function(
    image=image,
    secrets=REQUIRED_SECRETS,
    timeout=600,
)
@modal.concurrent(max_inputs=10)
@modal.web_server(port=8000, startup_timeout=120)
def chainlit_server():
    """
    Start Chainlit on port 8000. Modal proxies HTTPS traffic to it.

    URL after deploy:
        https://<workspace>--premier-league-agent-v2-chainlit-server.modal.run
    """
    import os
    import subprocess
    import sys  # for stdout/stderr passthrough

    env = {
        **os.environ,
        # Add /app to PYTHONPATH so `from db.connection import ...` resolves
        "PYTHONPATH": "/app:" + os.environ.get("PYTHONPATH", ""),
    }

    # Start Chainlit and return immediately — Modal polls port 8000 until open,
    # then routes traffic. The subprocess keeps the container alive.
    subprocess.Popen(
        [
            "chainlit", "run", "app.py",
            "--host", "0.0.0.0",
            "--port", "8000",
        ],
        cwd="/app/agent_v2",
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


# =============================================================================
# Deployment Instructions
# =============================================================================

"""
DEPLOY:
    modal deploy till/agent_v2/modal_app.py

LOGS:
    modal app logs premier-league-agent-v2

STOP:
    modal app stop premier-league-agent-v2
"""
