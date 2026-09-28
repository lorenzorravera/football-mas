# Appendix — Experimental Setup and Results

All numbers in this appendix are regenerated programmatically from the frozen ground truth
(`results/golden/ground_truth.json`, `prediction_golden.json`) and the stored run files
(`results/runs/`) by re-scoring with `eval/score.py` — they are never hand-edited. Scoring is
deterministic: scalar answers match within a small numeric tolerance, ranked/tabular answers are
compared as row sets. No LLM-as-judge was used (all 50 questions resolve to deterministic SQL
ground truth). Evaluation is single-repeat (n = 46 data-analysis questions, 4 prediction
questions); treat all figures as directional.

---

## A.1 Model IDs and configuration

| Logical family | LiteLLM model ID | Temperature |
|---|---|---|
| claude | `anthropic/claude-opus-4-8` | model default (param omitted) |
| gpt | `gpt-5.5` | model default (param omitted) |
| gemini | `gemini/gemini-3.1-pro-preview` | model default (param omitted) |

- **Routing:** all model calls go through **LiteLLM** (`completion`), giving one OpenAI-style
  interface (incl. cross-provider function-calling) across the three families.
- **Temperature note:** all three chosen frontier models deprecate or restrict the `temperature`
  parameter, so we omit it entirely and let each model use its own default. SQL-generating paths
  *request* 0.3, but this is suppressed for these models; this is a methodological constraint, not a
  fixed temperature.
- **Max tokens:** 4096 (generous, so thinking models return content rather than only reasoning).
- **Memory:** disabled for all eval runs (no read/write) so the comparison isolates orchestration.
- **Tokens & latency:** captured locally via LiteLLM usage accounting per run, except MAS
  data-analysis token totals, which were recovered from Langfuse traces because local capture does
  not see the data-analyst self-debate loop (see A.7).

---

## A.2 Golden-set questions (data analysis, n = 46)

