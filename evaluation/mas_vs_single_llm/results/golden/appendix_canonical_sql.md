# Appendix — Golden set: question → canonical SQL → result (CANDIDATE)

_Not frozen. Ground truth is the result of running each canonical SQL._

## Q01 — team_league_outcomes (simple, deterministic_sql/scalar)

**Q:** Which team won the Premier League in 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2024-2025' AND st.tss_rank=1
```

| team_name |
| --- |
| Liverpool |

## Q02 — team_league_outcomes (simple, deterministic_sql/scalar)

**Q:** How many points did Arsenal finish with in the 2023-2024 season?

**Status:** `ok`

```sql
SELECT st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND t.team_name='Arsenal'
```

| tss_points |
| --- |
| 89 |

## Q03 — team_league_outcomes (medium, deterministic_sql/ranking)

**Q:** Give the full 2022-2023 Premier League final table (rank, team, points).

**Status:** `ok`

```sql
SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2022-2023' ORDER BY st.tss_rank
```

| tss_rank | team_name | tss_points |
| --- | --- | --- |
| 1 | Manchester City | 89 |
| 2 | Arsenal | 84 |
| 3 | Manchester United | 75 |
| 4 | Newcastle United | 71 |
| 5 | Liverpool | 67 |
| 6 | Brighton | 62 |
| 7 | Aston Villa | 61 |
| 8 | Tottenham Hotspur | 60 |
_…12 more rows_

## Q04 — team_league_outcomes (medium, deterministic_sql/table)

**Q:** Which three teams were relegated from the Premier League in 2023-2024?

**Status:** `ok`

```sql
SELECT t.team_name, st.tss_rank FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND st.tss_rank >= 18 ORDER BY st.tss_rank
```

| team_name | tss_rank |
| --- | --- |
| Luton Town | 18 |
| Burnley | 19 |
| Sheffield United | 20 |

## Q05 — team_league_outcomes (medium, deterministic_sql/scalar)

**Q:** Which team had the best goal difference in 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2024-2025' ORDER BY st.tss_goal_difference DESC, t.team_name LIMIT 1
```

| team_name |
| --- |
| Liverpool |

## Q06 — team_league_outcomes (edge_case, multi_step/table)

**Q:** How many points did Everton actually finish 2023-2024 with, and how many would they have had without the points deduction?

**Status:** `ok`

```sql
SELECT st.tss_points AS actual_points, (3*st.tss_wins + st.tss_draws) AS points_without_deduction FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2023-2024' AND t.team_name='Everton'
```

| actual_points | points_without_deduction |
| --- | --- |
| 40 | 48 |

## Q07 — team_league_outcomes (hard, deterministic_sql/table)

**Q:** What is the highest points total achieved by any team in a single season across 2020-2021 to 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name, s.season, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id ORDER BY st.tss_points DESC, t.team_name LIMIT 1
```

| team_name | season | tss_points |
| --- | --- | --- |
| Manchester City | 2021-2022 | 93 |

## Q08 — team_league_outcomes (simple, deterministic_sql/table)

**Q:** Which teams finished in the top four in 2021-2022?

**Status:** `ok`

```sql
SELECT st.tss_rank, t.team_name, st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2021-2022' AND st.tss_rank <= 4 ORDER BY st.tss_rank
```

| tss_rank | team_name | tss_points |
| --- | --- | --- |
| 1 | Manchester City | 93 |
| 2 | Liverpool | 92 |
| 3 | Chelsea | 74 |
| 4 | Tottenham Hotspur | 71 |

## Q09 — player_season_aggregates (simple, deterministic_sql/scalar)

**Q:** Who was the top goalscorer in the 2023-2024 Premier League season, and how many goals did they score?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name ORDER BY goals DESC, p.player_name LIMIT 1
```

| player_name | goals |
| --- | --- |
| Erling Haaland | 27 |

