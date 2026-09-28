"""
qualitative_spotcheck.py — LIGHT spot-check for the qualitative-reasoning arm.

NOT a formal golden set and NOT part of the deterministic 46+4 benchmark (which is
untouched). Runs a handful of open-ended narrative questions through the live agent,
then LLM-judges each answer for GROUNDEDNESS (is every claim supported by the
retrieved `documents` passages?) and hallucination. Open-ended answers have no single
correct value, so there is no accuracy/Brier here — the point is: does the agent (a)
route narrative questions to the qualitative path, (b) answer only from retrieved
text, and (c) refuse gracefully when it has no background?

Prereqs:
  - documents table seeded:  python ../data_prep/ingest_wikipedia.py
  - Ethan/agent_v4/.env with DATABASE_URI + ANTHROPIC_API_KEY

Run:  cd Ethan/agent_v4 && python eval/qualitative_spotcheck.py
      python eval/qualitative_spotcheck.py --judge-model gpt4o   # cross-family judge
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_AGENT_V4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AGENT_V4))
load_dotenv(_AGENT_V4 / ".env", override=True)

from graph import run_agent            # noqa: E402
from config import call_llm, get_model  # noqa: E402
from agents.synthesizer import _format_narrative  # noqa: E402

QUESTIONS = _AGENT_V4 / "eval" / "qualitative_spotcheck.json"
OUT_SUMMARY = _AGENT_V4 / "eval" / "qualitative_spotcheck_summary.txt"


JUDGE_PROMPT = """You are grading a football assistant's answer for GROUNDEDNESS.

Question: "{question}"

Retrieved passages the assistant was given:
---
{passages}
---

Assistant's answer:
---
{answer}
---

Decide how well the answer is grounded in the passages. If the assistant had NO passages
and correctly declined to answer (said it lacks the background), grade that as GROUNDED.
Penalise any claim not supported by the passages (hallucination).

Respond in EXACTLY this format:
VERDICT: [GROUNDED/PARTIAL/HALLUCINATED]
HALLUCINATIONS: [count of unsupported factual claims, an integer]
REASON: [one sentence]"""


def judge(question: str, passages: str, answer: str, judge_model: str) -> dict:
    prompt = JUDGE_PROMPT.format(question=question, passages=passages or "(none)", answer=answer)
    # call_llm expects a full LiteLLM id; resolve the family key ('claude'/'gpt4o').
    model_id = get_model(judge_model) if judge_model in ("claude", "gpt4o") else judge_model
    resp = call_llm([{"role": "user", "content": prompt}], model=model_id, temperature=0.0)
    out = {"verdict": "?", "hallucinations": None, "reason": ""}
    for line in resp.strip().splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().upper(), v.strip()
        if k == "VERDICT":
            out["verdict"] = v.upper()
        elif k == "HALLUCINATIONS":
            try:
                out["hallucinations"] = int("".join(ch for ch in v if ch.isdigit()) or "0")
            except ValueError:
                out["hallucinations"] = None
        elif k == "REASON":
            out["reason"] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Light qualitative spot-check")
    ap.add_argument("--judge-model", default="claude",
                    help="model family for the judge (default 'claude'; use 'gpt4o' for cross-family)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    data = json.loads(QUESTIONS.read_text())
    qs = data["questions"][: args.limit] if args.limit else data["questions"]

    rows, lines = [], []
    grounded = 0
    routed_ok = 0
    print(f"Qualitative spot-check — {len(qs)} questions "
          f"(judge={args.judge_model})\n{'='*70}")

    for q in qs:
        state = run_agent(q["question"], verbose=False)
        intent = state.get("intent")
        answer = state.get("final_response", "")
        narrative = state.get("narrative_context", []) or []
        passages = _format_narrative(narrative, max_docs=6)

        # For the fictional-player probe we EXPECT no narrative + a graceful refusal.
        is_refusal_case = q.get("expects") == "no_narrative_available"
        routed = (intent == "qualitative")
        routed_ok += int(routed)

        v = judge(q["question"], passages, answer, args.judge_model)
        grounded += int(v["verdict"] == "GROUNDED")

        line = (f"[{q['id']}] intent={intent} docs={len(narrative)} "
                f"verdict={v['verdict']} halluc={v['hallucinations']}"
                + ("  (refusal-case)" if is_refusal_case else ""))
        print(line)
        print(f"      Q: {q['question']}")
        print(f"      A: {answer[:160].replace(chr(10), ' ')}")
        print(f"      judge: {v['reason']}\n")
        lines.append(line)
        rows.append({"id": q["id"], "intent": intent, "n_docs": len(narrative), **v})

    n = len(qs)
    summary = (
        f"\n{'='*70}\nSUMMARY  (n={n})\n"
        f"  routed to qualitative : {routed_ok}/{n}\n"
        f"  judged GROUNDED       : {grounded}/{n}\n"
        f"  judge model           : {args.judge_model}\n"
        "NOTE: light spot-check, not a scored benchmark. GROUNDED includes correct "
        "refusals on topics with no retrieved background.\n"
    )
    print(summary)
    OUT_SUMMARY.write_text("\n".join(lines) + "\n" + summary)
    print(f"Wrote {OUT_SUMMARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