| ID | Category | Difficulty | Type | Coverage | Question |
|---|---|---|---|---|---|
| Q01 | team_league_outcomes | simple | scalar | in | Which team won the Premier League in 2024-2025? |
| Q02 | team_league_outcomes | simple | scalar | in | How many points did Arsenal finish with in 2023-2024? |
| Q03 | team_league_outcomes | medium | ranking | in | Give the full 2022-2023 PL final table (rank, team, points). |
| Q04 | team_league_outcomes | medium | table | in | Which three teams were relegated in 2023-2024? |
| Q05 | team_league_outcomes | medium | scalar | in | Which team had the best goal difference in 2024-2025? |
| Q06 | team_league_outcomes | edge_case | table | out | Everton's actual 2023-2024 points vs points without the deduction? |
| Q07 | team_league_outcomes | hard | table | out | Highest single-season points total across 2020-2021…2024-2025? |
| Q08 | team_league_outcomes | simple | table | in | Which teams finished top four in 2021-2022? |
| Q09 | player_season_aggregates | simple | scalar | in | Top goalscorer in 2023-2024 and their goals? |
| Q10 | player_season_aggregates | medium | ranking | in | Top five goalscorers in 2024-2025 with totals. |
| Q11 | player_season_aggregates | medium | scalar | in | Most assists in 2023-2024? |
| Q12 | player_season_aggregates | edge_case | scalar | in | Cole Palmer's total 2023-2024 goals (across all clubs)? |
| Q13 | player_season_aggregates | medium | scalar | in | Player with most minutes in 2022-2023? |
| Q14 | player_season_aggregates | medium | scalar | in | Liverpool's top scorer in 2024-2025? |
| Q15 | player_season_aggregates | medium | table | in | Players with ≥20 league goals in 2024-2025? |
| Q16 | home_away_splits | medium | scalar | in | Most home points in 2024-2025? |
| Q17 | home_away_splits | medium | scalar | in | Most away wins in 2023-2024? |
| Q18 | home_away_splits | hard | scalar | out | Biggest home-vs-away points gap in 2023-2024? |
| Q19 | home_away_splits | simple | scalar | in | Arsenal's home points in 2023-2024? |
| Q20 | home_away_splits | medium | scalar | in | Most home goals in 2024-2025? |
| Q21 | disciplinary | medium | scalar | in | Most yellow cards (team) in 2023-2024? |
| Q22 | disciplinary | medium | scalar | in | Most yellow cards (player) in 2023-2024? |
| Q23 | disciplinary | medium | scalar | in | Most red cards (team) in 2024-2025? |
| Q24 | disciplinary | medium | scalar | out | Total red cards league-wide in 2023-2024? |
| Q25 | disciplinary | edge_case | scalar | out | PL matches refereed by Anthony Taylor in 2023-2024? |
| Q26 | xg_performance | hard | scalar | out | Biggest xG overperformer (≥10 goals) in 2023-2024? |
| Q27 | xg_performance | hard | scalar | out | Biggest xG underperformer (≥10 goals) in 2023-2024? |
| Q28 | xg_performance | medium | table | out | Haaland's 2023-2024 goals vs xG and the difference? |
| Q29 | xg_performance | hard | scalar | out | Highest goals-to-xG ratio (≥15 xG) in 2024-2025? |
| Q30 | xg_performance | hard | scalar | out | Team with most combined npxG in 2023-2024? |
| Q31 | market_transfers | medium | scalar | in | Player with highest most-recent market value? |
| Q32 | market_transfers | hard | table | in | Five largest incoming transfer fees to PL clubs? |
| Q33 | market_transfers | medium | scalar | in | Most expensive incoming transfer in the 2023-2024 window? |
| Q34 | market_transfers | hard | scalar | out | Chelsea's total incoming transfer spend (all seasons)? |
| Q35 | market_transfers | medium | table | in | Three highest market-value players at Man City? |
| Q36 | availability | medium | scalar | out | Most games missed in a single injury spell, 2023-2024? |
| Q37 | availability | hard | scalar | out | Most total days missed to injury, 2023-2024? |
| Q38 | availability | hard | scalar | out | Club with most separate injury spells, 2023-2024? |
| Q39 | availability | medium | scalar | out | Injury spells recorded for Brentford players, 2023-2024? |
| Q40 | event_player_match | hard | scalar | in | Most shots attempted (event data) in 2023-2024? |
| Q41 | event_player_match | medium | table | in | Most goals by one player in a single match, 2024-2025? |
| Q42 | event_player_match | hard | scalar | out | Most fouls committed (summed) in 2023-2024? |
| Q43 | event_player_match | medium | scalar | out | Shot events resulting in a goal in 2024-2025? |
| Q44 | event_player_match | medium | table | in | Biggest home win (margin) in 2024-2025? |
| Q45 | edge_case | edge_case | scalar | in | Norwich City's points in 2024-2025? (not in PL — expect denial) |
| Q46 | edge_case | edge_case | scalar | out | Matches in 2020-2021 with a recorded attendance figure? |

### A.2.1 Canonical ground-truth SQL (verbatim)