## Q10 — player_season_aggregates (medium, deterministic_sql/ranking)

**Q:** List the top five goalscorers in 2024-2025 with their goal totals.

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name ORDER BY goals DESC, p.player_name LIMIT 5
```

| player_name | goals |
| --- | --- |
| Mohamed Salah | 29 |
| Alexander Isak | 23 |
| Erling Haaland | 22 |
| Bryan Mbeumo | 20 |
| Chris Wood | 20 |

## Q11 — player_season_aggregates (medium, deterministic_sql/scalar)

**Q:** Who provided the most assists in 2023-2024?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.assists_pss) AS assists FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name ORDER BY assists DESC, p.player_name LIMIT 1
```

| player_name | assists |
| --- | --- |
| Ollie Watkins | 13 |

## Q12 — player_season_aggregates (edge_case, multi_step/scalar)

**Q:** How many league goals did Cole Palmer score in total in 2023-2024 (across all clubs he played for that season)?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS total_goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' AND p.player_name='Cole Palmer' GROUP BY p.player_id, p.player_name
```

| player_name | total_goals |
| --- | --- |
| Cole Palmer | 22 |

## Q13 — player_season_aggregates (medium, deterministic_sql/scalar)

**Q:** Which player played the most minutes in 2022-2023?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.minutes_pss) AS minutes FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2022-2023' GROUP BY p.player_id, p.player_name ORDER BY minutes DESC, p.player_name LIMIT 1
```

| player_name | minutes |
| --- | --- |
| Aaron Ramsdale | 3420 |

## Q14 — player_season_aggregates (medium, deterministic_sql/scalar)

**Q:** Who was Liverpool's top scorer in 2024-2025?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id JOIN teams t ON t.team_id=pss.team_id WHERE s.season='2024-2025' AND t.team_name='Liverpool' GROUP BY p.player_id, p.player_name ORDER BY goals DESC, p.player_name LIMIT 1
```

| player_name | goals |
| --- | --- |
| Mohamed Salah | 29 |

## Q15 — player_season_aggregates (medium, deterministic_sql/table)

**Q:** Which players scored at least 20 league goals in 2024-2025?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name HAVING SUM(pss.goals_pss) >= 20 ORDER BY goals DESC, p.player_name
```

| player_name | goals |
| --- | --- |
| Mohamed Salah | 29 |
| Alexander Isak | 23 |
| Erling Haaland | 22 |
| Bryan Mbeumo | 20 |
| Chris Wood | 20 |

## Q16 — home_away_splits (medium, deterministic_sql/scalar)

**Q:** Which team earned the most home points in 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name, ha.tshas_home_points AS home_points FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2024-2025' ORDER BY home_points DESC, t.team_name LIMIT 1
```

| team_name | home_points |
| --- | --- |
| Liverpool | 46 |

## Q17 — home_away_splits (medium, deterministic_sql/scalar)

**Q:** Which team recorded the most away wins in 2023-2024?

**Status:** `ok`

```sql
SELECT t.team_name, ha.tshas_away_wins AS away_wins FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2023-2024' ORDER BY away_wins DESC, t.team_name LIMIT 1
```

| team_name | away_wins |
| --- | --- |
| Manchester City | 14 |

## Q18 — home_away_splits (hard, multi_step/scalar)

**Q:** Which team had the biggest gap between home points and away points in 2023-2024?

**Status:** `ok`

```sql
SELECT t.team_name, (ha.tshas_home_points - ha.tshas_away_points) AS home_away_gap FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2023-2024' ORDER BY home_away_gap DESC, t.team_name LIMIT 1
```

| team_name | home_away_gap |
| --- | --- |
| Newcastle United | 20 |

## Q19 — home_away_splits (simple, deterministic_sql/scalar)

**Q:** How many home points did Arsenal earn in 2023-2024?

**Status:** `ok`

```sql
SELECT ha.tshas_home_points FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2023-2024' AND t.team_name='Arsenal'
```

| tshas_home_points |
| --- |
| 47 |

## Q20 — home_away_splits (medium, deterministic_sql/scalar)

**Q:** Which team scored the most home goals in 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name, ha.tshas_home_goals_for AS home_goals FROM team_season_home_away_standings ha JOIN teams t ON t.team_id=ha.team_id JOIN seasons s ON s.season_id=ha.season_id WHERE s.season='2024-2025' ORDER BY home_goals DESC, t.team_name LIMIT 1
```

