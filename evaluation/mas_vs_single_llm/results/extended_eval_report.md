# Extended evaluation — MAS vs single-LLM baselines (Opus 4.8)

Single run per condition on the **extended, re-scoped, content-hashed** golden set (60 items = 30
data-analysis + 30 prediction). Model: `anthropic/claude-opus-4-8`, memory OFF, autonomous MAS.

- Golden set: `results/golden/golden_set_v2.json` — 30 DA, sha256 `1ceb52a2…`, 18 in-coverage / 12 out-of-coverage
- Ground truth: `results/golden/ground_truth_v2.json` — sha256 `ea0e26fe…`
- Prediction set: `results/golden/prediction_golden_v2.json` — 30 fixtures, sha256 `9bf47dc4…`
- Originating git commit: `b000fb5` (working tree dirty — the v5 harness code that produced these
  artifacts is uncommitted; the sha256 is the integrity anchor, as with the v1 freeze)
- Per-question raw runs: `results/runs/extended_da/`, `results/runs/extended_pred/` (one file per
  question × condition, persisted **before** scoring)
- Scores: `results/scores/extended_da_scores.json`, `extended_pred_scores.json`
- Stats: `results/stats/extended_mcnemar.json`

Ground-truth isolation is preserved: no agent sees `ground_truth_v2.json`; scoring reads stored runs
+ frozen ground truth only, never re-running a model.

---

## 0. Two things found before running (read this first)

### 0a. The 40-vs-41 discrepancy — resolved: run-to-run nondeterminism

The previous draft had autonomous Opus at **40/46** in Experiment 1 (DoF, `autonomous` mode) and
**41/46** in Experiment 2 (MAS-vs-single, `mas` condition). These are two *independent* stochastic
invocations of the **identical** autonomous-MAS configuration. They differ on exactly **one**
question, **Q03** ("full 2022-2023 league table"):

- Experiment 1's run wrote `SELECT tss_rank, tss_team, tss_points …` using the **denormalized**
  `tss_team` column → "Manchester Utd", "Newcastle". The scorer matches the **canonical** ground-truth
  names ("Manchester United", "Newcastle United"), so that 20-row ranking scored `partial`.
- Experiment 2's run joined `teams` for the **canonical** `team_name` → scored `correct`.

Cause: the autonomous analyst generates its own SQL at the model's default temperature (Opus
deprecates the `temperature` param, so it is omitted → non-zero), and the two experiments ran it
twice. Not a bug, not a different question set, not a scoring inconsistency (`score_run` and
`score_run_text` both give 40 for Experiment 1's stored run and 41 for Experiment 2's).

**Fix applied here:** the autonomous MAS is run **exactly once** per question; there is no separate
DoF-vs-MVS duplicate. "The same config on the same question" therefore yields one number by
construction. This rerun is internally consistent.

### 0b. The eval DB drifted from PL-only to five leagues (larger issue)

The Aiven DB was **repopulated from ENG-PL-only to five leagues** (ENG-PL, ESP-LL, ITA-SA, GER-BL,
FRA-L1) **plus international tables** *after* the original 46-item set was frozen. Consequences on
the live DB:

- **30 of 46** original canonical SQLs returned results different from the frozen (PL-only) ground
  truth, because they filtered on `season='YYYY-YYYY'` only — every league has a row for that season
  label. E.g. Q01 "who won the PL 2024-2025" returned **five** champions (Liverpool, Barcelona,
  Napoli, Bayern, PSG).
- The agent-facing schema context still asserted "Data covers ENG-PL ONLY … 27 teams" — false, so an
  agent run as-is would be told PL-only, write season-only SQL, and silently get 5-league data.
- The old 40/41 runs were produced on the *old PL-only* DB (their stored runs show 20-row PL tables),
  so they are **not comparable** to anything run against today's DB.

**Resolution (approved: "re-scope to ENG-PL on current DB"):** every canonical SQL in the extended
set is explicitly scoped to ENG-PL (`seasons.competition_id = 1`; text-keyed transfer/injury tables
restricted to ENG-PL club names). The agent schema context (`tools/schema_context.py`) and the
single-LLM raw-data dump (`conditions/single_llm.py`) were updated to state the DB is multi-league
and that queries must scope to ENG-PL. Ground truth = result of executing the re-scoped SQL on the
current DB.