```sql
-- Q01 SELECT t.team_name FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2024-2025' AND st.tss_rank=1
-- Q02 SELECT st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND t.team_name='Arsenal'
-- Q03 SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2022-2023' ORDER BY st.tss_rank
-- Q04 SELECT t.team_name, st.tss_rank FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND st.tss_rank >= 18 ORDER BY st.tss_rank
-- Q05 SELECT t.team_name FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2024-2025' ORDER BY st.tss_goal_difference DESC, t.team_name LIMIT 1
-- Q06 SELECT st.tss_points AS actual_points, (3*st.tss_wins + st.tss_draws) AS points_without_deduction FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND t.team_name='Everton'
-- Q07 SELECT t.team_name, s.season, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id ORDER BY st.tss_points DESC, t.team_name LIMIT 1
-- Q08 SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2021-2022' AND st.tss_rank <= 4 ORDER BY st.tss_rank
-- Q09 SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name ORDER BY goals DESC, p.player_name LIMIT 1
-- Q10 (top 5 goalscorers 2024-2025) … LIMIT 5
-- Q11 most assists 2023-2024 (SUM assists_pss)
-- Q12 SELECT … WHERE p.player_name='Cole Palmer' AND season='2023-2024' GROUP BY player  (sums across clubs)
-- Q13 most minutes 2022-2023 (SUM minutes_pss)
-- Q14 Liverpool top scorer 2024-2025 (join teams, team_name='Liverpool')
-- Q15 players HAVING SUM(goals_pss) >= 20 in 2024-2025
-- Q16 most home points 2024-2025 (team_season_home_away_standings.tshas_home_points)
-- Q17 most away wins 2023-2024 (tshas_away_wins)
-- Q18 max (tshas_home_points - tshas_away_points) 2023-2024
-- Q19 Arsenal home points 2023-2024
-- Q20 most home goals 2024-2025 (tshas_home_goals_for)
-- Q21 most yellow cards team 2023-2024 (team_season_stats_for.tssf_yellow_cards)
-- Q22 most yellow cards player 2023-2024 (SUM yellow_cards_pss)
-- Q23 most red cards team 2024-2025 (tssf_red_cards)
-- Q24 SUM(tssf_red_cards) over league 2023-2024
-- Q25 SELECT COUNT(*) FROM matches m JOIN seasons s … WHERE season='2023-2024' AND replace(m.referee, chr(160), ' ') = 'Anthony Taylor'   ← non-breaking-space landmine
-- Q26 HAVING SUM(goals_pss)>=10 ORDER BY (goals - xg) DESC   (overperformance)
-- Q27 HAVING SUM(goals_pss)>=10 ORDER BY (xg - goals) DESC   (underperformance)
-- Q28 Haaland goals vs xg and difference 2023-2024
-- Q29 HAVING SUM(xg_pss)>=15 ORDER BY goals/NULLIF(xg,0) DESC  2024-2025
-- Q30 team with max SUM(npxg_pss) 2023-2024
-- Q31 highest most-recent market value (player_market_values, MAX(date_unix) per player)
-- Q32 five largest transfer fees into PL clubs (player_transfers, to_team IN teams)
-- Q33 most expensive incoming transfer in 2023-2024 window
-- Q34 SUM(transfer_fee) WHERE to_team='Chelsea'
-- Q35 three highest market-value players at Man City (join player_season_stats for club)
-- Q36 max games_missed single spell 2023-2024 (player_injury_spells)
-- Q37 max SUM(days_missed) per player 2023-2024
-- Q38 club with most injury spells 2023-2024
-- Q39 COUNT spells for Brentford 2023-2024
-- Q40 most shots: COUNT(*) FROM match_events WHERE is_shot 2023-2024 ENG-PL
-- Q41 top single-match goals: player_match_performance ORDER BY match_goals DESC LIMIT 5
-- Q42 most fouls: SUM(pmp.fouls) 2023-2024
-- Q43 COUNT(*) FROM match_events WHERE is_goal 2024-2025 ENG-PL
-- Q44 biggest home win 2024-2025 (matches, ORDER BY home_score-away_score DESC)
-- Q45 Norwich City points 2024-2025 (returns empty → expected denial)
-- Q46 COUNT(*) FROM matches WHERE season='2020-2021' AND attendance_m IS NOT NULL
```

*(Q01–Q09 reproduced in full; Q10–Q46 abbreviated — the complete SQL is in
`results/golden/ground_truth.json`.)*

## A.2.2 Prediction questions (n = 4)

These are scored differently from the data-analysis set: rather than matching a SQL answer, they
are evaluated on (a) the **Brier score** of the predicted home/draw/away probabilities against the
realised outcome, and (b) **fidelity** — whether the agent correctly delegated to the prediction
model and reproduced its output.