| team_name | home_goals |
| --- | --- |
| Manchester City | 43 |

## Q21 — disciplinary (medium, deterministic_sql/scalar)

**Q:** Which team received the most yellow cards in 2023-2024?

**Status:** `ok`

```sql
SELECT t.team_name, sf.tssf_yellow_cards AS yellows FROM team_season_stats_for sf JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id WHERE s.season='2023-2024' ORDER BY yellows DESC, t.team_name LIMIT 1
```

| team_name | yellows |
| --- | --- |
| Chelsea | 109 |

## Q22 — disciplinary (medium, deterministic_sql/scalar)

**Q:** Which player received the most yellow cards in 2023-2024?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.yellow_cards_pss) AS yellows FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name ORDER BY yellows DESC, p.player_name LIMIT 1
```

| player_name | yellows |
| --- | --- |
| João Palhinha | 13 |

## Q23 — disciplinary (medium, deterministic_sql/scalar)

**Q:** Which team picked up the most red cards in 2024-2025?

**Status:** `ok`

```sql
SELECT t.team_name, sf.tssf_red_cards AS reds FROM team_season_stats_for sf JOIN teams t ON t.team_id=sf.team_id JOIN seasons s ON s.season_id=sf.season_id WHERE s.season='2024-2025' ORDER BY reds DESC, t.team_name LIMIT 1
```

| team_name | reds |
| --- | --- |
| Arsenal | 6 |

## Q24 — disciplinary (medium, deterministic_sql/scalar)

**Q:** How many red cards were shown in total across the league in 2023-2024?

**Status:** `ok`

```sql
SELECT SUM(sf.tssf_red_cards) AS total_red_cards FROM team_season_stats_for sf JOIN seasons s ON s.season_id=sf.season_id WHERE s.season='2023-2024'
```

| total_red_cards |
| --- |
| 58 |

## Q25 — disciplinary (edge_case, deterministic_sql/scalar)

**Q:** How many Premier League matches did referee Anthony Taylor officiate in 2023-2024?

**Status:** `ok`

```sql
SELECT COUNT(*) AS matches_officiated FROM matches m JOIN seasons s ON s.season_id=m.season_id WHERE s.season='2023-2024' AND replace(m.referee, chr(160), ' ') = 'Anthony Taylor'
```

| matches_officiated |
| --- |
| 27 |

## Q26 — xg_performance (hard, multi_step/scalar)

**Q:** Among players with at least 10 goals in 2023-2024, who overperformed their xG by the most (goals minus xG)?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, ROUND(SUM(pss.goals_pss) - SUM(pss.xg_pss),2) AS overperformance FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name HAVING SUM(pss.goals_pss) >= 10 ORDER BY overperformance DESC, p.player_name LIMIT 1
```

| player_name | goals | xg | overperformance |
| --- | --- | --- | --- |
| Phil Foden | 19 | 11.31 | 7.69 |

## Q27 — xg_performance (hard, multi_step/scalar)