**Validation:** 29/30 re-scoped queries reproduce the original PL-only frozen answers **exactly**;
only Q32 differs, and only because the transfers table legitimately grew (2025-2026 windows added,
plus a duplicate-name row that we deduplicate). This confirms the re-scoping is correct.

> Caveat for the paper: this rerun measures the agents on the current multi-league DB with ENG-PL
> scoping. The numbers below are **not** directly comparable to the historical 40/41 (different DB
> substrate).

---

## 1. Data-analysis accuracy (30 questions, answer-text scoring)

Scoring is condition-agnostic (final-answer text vs ground-truth rows), applied identically to all
three conditions.

| Condition | Overall | In-coverage (18) | Out-of-coverage (12) | Raw-answerable subset (20) |
|---|---|---|---|---|
| **MAS** (autonomous) | **26/30 (87%)** | 16/18 (89%) | 10/12 (83%) | 20/20 (100%) |
| **Single-LLM + tools** | **26/30 (87%)** | 14/18 (78%) | 12/12 (100%) | 20/20 (100%) |
| **Single-LLM + raw data** | 21/30 (70%) | 14/18 (78%) | 7/12 (58%) | 20/20 (100%) |

Notes:
- **MAS and single-LLM+tools tie overall at 26/30.** They are *not* identical question-by-question
  (see §3) — they trade wins on 4 questions — but the totals match.
- **Single-LLM+raw-data** is scored on its answerable subset ("only answerable subset applies"): the
  raw dump inlines only the ENG-PL team-/player-season tables, so market/transfer, injury, event, and
  referee questions are unanswerable by construction. On the 20 answerable items it scores **20/20**;
  its lower overall/out-of-coverage numbers are driven entirely by the 10 items whose source data is
  not in the dump (it correctly says the data is absent, which scores `wrong` against a non-empty GT).
- The out-of-coverage column did **not** show the hypothesised MAS advantage — see §3.

---

## 2. Prediction (30 fixtures, descriptive only — NO significance test)

Per the design: both MAS and single-LLM+tools do single-pass parameter extraction and then call the
**same** `predict_match_outcome`, so their forecast outputs are **identical by construction** — zero
discordant pairs, so a paired test is undefined. Reported descriptively:

| Condition | Delegation fidelity | Mean Brier vs actual | Mean tokens | Mean latency |
|---|---|---|---|---|
| **MAS** | **30/30** delegated, 30/30 report the model vector faithfully | **0.1973** | 1,008 | 6.8 s |
| **Single-LLM + tools** | **30/30** delegated, 30/30 faithful | **0.1973** | 42,912 | 13.0 s |
| **Single-LLM + raw data** (LLM-as-forecaster) | 0/30 (by design — no model) | 0.1960 | 1,204 | 7.7 s |

- **Confirmed: MAS and single-LLM+tools produced identical forecast vectors on all 30/30 fixtures.**
  The two conditions are indistinguishable on the prediction slice; the MAS orchestration adds nothing
  (and costs more only in the single-LLM+tools case, which burns tokens exploring the DB before
  delegating).
- Reference points: the trained model's Brier on these 30 fixtures is **0.1973**; a uniform 1/3
  forecast scores 0.2222. Both the model and the raw-data LLM-forecaster beat uniform; on this sample
  the LLM-forecaster (0.1960) is statistically indistinguishable from the model (0.1973).

---

## 3. Paired significance — McNemar exact (DATA-ANALYSIS only): MAS vs single-LLM+tools

Exact binomial McNemar (two-sided) on the discordant pairs — the chi-square approximation is invalid
here because the discordant count is < 10.

### Overall (n = 30)

|  | single+tools right | single+tools wrong |
|---|---|---|
| **MAS right** | 24 (both right) | **2** (MAS-only) = *b* |
| **MAS wrong** | **2** (single-only) = *c* | 2 (both wrong) |

- b = 2, c = 2, discordant = 4
- **Exact McNemar p = 1.0** → **not significant**
- McNemar odds ratio b/c = 1.0 (no directional effect); accuracy Δ = 0.0 (0.867 vs 0.867)

### Out-of-coverage (n = 12) — where the effect was expected

|  | single+tools right | single+tools wrong |
|---|---|---|
| **MAS right** | 10 (both right) | **0** (MAS-only) = *b* |
| **MAS wrong** | **2** (single-only) = *c* | 0 (both wrong) |

- b = 0, c = 2, discordant = 2
- **Exact McNemar p = 0.5** → **not significant**
- Direction, if anything, **favours single-LLM+tools** here (b/c = 0; MAS 10/12 vs single 12/12).