| ID | Difficulty | Question | Model ground truth (H / D / A) |
|---|---|---|---|
| P01 | medium | Man United vs Fulham, 2024-08-16 — H/D/A probabilities | 0.557 / 0.178 / 0.265 |
| P02 | medium | Arsenal home win likelihood vs Wolves, 2024-08-17, + confidence | 0.800 / 0.184 / 0.016 |
| P03 | medium | Everton vs Brighton at Everton, 2024-08-17 — who is likelier? | 0.239 / 0.224 / 0.538 |
| P04 | hard | Draw probability, Nottingham Forest vs Bournemouth, 2024-08-17 | 0.322 / 0.249 / 0.429 |

---

## A.3 Aggregate result tables

### A.3.1 Experiment 1 — Degrees of freedom (accuracy by model × variant × coverage)

| Model | Variant | In-coverage (28) | Out-of-coverage (18) | Overall (46) |
|---|---|---|---|---|
| Opus 4.8 | Controlled | 26/28 (93%) | 1/18 (6%) | 27/46 (59%) |
| Opus 4.8 | Semi | 26/28 (93%) | 16/18 (89%) | 42/46 (91%) |
| Opus 4.8 | Autonomous | 23/28 (82%) | 17/18 (94%) | 40/46 (87%) |
| GPT 5.5 | Controlled | 26/28 (93%) | 3/18 (17%) | 29/46 (63%) |
| GPT 5.5 | Semi | 25/28 (89%) | 16/18 (89%) | 41/46 (89%) |
| GPT 5.5 | Autonomous | 23/28 (82%) | 16/18 (89%) | 39/46 (85%) |
| Gemini 3.1 Pro | Controlled | 26/28 (93%) | 2/18 (11%) | 28/46 (61%) |
| Gemini 3.1 Pro | Semi | 26/28 (93%) | 16/18 (89%) | 42/46 (91%) |
| Gemini 3.1 Pro | Autonomous | 19/28 (68%) | 13/18 (72%) | 32/46 (70%) |

### A.3.2 Experiment 2 — MAS vs single LLM (Claude; MAS = autonomous analyst), data analysis

| Condition | Overall | In-cov (28) | Out-of-cov (18) | Avg tokens | Avg latency |
|---|---|---|---|---|---|
| MAS (autonomous) | 41/46 (89%) | 24/28 (86%) | 17/18 (94%) | 30,635 | 17.8 s |
| single-LLM + tools | 38/46 (83%) | 23/28 (82%) | 15/18 (83%) | 24,740 | 10.5 s |
| single-LLM + raw data | 16/46 (35%) | 13/28 (46%) | 3/18 (17%) | 229,749 | 4.5 s |

Accuracy decomposition for the gains: tool access contributes +48 points (35% → 83%), additional
multi-agent orchestration +6 points (83% → 89%).

**By category:**

| Category | MAS | single + tools | single + raw |
|---|---|---|---|
| availability | 4/4 | 4/4 | 0/4 |
| disciplinary | 4/5 | 5/5 | 3/5 |
| edge_case | 2/2 | 1/2 | 1/2 |
| event_player_match | 3/5 | 4/5 | 0/5 |
| home_away_splits | 5/5 | 4/5 | 4/5 |
| market_transfers | 4/5 | 1/5 | 0/5 |
| player_season_aggregates | 6/7 | 7/7 | 1/7 |
| team_league_outcomes | 8/8 | 8/8 | 7/8 |
| xg_performance | 5/5 | 4/5 | 0/5 |

### A.3.3 Experiment 2 — prediction slice (Claude, n = 4)

| Condition | Avg Brier | Fidelity | Avg tokens | Avg latency |
|---|---|---|---|---|
| MAS (autonomous) | 0.129 | 4/4 | 992 | 8.5 s |
| single-LLM + tools | 0.129 | 4/4 | 34,947 | 12.2 s |
| single-LLM + raw data | 0.166 | n/a | 1,156 | 6.4 s |