**Q:** Among players with at least 10 goals in 2023-2024, who underperformed their xG by the most (xG minus goals)?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, ROUND(SUM(pss.xg_pss) - SUM(pss.goals_pss),2) AS underperformance FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY p.player_id, p.player_name HAVING SUM(pss.goals_pss) >= 10 ORDER BY underperformance DESC, p.player_name LIMIT 1
```

| player_name | goals | xg | underperformance |
| --- | --- | --- | --- |
| Darwin Núñez | 11 | 19.19 | 8.19 |

## Q28 — xg_performance (medium, multi_step/table)

**Q:** How many goals did Erling Haaland score in 2023-2024 versus his xG, and what was the difference?

**Status:** `ok`

```sql
SELECT SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, ROUND(SUM(pss.goals_pss) - SUM(pss.xg_pss),2) AS difference FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' AND p.player_name='Erling Haaland' GROUP BY p.player_id
```

| goals | xg | difference |
| --- | --- | --- |
| 27 | 31.65 | -4.65 |

## Q29 — xg_performance (hard, multi_step/scalar)

**Q:** Among players with at least 15 xG in 2024-2025, who had the highest goals-to-xG ratio?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pss.goals_pss) AS goals, ROUND(SUM(pss.xg_pss),2) AS xg, ROUND(SUM(pss.goals_pss)/NULLIF(SUM(pss.xg_pss),0),3) AS goals_per_xg FROM player_season_stats pss JOIN players p ON p.player_id=pss.player_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2024-2025' GROUP BY p.player_id, p.player_name HAVING SUM(pss.xg_pss) >= 15 ORDER BY goals_per_xg DESC, p.player_name LIMIT 1
```

| player_name | goals | xg | goals_per_xg |
| --- | --- | --- | --- |
| Chris Wood | 20 | 15.64 | 1.279 |

## Q30 — xg_performance (hard, multi_step/scalar)

**Q:** Which team had the most non-penalty expected goals (npxG) from its players combined in 2023-2024?

**Status:** `ok`

```sql
SELECT t.team_name, ROUND(SUM(pss.npxg_pss),2) AS team_npxg FROM player_season_stats pss JOIN teams t ON t.team_id=pss.team_id JOIN seasons s ON s.season_id=pss.season_id WHERE s.season='2023-2024' GROUP BY t.team_id, t.team_name ORDER BY team_npxg DESC, t.team_name LIMIT 1
```

| team_name | team_npxg |
| --- | --- |
| Liverpool | 90.26 |

## Q31 — market_transfers (medium, multi_step/scalar)

**Q:** Which player has the highest market value (most recent valuation on record)?

**Status:** `ok`

```sql
SELECT p.player_name, mv.market_value FROM player_market_values mv JOIN players p ON p.player_id=mv.player_id WHERE (mv.player_id, mv.date_unix) IN (SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) ORDER BY mv.market_value DESC, p.player_name LIMIT 1
```

| player_name | market_value |
| --- | --- |
| Erling Haaland | 180000000 |

## Q32 — market_transfers (hard, deterministic_sql/table)

**Q:** What are the five largest transfer fees paid by a Premier League club (incoming transfers) in the data?

**Status:** `ok`

```sql
SELECT p.player_name, tr.from_team, tr.to_team, tr.season, tr.transfer_fee FROM player_transfers tr JOIN players p ON p.player_id=tr.player_id WHERE tr.to_team IN (SELECT team_name FROM teams) AND tr.transfer_fee IS NOT NULL ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 5
```

| player_name | from_team | to_team | season | transfer_fee |
| --- | --- | --- | --- | --- |
| Alexander Isak | Newcastle United | Liverpool | 2025-2026 | 145000000 |
| Enzo Fernández | Benfica | Chelsea | 2022-2023 | 121000000 |
| Jack Grealish | Aston Villa | Manchester City | 2021-2022 | 117500000 |
| Declan Rice | West Ham United | Arsenal | 2023-2024 | 116600000 |
| Moisés Caicedo | Brighton | Chelsea | 2023-2024 | 116000000 |

## Q33 — market_transfers (medium, deterministic_sql/scalar)

**Q:** What was the most expensive incoming transfer to a Premier League club in the 2023-2024 season window?

**Status:** `ok`

