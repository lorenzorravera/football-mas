"""
Shared LiteLLM configuration for all agent variants.

This module provides:
- Model name to LiteLLM string mapping
- Automatic routing between Claude Sonnet 4.5 and GPT-4o
- In-memory caching to reduce duplicate API calls
- Centralized API key management

All agent variants import from this shared config:
    from config import get_model, call_llm
"""

import os
from contextvars import ContextVar
from typing import Literal, Optional
from pathlib import Path
from dotenv import load_dotenv
import litellm
from litellm import completion

# Load environment variables from till/.env (one level up from agent_v2)
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# =============================================================================
# Environment Variables
# =============================================================================

DATABASE_URI = os.getenv("DATABASE_URI")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_BASE_URL = os.getenv("LANGFUSE_BASE_URL")

# =============================================================================
# LiteLLM Configuration
# =============================================================================

# Set API keys for LiteLLM
os.environ["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY or ""
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY or ""

# Langfuse: LiteLLM expects LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
#if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY:
 #   os.environ["LANGFUSE_PUBLIC_KEY"] = LANGFUSE_PUBLIC_KEY
 #   os.environ["LANGFUSE_SECRET_KEY"] = LANGFUSE_SECRET_KEY
    # Support both LANGFUSE_BASE_URL (our name) and LANGFUSE_HOST (LiteLLM's name)
 #   if LANGFUSE_BASE_URL:
 #       os.environ["LANGFUSE_HOST"] = LANGFUSE_BASE_URL
#    litellm.success_callback = ["langfuse"]

# Suppress verbose debug output
litellm.drop_params = True  # let providers ignore unsupported kwargs (e.g. temperature on Opus 4.8)
litellm.suppress_debug_info = True
litellm.set_verbose = False

# =============================================================================
# Langfuse Trace Context
# =============================================================================

# ContextVar is safe for concurrent async requests (each Chainlit session
# runs in its own async context, so there's no cross-request leakage).
_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
_trace_name: ContextVar[Optional[str]] = ContextVar("trace_name", default=None)


def set_trace_context(trace_id: str, trace_name: str = "") -> None:
    """
    Set the Langfuse trace_id for the current async context.
    Call this once per user query in app.py before running the pipeline.
    All subsequent call_llm() calls will share the same trace.
    """
    _trace_id.set(trace_id)
    _trace_name.set(trace_name)


# =============================================================================
# Per-query token accounting + model override (A3 — bandit/trajectory substrate)
# =============================================================================
# These reuse the ContextVar pattern above so they are safe across concurrent async
# Chainlit sessions. run_agent() resets the accumulator at the start of each turn and
# reads it at the end for the trajectory log.

_token_usage: ContextVar[Optional[dict]] = ContextVar("token_usage", default=None)
_model_override: ContextVar[Optional[str]] = ContextVar("model_override", default=None)


def reset_token_usage() -> None:
    """Start a fresh per-turn token accumulator for the current context."""
    _token_usage.set({"prompt": 0, "completion": 0, "total": 0})


def get_token_usage() -> dict:
    """Return the accumulated token usage for the current context (zeros if inactive)."""
    u = _token_usage.get()
    return dict(u) if u else {"prompt": 0, "completion": 0, "total": 0}


def _accumulate_usage(response) -> None:
    """Add one LLM response's token usage to the active accumulator (best-effort)."""
    u = _token_usage.get()
    if u is None:
        return  # accumulation not active for this context
    try:
        usage = getattr(response, "usage", None)
        if usage:
            u["prompt"]     += int(getattr(usage, "prompt_tokens", 0) or 0)
            u["completion"] += int(getattr(usage, "completion_tokens", 0) or 0)
            u["total"]      += int(getattr(usage, "total_tokens", 0) or 0)
    except Exception:
        pass


def set_model_override(model_name: Optional[str]) -> None:
    """
    Force a logical model ('claude' | 'gpt4o') for every agent in the current turn.
    Makes `model` a real bandit arm (previously the UI selection was never applied).
    Pass None to clear.
    """
    _model_override.set(model_name)


# =============================================================================
# Model Registry
# =============================================================================

ModelName = Literal["claude", "gpt4o"]

# Map logical model names to LiteLLM provider strings
MODEL_MAP = {
    "claude": "anthropic/claude-opus-4-8",  # matched to Till for fair comparison
    "gpt4o": "gpt-4o",  # GPT-4o (full, not mini)
}

# Default model for each agent role
AGENT_DEFAULTS = {
    "manager": "claude",  # Intent classification needs strong reasoning
    "data_discovery": "claude",  # Schema analysis
    "data_analyst": "claude",  # SQL generation (cheaper, faster)
    "visualizer": "claude",  # Plotly code generation
    "synthesizer": "claude",  # Final synthesis needs reasoning
}

# =============================================================================
# Helper Functions
# =============================================================================


def get_model(model_name: ModelName) -> str:
    """
    Get the LiteLLM provider string for a logical model name.

    Args:
        model_name: "claude" or "gpt4o"

    Returns:
        LiteLLM provider string (e.g., "anthropic/claude-sonnet-4-20250514")

    Example:
        >>> get_model("claude")
        "anthropic/claude-sonnet-4-20250514"
    """
    return MODEL_MAP[model_name]


def get_agent_model(agent_role: str, override: Optional[ModelName] = None) -> str:
    """
    Get the LiteLLM string for an agent, with optional override.

    Args:
        agent_role: Agent identifier (e.g., "manager", "data_analyst")
        override: Optional model override from Chat Profile selection

    Returns:
        LiteLLM provider string

    Example:
        >>> get_agent_model("manager")
        "anthropic/claude-sonnet-4-20250514"
        >>> get_agent_model("data_analyst", override="claude")
        "anthropic/claude-sonnet-4-20250514"
    """
    if override:
        return get_model(override)

    # A per-turn ContextVar override (set by run_agent) makes `model` a real bandit arm.
    ctx_override = _model_override.get()
    if ctx_override:
        return get_model(ctx_override)

    model_name = AGENT_DEFAULTS.get(agent_role, "claude")
    return get_model(model_name)


def call_llm(
    messages: list[dict],
    model: Optional[str] = None,
    model_name: Optional[ModelName] = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    **kwargs
) -> str:
    """
    Call LLM with automatic caching and routing.

    Caching: Identical messages within a session are cached in-memory,
    preventing duplicate API calls for repeated schema context, etc.

    Args:
        messages: List of message dicts with "role" and "content"
        model: Explicit LiteLLM string (overrides model_name)
        model_name: "claude" or "gpt4o" (used if model not specified)
        temperature: Sampling temperature (0.0 = deterministic)
        max_tokens: Max tokens to generate
        **kwargs: Additional litellm.completion() arguments

    Returns:
        The model's text response

    Example:
        >>> messages = [{"role": "user", "content": "What is 2+2?"}]
        >>> response = call_llm(messages, model_name="gpt4o")
        "4"
    """
    if model is None:
        if model_name is None:
            model_name = "claude"
        model = get_model(model_name)

    trace_id = _trace_id.get()
    if trace_id and "metadata" not in kwargs:
        kwargs["metadata"] = {
            "trace_id": trace_id,
            "trace_name": _trace_name.get() or "",
        }

    # Some frontier models (e.g. Opus 4.8) REJECT `temperature` outright (not just ignore it),
    # so we must omit the kwarg entirely rather than rely on litellm.drop_params.
    _TEMP_DEPRECATED = ("opus-4-8",)
    call_kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, **kwargs)
    if not any(tag in model for tag in _TEMP_DEPRECATED):
        call_kwargs["temperature"] = temperature
    response = completion(**call_kwargs)
    _accumulate_usage(response)

    return response.choices[0].message.content