MAS and single-LLM-with-tools produce identical predictions (both delegate to the same model
function), hence identical Brier. The raw-data condition reasons over recent results with no model
access and is less calibrated.

---

## A.4 Per-question result matrix — Experiment 1 (DoF)

`1` = correct, `0` = incorrect. Columns: model (clau/gpt/gemi) × variant (con/sem/aut).

| QID | Cov | clau.con | clau.sem | clau.aut | gpt.con | gpt.sem | gpt.aut | gemi.con | gemi.sem | gemi.aut |
|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q02 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q03 | in | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 | 0 |
| Q04 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 |
| Q05 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q06 | out | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q07 | out | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 0 |
| Q08 | in | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 0 |
| Q09 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q10 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q11 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q12 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q13 | in | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 |
| Q14 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q15 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q16 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 |
| Q17 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q18 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q19 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q20 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 |
| Q21 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q22 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q23 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q24 | out | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q25 | out | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q26 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 0 | 1 |
| Q27 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 0 |
| Q28 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q29 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q30 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q31 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q32 | in | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| Q33 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q34 | out | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 1 |
| Q35 | in | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 | 0 |
| Q36 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 0 |
| Q37 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q38 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 0 |
| Q39 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q40 | in | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 | 0 |
| Q41 | in | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q42 | out | 0 | 0 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q43 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |
| Q44 | in | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| Q45 | in | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 |
| Q46 | out | 0 | 1 | 1 | 0 | 1 | 1 | 0 | 1 | 1 |

---

## A.5 Per-question result matrix — Experiment 2 (MAS vs single, Claude)

| QID | Cov | MAS | single + tools | single + raw |
|---|---|---|---|---|
| Q01 | in | 1 | 1 | 1 |
| Q02 | in | 1 | 1 | 1 |
| Q03 | in | 1 | 1 | 1 |
| Q04 | in | 1 | 1 | 1 |
| Q05 | in | 1 | 1 | 1 |
| Q06 | out | 1 | 1 | 1 |
| Q07 | out | 1 | 1 | 0 |
| Q08 | in | 1 | 1 | 1 |
| Q09 | in | 1 | 1 | 0 |
| Q10 | in | 1 | 1 | 0 |
| Q11 | in | 1 | 1 | 0 |
| Q12 | in | 1 | 1 | 0 |
| Q13 | in | 0 | 1 | 0 |
| Q14 | in | 1 | 1 | 1 |
| Q15 | in | 1 | 1 | 0 |
| Q16 | in | 1 | 1 | 1 |
| Q17 | in | 1 | 1 | 1 |
| Q18 | out | 1 | 1 | 1 |
| Q19 | in | 1 | 1 | 1 |
| Q20 | in | 1 | 0 | 0 |
| Q21 | in | 1 | 1 | 1 |
| Q22 | in | 1 | 1 | 0 |
| Q23 | in | 1 | 1 | 1 |
| Q24 | out | 1 | 1 | 1 |
| Q25 | out | 0 | 1 | 0 |
| Q26 | out | 1 | 1 | 0 |
| Q27 | out | 1 | 1 | 0 |
| Q28 | out | 1 | 0 | 0 |
| Q29 | out | 1 | 1 | 0 |
| Q30 | out | 1 | 1 | 0 |
| Q31 | in | 1 | 0 | 0 |
| Q32 | in | 1 | 0 | 0 |
| Q33 | in | 1 | 0 | 0 |
| Q34 | out | 1 | 0 | 0 |
| Q35 | in | 0 | 1 | 0 |
| Q36 | out | 1 | 1 | 0 |
| Q37 | out | 1 | 1 | 0 |
| Q38 | out | 1 | 1 | 0 |
| Q39 | out | 1 | 1 | 0 |
| Q40 | in | 0 | 1 | 0 |
| Q41 | in | 0 | 0 | 0 |
| Q42 | out | 1 | 1 | 0 |
| Q43 | out | 1 | 1 | 0 |
| Q44 | in | 1 | 1 | 0 |
| Q45 | in | 1 | 1 | 1 |
| Q46 | out | 1 | 0 | 0 |