```sql
SELECT p.player_name, tr.to_team, tr.transfer_fee FROM player_transfers tr JOIN players p ON p.player_id=tr.player_id WHERE tr.season='2023-2024' AND tr.to_team IN (SELECT team_name FROM teams) AND tr.transfer_fee IS NOT NULL ORDER BY tr.transfer_fee DESC, p.player_name LIMIT 1
```

| player_name | to_team | transfer_fee |
| --- | --- | --- |
| Declan Rice | Arsenal | 116600000 |

## Q34 — market_transfers (hard, multi_step/scalar)

**Q:** What is Chelsea's total recorded incoming transfer spend across all seasons in the data?

**Status:** `ok`

```sql
SELECT SUM(tr.transfer_fee) AS total_spend FROM player_transfers tr WHERE tr.to_team='Chelsea' AND tr.transfer_fee IS NOT NULL
```

| total_spend |
| --- |
| 2363510000 |

## Q35 — market_transfers (medium, deterministic_sql/table)

**Q:** List the three players with the highest market value at Manchester City (most recent valuation).

**Status:** `ok`

```sql
SELECT p.player_name, mv.market_value FROM player_market_values mv JOIN players p ON p.player_id=mv.player_id JOIN player_season_stats pss ON pss.player_id=mv.player_id JOIN teams t ON t.team_id=pss.team_id WHERE t.team_name='Manchester City' AND (mv.player_id, mv.date_unix) IN (SELECT player_id, MAX(date_unix) FROM player_market_values GROUP BY player_id) GROUP BY p.player_name, mv.market_value ORDER BY mv.market_value DESC, p.player_name LIMIT 3
```

| player_name | market_value |
| --- | --- |
| Erling Haaland | 180000000 |
| Cole Palmer | 120000000 |
| Rodri | 110000000 |

## Q36 — availability (medium, deterministic_sql/scalar)

**Q:** Which player missed the most games in a single injury spell in 2023-2024?

**Status:** `ok`

```sql
SELECT p.player_name, pis.games_missed FROM player_injury_spells pis JOIN players p ON p.player_id=pis.player_id WHERE pis.season='2023-2024' ORDER BY pis.games_missed DESC NULLS LAST, p.player_name LIMIT 1
```

| player_name | games_missed |
| --- | --- |
| Aaron Hickey | 65 |

## Q37 — availability (hard, multi_step/scalar)