*(In-coverage, n = 18: b = 2, c = 0, p = 0.5, not significant — direction favours MAS but far from
significant.)*

The four discordant DA questions — and, crucially, **two of the four are scorer artifacts, not real
differences** (verified by reading the stored answers):

| Q | Coverage | Scored winner | Substantive reality |
|---|---|---|---|
| Q33 | in | MAS | **Scorer artifact.** Single+tools *was correct* ("Declan Rice … West Ham United to Arsenal, £116.6 million") but wrote the fee as "116.6 million"; the numeric scorer did not match that to `116600000`. |
| Q45 | in | MAS | **Scorer artifact.** Single+tools *was correct* ("Norwich City did **not** play … no points"), but the markdown `**not**` broke the denial-phrase substring match. |
| Q25 | out | single+tools | **Genuine MAS error.** MAS free-SQL filtered `referee = 'Anthony Taylor'` without normalizing the non-breaking space → 0 matches (GT = 27). |
| Q42 | out | single+tools | **Genuine MAS error.** MAS self-debate returned a null/inconsistent foul aggregation (GT = Conor Gallagher, 83). |

So after manual inspection, the **only genuine** discordant outcomes (Q25, Q42) are **both won by
single-LLM+tools**. Substantively, single-LLM+tools is at worst tied and arguably marginally ahead of
the MAS on this set; the programmatic 26/26 tie slightly *flatters* the MAS.

Two questions were wrong for **both** conditions: Q32 (top-5 transfers — volatile/duplicated transfer
data; the answer-text scorer requires all five names+fees to appear) and Q41 (most goals in one match
— answer-format mismatch).

> **Scorer limitation (report honestly):** the answer-text scorer is sensitive to unit formatting
> ("116.6 million" vs `116600000`) and to markdown inside denial phrases (`**not**`). These cost
> single-LLM+tools two questions it answered correctly. The primary metric above is the frozen
> programmatic scorer (applied identically to all conditions), but the substantive conclusion is
> unchanged/strengthened: no MAS advantage.

---

## 4. Cost summary (tokens / latency, Opus 4.8, single run)

| | DA mean tokens | DA mean latency | Prediction mean tokens | Prediction mean latency |
|---|---|---|---|---|
| MAS | 32,324 | 16.7 s | 1,008 | 6.8 s |
| Single-LLM + tools | 22,150 | 8.1 s | 42,912 | 13.0 s |
| Single-LLM + raw data | 121,711 | 4.6 s | 1,204 | 7.7 s |

- On DA, the MAS costs ~1.5× the tokens and ~2× the latency of single-LLM+tools (manager + discovery +
  two-candidate SQL self-debate + synthesizer) for the **same** 26/30 accuracy.
- Raw-data DA is token-heavy (the ~43k-token inlined dump repeated per question) but fastest (one call).
- On prediction, single-LLM+tools is the outlier: it explores the DB with `run_sql` before delegating
  to the model, spending ~43k tokens to reach the identical vector the MAS gets for ~1k.

---

## 5. Interpretation (what McNemar does and does not establish)

On these 30 data-analysis questions, **the multi-agent system did not significantly outperform a
single Opus 4.8 with the same tools.** The two conditions tied at 26/30 overall, the McNemar exact
test is non-significant overall (p = 1.0) and on the out-of-coverage subset (p = 0.5), and the small
effects that exist point in opposite directions on different subsets. The hypothesis that the MAS
advantage would concentrate in out-of-coverage questions was **not** supported — single-LLM+tools
actually scored 12/12 there versus the MAS's 10/12. Manual inspection strengthens this: two of the
four discordant pairs are scorer artifacts (single+tools was substantively correct), so the *only*
genuine discordances (Q25, Q42) both favour single-LLM+tools. On the prediction slice the two conditions are
identical by construction (30/30 identical vectors), so no test applies. What McNemar *establishes*
here is narrow: with n = 30 (and only 2–4 discordant pairs), the study is **underpowered** — it can
neither confirm nor rule out a small true difference; a paired design with an order of magnitude more
questions would be needed to detect an effect of the size seen. What it does *not* establish is any
claim that orchestration helps or hurts: the evidence is consistent with "no material difference in
answer accuracy between MAS and a single tool-using LLM on this task, at meaningfully higher token and
latency cost for the MAS."