---

## A.6 Failure taxonomy (semi-controlled variant)

Every semi-controlled run that did not score correct, classified by failure mode. A = chose a
template when SQL was needed; B = wrong template / params; C = template failed → SQL fallback,
still wrong; D = free-SQL generation wrong; E = errored / unclassified.

| Code | Failure mode | claude | gpt | gemini | Total |
|---|---|---|---|---|---|
| A | chose template when SQL needed | 0 | 0 | 0 | 0 |
| B | wrong template / params | 2 | 3 | 2 | 7 |
| C | template failed → SQL fallback, still wrong | 0 | 0 | 0 | 0 |
| D | free-SQL generation wrong | 2 | 2 | 2 | 6 |
| E | errored / unclassified | 0 | 0 | 0 | 0 |

**Failing items (semi-controlled):**

| ID | Model | Coverage | Route taken | Bucket |
|---|---|---|---|---|
| Q41 | claude | in | template | B |
| Q32 | claude | in | template | B |
| Q42 | claude | out | sql | D |
| Q25 | claude | out | sql | D |
| Q45 | gpt | in | template | B |
| Q32 | gpt | in | template | B |
| Q41 | gpt | in | template | B |
| Q25 | gpt | out | sql | D |
| Q34 | gpt | out | sql | D |
| Q41 | gemini | in | template | B |
| Q32 | gemini | in | template | B |
| Q26 | gemini | out | sql | D |
| Q25 | gemini | out | sql | D |

---

## A.7 Root-cause analysis of failures

**Controlled variant collapses on out-of-coverage (6–17%).** By construction the template catalogue
(A.8.10) cannot express computed columns, `HAVING` filters, cross-season aggregation, or the
events/transfers/injuries tables. Every out-of-coverage miss (Q06, Q07, Q18, Q26–Q30, Q34, Q36–Q39,
Q42, Q43, Q46) is a "no template fits the required logic" failure — the expected and correct result
of constraining the agent to templates, and the central motivation for allowing free SQL.

**Universal failures (all variants, all models).** Two questions are missed by every configuration:
- **Q41** (most goals by one player in a single match) — `player_match_performance` has a per-(player, game) grain that all systems mis-aggregated; the matching template (`player_match_leaders`) returns a different shape than the ground truth expects. This is the only in-coverage question the controlled variant fails for *all* models and is a likely ground-truth/grain mismatch worth re-auditing.
- **Q25** (matches refereed by Anthony Taylor) — the `referee` column contains a non-breaking space (`chr(160)`) that the canonical SQL normalises with `replace(...)`; agents that wrote the natural `referee = 'Anthony Taylor'` returned zero rows. A data-quality landmine, not a reasoning failure. (single-LLM-with-tools alone recovered it.)

**Autonomous loses some in-coverage questions (the 82%/68% dip).** On questions a template would
have answered cleanly, free SQL occasionally diverges — Q03/Q08 (table formatting/ordering),
Q13 (minutes aggregation), Q20, Q35 (market value joined to club), Q40. For Gemini the autonomous
self-debate loop frequently failed to converge (in-coverage 19/28), the main driver of its 70%
overall. This is the cost side of autonomy: more expressive, but more ways to be subtly wrong.

**Semi-controlled failures split evenly (A.6).** Seven are wrong-template/param (route = template:
mostly Q41, Q32) and six are wrong-SQL (route = sql: Q25, Q42, Q34, Q26). Notably bucket A is empty —
no model ever picked a template when SQL was strictly required — so the routing decision itself is
sound; the errors are downstream (bad params, or bad SQL once it routed correctly).