**Q:** Which player missed the most total days to injury across all spells in 2023-2024?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pis.days_missed) AS total_days_missed FROM player_injury_spells pis JOIN players p ON p.player_id=pis.player_id WHERE pis.season='2023-2024' GROUP BY p.player_id, p.player_name ORDER BY total_days_missed DESC NULLS LAST, p.player_name LIMIT 1
```

| player_name | total_days_missed |
| --- | --- |
| Jamaal Lascelles | 1132 |

## Q38 — availability (hard, multi_step/scalar)

**Q:** Which club had the most separate injury spells recorded in 2023-2024?

**Status:** `ok`

```sql
SELECT pis.team, COUNT(*) AS spells FROM player_injury_spells pis WHERE pis.season='2023-2024' GROUP BY pis.team ORDER BY spells DESC, pis.team LIMIT 1
```

| team | spells |
| --- | --- |
| Chelsea | 61 |

## Q39 — availability (medium, deterministic_sql/scalar)

**Q:** How many injury spells were recorded for Brentford players in 2023-2024?

**Status:** `ok`

```sql
SELECT COUNT(*) AS spells FROM player_injury_spells pis WHERE pis.season='2023-2024' AND pis.team='Brentford'
```

| spells |
| --- |
| 34 |

## Q40 — event_player_match (hard, multi_step/scalar)

**Q:** Which player attempted the most shots (from event data) in 2023-2024?

**Status:** `ok`

```sql
SELECT p.player_name, COUNT(*) AS shots FROM match_events e JOIN players p ON p.player_id=e.player_id WHERE e.season='2023-2024' AND e.league_code='ENG-PL' AND e.is_shot = TRUE GROUP BY p.player_id, p.player_name ORDER BY shots DESC, p.player_name LIMIT 1
```

| player_name | shots |
| --- | --- |
| Erling Haaland | 121 |

## Q41 — event_player_match (medium, deterministic_sql/table)

**Q:** What is the most goals scored by a single player in one match in 2024-2025?

**Status:** `ok`

```sql
SELECT p.player_name, pmp.game_id, pmp.match_goals FROM player_match_performance pmp JOIN players p ON p.player_id=pmp.player_id WHERE pmp.season='2024-2025' AND pmp.league_code='ENG-PL' ORDER BY pmp.match_goals DESC, p.player_name LIMIT 5
```

| player_name | game_id | match_goals |
| --- | --- | --- |
| Cole Palmer | 1821102 | 4 |
| Alexander Isak | 1821236 | 3 |
| Amad Diallo | 1821316 | 3 |
| Chris Wood | 1821414 | 3 |
| Dango Ouattara | 1821389 | 3 |

## Q42 — event_player_match (hard, multi_step/scalar)

**Q:** Which player committed the most fouls in 2023-2024 (summed across matches)?

**Status:** `ok`

```sql
SELECT p.player_name, SUM(pmp.fouls) AS fouls FROM player_match_performance pmp JOIN players p ON p.player_id=pmp.player_id WHERE pmp.season='2023-2024' AND pmp.league_code='ENG-PL' GROUP BY p.player_id, p.player_name HAVING SUM(pmp.fouls) IS NOT NULL ORDER BY fouls DESC, p.player_name LIMIT 1
```

| player_name | fouls |
| --- | --- |
| Conor Gallagher | 83 |

## Q43 — event_player_match (medium, deterministic_sql/scalar)

**Q:** How many shot events resulted in a goal (is_goal) in 2024-2025?

**Status:** `ok`

```sql
SELECT COUNT(*) AS goal_events FROM match_events e WHERE e.season='2024-2025' AND e.league_code='ENG-PL' AND e.is_goal = TRUE
```

| goal_events |
| --- |
| 1115 |

## Q44 — event_player_match (medium, deterministic_sql/table)

**Q:** What was the biggest home win (by goal margin) in 2024-2025?

**Status:** `ok`

```sql
SELECT ht.team_name AS home_team, at.team_name AS away_team, m.home_score, m.away_score FROM matches m JOIN seasons s ON s.season_id=m.season_id JOIN teams ht ON ht.team_id=m.home_team_id JOIN teams at ON at.team_id=m.away_team_id WHERE s.season='2024-2025' ORDER BY (m.home_score - m.away_score) DESC, m.home_score DESC LIMIT 1
```

| home_team | away_team | home_score | away_score |
| --- | --- | --- | --- |
| Nottingham Forest | Brighton | 7 | 0 |

## Q45 — edge_case (edge_case, deterministic_sql/scalar)

**Q:** How many points did Norwich City get in the 2024-2025 Premier League season?

**Status:** `empty_expected`

```sql
SELECT st.tss_points FROM team_season_standings st JOIN teams t ON t.team_id=st.team_id JOIN seasons s ON s.season_id=st.season_id WHERE s.season='2024-2025' AND t.team_name='Norwich City'
```

_(empty result set)_

## Q46 — edge_case (edge_case, deterministic_sql/scalar)

**Q:** How many matches in the 2020-2021 season have a recorded attendance figure?

**Status:** `ok`

```sql
SELECT COUNT(*) AS matches_with_attendance FROM matches m JOIN seasons s ON s.season_id=m.season_id WHERE s.season='2020-2021' AND m.attendance_m IS NOT NULL
```

| matches_with_attendance |
| --- |
| 32 |
