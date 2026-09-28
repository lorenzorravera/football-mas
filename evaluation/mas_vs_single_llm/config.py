"""
config.py — shared model routing for agent_v5 (LiteLLM).

Three model families for the 9-cell experiment: claude / gpt / gemini.
`call_llm` does plain text completion; `call_llm_tools` does OpenAI-style function-calling
(works across providers via LiteLLM). Temperature defaults follow the spec (SQL-generating paths
run at ~0.3 to surface routing variance, not 0).

⚠️ MODEL IDS ARE PROPOSED — confirm with Till before any live/scored run. They are plain config
strings, so changing them needs no code edits. Keys come from till/agent_v5/.env.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
import litellm
from litellm import completion

# agent_v5/.env supplies DATABASE_URI (loaded first so it wins); till/.env supplies the API keys.
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

litellm.suppress_debug_info = True
litellm.set_verbose = False
litellm.drop_params = True  # let providers ignore unsupported kwargs (e.g. temperature on some)

# --------------------------------------------------------------------------- #
# Langfuse tracing (optional — enabled when keys are present)
# --------------------------------------------------------------------------- #
LANGFUSE_ENABLED = False
if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
    os.environ["LANGFUSE_PUBLIC_KEY"] = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    os.environ["LANGFUSE_SECRET_KEY"] = os.getenv("LANGFUSE_SECRET_KEY", "")
    if os.getenv("LANGFUSE_BASE_URL"):  # LiteLLM expects LANGFUSE_HOST
        os.environ["LANGFUSE_HOST"] = os.getenv("LANGFUSE_BASE_URL", "")
    try:
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        LANGFUSE_ENABLED = True
    except Exception:  # noqa: BLE001
        LANGFUSE_ENABLED = False

# Per-run trace context (safe for concurrent async contexts). The runner sets this once per run;
# every nested call_llm attaches the same trace_id so all generations group under one Langfuse trace.
_trace_ctx: ContextVar[dict] = ContextVar("trace_ctx", default={})
# Per-run token accumulator (reset on set_trace_context; read via get_token_usage before clearing).
_token_ctx: ContextVar[dict] = ContextVar("token_ctx", default={})


def set_trace_context(trace_id: str, trace_name: str = "", tags: Optional[list] = None) -> None:
    _trace_ctx.set({"trace_id": trace_id, "trace_name": trace_name, "tags": tags or []})
    _token_ctx.set({"input": 0, "output": 0, "total": 0, "calls": 0})


def clear_trace_context() -> None:
    _trace_ctx.set({})


def get_token_usage() -> dict:
    return dict(_token_ctx.get() or {})


def _accumulate_usage(resp) -> None:
    u = getattr(resp, "usage", None)
    d = _token_ctx.get()
    if not u or not d:
        return
    d["input"] += getattr(u, "prompt_tokens", 0) or 0
    d["output"] += getattr(u, "completion_tokens", 0) or 0
    d["total"] += getattr(u, "total_tokens", 0) or 0
    d["calls"] += 1

# --------------------------------------------------------------------------- #
# Model registry — logical family name -> LiteLLM model id. *** CONFIRM THESE ***
# --------------------------------------------------------------------------- #
MODEL_REGISTRY: dict[str, str] = {
    "claude": "anthropic/claude-opus-4-8",        # Till's choice. NOTE: temperature is DEPRECATED -> omitted.
    "gpt":    "gpt-5.5",                          # Till's choice. NOTE: only temperature=1 -> omitted.
    "gemini": "gemini/gemini-3.1-pro-preview",     # Till's choice. Thinking model -> give generous max_tokens.
}
MODEL_FAMILIES = list(MODEL_REGISTRY)

DEFAULT_SQL_TEMPERATURE = 0.3   # requested by the SQL paths, but see NO_CUSTOM_TEMP below

# All three chosen frontier models deprecate/restrict `temperature` (only =1, or removed). For these
# we OMIT the temperature param entirely and let the model use its default. Methodology note for the
# paper: temperature is each model's default, NOT a fixed 0.3, because the chosen models don't expose it.
NO_CUSTOM_TEMP_PATTERNS = ("opus-4", "gpt-5", "gemini-3")
DEFAULT_MAX_TOKENS = 4096        # generous, so thinking models (Gemini 3) return content not just reasoning


def resolve_model(model: str) -> str:
    """Accept a family key ('claude') or a full LiteLLM id and return the LiteLLM id."""
    return MODEL_REGISTRY.get(model, model)


def _supports_custom_temp(model_id: str) -> bool:
    return not any(pat in model_id for pat in NO_CUSTOM_TEMP_PATTERNS)


def _trace_meta(trace_id: Optional[str]) -> dict:
    ctx = _trace_ctx.get()
    tid = trace_id or ctx.get("trace_id")
    if not tid:
        return {}
    return {"metadata": {"trace_id": tid, "trace_name": ctx.get("trace_name", ""),
                         "tags": ctx.get("tags", [])}}


def _kwargs(model_id: str, temperature: float, max_tokens: Optional[int], trace_id: Optional[str]) -> dict:
    kw = {"max_tokens": max_tokens or DEFAULT_MAX_TOKENS, **_trace_meta(trace_id)}
    if _supports_custom_temp(model_id):
        kw["temperature"] = temperature
    return kw


def call_llm(messages: list[dict], model: str, temperature: float = 0.0,
             max_tokens: Optional[int] = None, trace_id: Optional[str] = None) -> str:
    """Plain text completion. Returns the assistant text."""
    mid = resolve_model(model)
    resp = completion(model=mid, messages=messages, **_kwargs(mid, temperature, max_tokens, trace_id))
    _accumulate_usage(resp)
    return resp.choices[0].message.content or ""


def call_llm_tools(messages: list[dict], model: str, tools: list[dict],
                   temperature: float = 0.0, max_tokens: Optional[int] = None,
                   trace_id: Optional[str] = None) -> Any:
    """
    Function-calling completion. `tools` are OpenAI-style tool specs:
        {"type": "function", "function": {"name", "description", "parameters"}}
    Returns the raw assistant message (has .content and .tool_calls).
    """
    mid = resolve_model(model)
    resp = completion(model=mid, messages=messages, tools=tools, tool_choice="auto",
                      **_kwargs(mid, temperature, max_tokens, trace_id))
    _accumulate_usage(resp)
    return resp.choices[0].message


def validate_keys() -> dict:
    """Report which family API keys are present (does not call any API)."""
    return {
        "claude": bool(os.getenv("ANTHROPIC_API_KEY")),
        "gpt": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
    }


if __name__ == "__main__":
    print("Model registry (PROPOSED — confirm before scored runs):")
    for fam, mid in MODEL_REGISTRY.items():
        print(f"  {fam:8} -> {mid}")
    print("API keys present:", validate_keys())