**single-LLM-with-raw-data (35%) is bounded twice over.**
1. *Coverage ceiling 30/46.* Only four tables are inlined (standings, home/away splits, team
   season stats, player season stats). The other 16 questions need tables too large to inline —
   `match_events`, `player_match_performance`, `player_transfers`, `player_market_values`,
   `player_injury_spells`, `matches` — so they are unanswerable by construction (entire
   availability, market/transfer, and event categories score 0).
2. *Reasoning shortfall within reach.* Even among the 30 answerable it scored only 16
   (53%), with the gap concentrated in `player_season_aggregates` (1/7) and `xg_performance`
   (0/5) — both requiring aggregation/scanning over the largest inlined table. The 35% headline
   therefore reflects both the impossibility of fitting a database into a prompt and unreliable
   reasoning over bulk inlined text, not reasoning ability alone.

---

## A.8 Exact prompts per condition

All conditions share the same role preamble and the same schema context (`get_schema_context()`),
injected where indicated by `{schema}`. Variable interpolations are shown in `{braces}`.

### A.8.1 Shared preamble (all agents)
```
You are a Premier League data analyst. Answer the user's question using ONLY the database.
Rules: seasons are 'YYYY-YYYY' (hyphen, e.g. '2023-2024'); the latest season is 2024-2025
(no 2025-26 data); point deductions are already in the points columns; prefer IDs over names
for joins; canonical team names (e.g. 'Manchester United', 'Wolves').
```

### A.8.2 MAS — Manager (intent + entity extraction)
```
{preamble}
Classify and extract for this Premier League question.
Question: {question}

Respond JSON: {"intent": "data_request" | "prediction_match" | "conversational",
"seasons": ["YYYY-YYYY", ...], "teams": [...], "metrics": [...],
"home_team": "...", "away_team": "...", "match_date": "YYYY-MM-DD"}.
Use intent='prediction_match' ONLY when asked to forecast/predict a specific fixture's
outcome; then fill home_team, away_team and match_date.
Resolve 'this/current season' to 2024-2025 (latest data).
```

### A.8.3 MAS — Data discovery
```
{preamble}
Database schema:
{schema}

Question: {question}
Manager context: {manager_json}

Respond JSON: {"relevant_tables": [...], "notes": "short join/grain guidance"}.
```

### A.8.4 MAS — Data analyst, CONTROLLED (template only)
```
{preamble}
You can ONLY answer using these templates:
{template_catalogue}

Question: {question}

Respond with JSON: {"template_name": "...", "params": {"season": "...", "team": "...",
"metric": "...", "top_n": 50}}. Include only the params the template needs.
```
*On template error: one corrective retry with `(Previous attempt failed: {error})` appended.*

### A.8.5 MAS — Data analyst, SEMI (route template-or-SQL)
```
{preamble}
You may either USE A TEMPLATE or WRITE CUSTOM SQL.
Templates:
{template_catalogue}

Question: {question}

Respond JSON: {"approach": "template" | "sql", "template_name": "...",
"params": {...}} (if template). If "sql", just {"approach":"sql"}.
```
*If approach = "sql", or a chosen template errors, control passes to the self-debate SQL loop
(A.8.6).*

### A.8.6 MAS — Data analyst, AUTONOMOUS (free SQL + self-debate)
Two independent candidates are generated per iteration (up to 2 reconcile rounds); their result
sets must agree or the answer is flagged low-confidence.
```
# Candidate A
{preamble}
Database schema:
{schema}

Question: {question}
Write the most direct correct query.
Return ONLY one SQL SELECT statement, no prose, no code fences.

# Candidate B
… Write an independent query (different phrasing/joins) for the same answer. …

# Reconcile round (if A and B disagree)
… Your two previous SQL attempts DISAGREED on their results — reconcile them.
Attempt A: {sql_a}
Attempt B: {sql_b}
Find the correct query. …
```

### A.8.7 MAS — Synthesizer (data questions)
```
{preamble}
Question: {question}

Query result (JSON):
{first_30_rows}

Answer the question directly and concisely using ONLY this result. State numbers exactly.
```

