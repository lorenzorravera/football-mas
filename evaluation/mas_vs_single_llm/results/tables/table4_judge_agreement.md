# Table 4 — Judge–human agreement

**N/A for this golden set.** All 46 questions have deterministic SQL ground truth and are scored programmatically (scalar / ranking / table / denial) against frozen `ground_truth.json` — no LLM-as-judge was used, so there is no judge-vs-human agreement to report. The LLM judge (different model family) is reserved for genuine free-text questions, of which there are none here. If free-text items are added later, `eval/judge_validation.py` populates this table.