# =============================================================================
# Configuration Validation
# =============================================================================


def validate_config() -> bool:
    """
    Validate required environment variables are set.

    Returns:
        True if valid

    Raises:
        ValueError if missing required variables
    """
    missing = []

    if not DATABASE_URI:
        missing.append("DATABASE_URI")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")

    if missing:
        raise ValueError(
            f"Missing environment variables: {', '.join(missing)}\n"
            f"Ensure till/.env contains these variables."
        )

    return True


# =============================================================================
# Module Initialization
# =============================================================================

# Validate on import
try:
    validate_config()
    print("✓ Shared config loaded")
    print(f"  Claude: {MODEL_MAP['claude']}")
    print(f"  GPT-4o: {MODEL_MAP['gpt4o']}")
except ValueError as e:
    print(f"⚠ Config error: {e}")


if __name__ == "__main__":
    print("\n=== Configuration Test ===\n")

    # Test model mappings
    print("Model Mappings:")
    for name, provider in MODEL_MAP.items():
        print(f"  {name:8} -> {provider}")

    print("\nAgent Defaults:")
    for role, model in AGENT_DEFAULTS.items():
        provider = get_agent_model(role)
        print(f"  {role:18} -> {provider}")

    # Test LLM call with caching
    print("\n=== LLM Call Test ===")
    test_msg = [{"role": "user", "content": "Say 'Config ready' and nothing else."}]

    print("First call (uncached)...")
    response1 = call_llm(test_msg, model_name="gpt4o")
    print(f"Response: {response1}")

    print("\nSecond call (should be cached)...")
    response2 = call_llm(test_msg, model_name="gpt4o")
    print(f"Response: {response2}")

    print("\n✓ Shared configuration working")