### A.8.8 MAS — Prediction synthesizer
```
{preamble}
Question: {question}

The match-outcome model returned (probabilities):
{prediction_json}

Answer the question using these probabilities. State the three probabilities
(home win / draw / away win) explicitly and the most likely outcome.
```

### A.8.9 Single-LLM + tools (system prompt)
Native function-calling; tools = `run_sql`, `predict_match_outcome`; max 8 steps.
```
{preamble}
Use the provided tools to answer: `run_sql` to query the database, and
`predict_match_outcome` to forecast a fixture's result. Then answer.
Database schema:
{schema}
```

### A.8.10 Single-LLM + raw data (system prompt)
No tools; the four core tables are inlined as CSV.
```
{preamble}
You have NO tools and NO database access. Answer ONLY from the schema and
the inlined data below. If the data needed is not present, say so.

Schema:
{schema}

=== INLINED DATA ===
{csv_dump_of: standings, home_away, team_discipline, player_season}
```

### A.8.11 Single-LLM + raw data (prediction variant)
No model, no tools — forecasts from causal recent-result data only.
```
{preamble}
You have NO tools and NO prediction model — forecast using ONLY the
recent results below. Reason about form, then give CALIBRATED probabilities for
{home_team} (home) vs {away_team} on {match_date} that sum to 1.0.

=== RECENT RESULTS ===
{home_team and away_team's last 10 matches strictly before match_date}

End your answer with EXACTLY this line:
PROBABILITIES: home=<p>, draw=<p>, away=<p>
```

### A.8.12 Tool: predict_match_outcome (schema shown to the model)
```
name: predict_match_outcome
description: Predict probabilities of each outcome (home win / draw / away win) for a Premier
  League fixture, using the trained match-outcome model. Returns three probabilities summing to
  1.0 plus the model's confidence. Provide the match_date (the model is causal — it uses only
  data before that date).
input: { home_team (req), away_team (req), match_date 'YYYY-MM-DD' (req), season (opt) }
```

### A.8.13 Template catalogue (controlled / semi)
```
- league_table: Full final league table for a season. (params: season)
- team_season_summary: One team's season summary incl. home/away points & goals, possession. (params: team, season)
- home_away_table: Teams ranked by a home/away split metric. (params: season; metric ∈ home_points|away_points|home_wins|away_wins|home_goals_for|away_goals_for)
- player_season_leaders: Top players by a season stat. (params: season; metric ∈ goals|assists|minutes|yellow_cards|red_cards|shots)
- player_team_leaders: Top players at a club by a season stat. (params: team, season; metric ∈ goals|assists|minutes)
- team_stat_leaders: Teams ranked by a team-season stat. (params: season; metric ∈ yellow_cards|red_cards|goals|shots|possession)
- head_to_head: All matches between two teams in a season. (params: team_a, team_b, season)
- match_results: Matches in a season ordered by home win margin. (params: season)
- market_value_leaders: Players ranked by latest market value. (params: none)
- market_value_team_leaders: Players at a club ranked by latest market value. (params: team)
- player_match_leaders: Top single-match player performances. (params: season; metric ∈ match_goals|match_assists)
- transfer_leaders: Largest incoming transfer fees to PL clubs. (params: none)
```

---

## A.9 Caveats

- Single-repeat (n = 46 + 4); no variance estimates. Differences of 1–3 questions are within noise.
- MAS data-analysis token totals come from Langfuse; all other token totals from local capture.
  The two are not directly comparable across tables (the MAS prediction total of 992 is local
  capture and undercounts relative to its Langfuse data-analysis total).
- Q41 and Q25 ground truth should be re-audited (grain mismatch and non-breaking-space normalisation).
- The on-disk `results/stats/paired_tests.json` predates the current scorer and disagrees with the
  re-scored tables above; regenerate before citing any significance test.
