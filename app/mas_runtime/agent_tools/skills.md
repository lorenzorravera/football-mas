# SQL Skills Reference for Premier League Database

This document describes 10 common query patterns for the Premier League PostgreSQL database. Use these as examples when writing your own SQL queries.

## Database Schema Overview

**Key Tables:**
- `teams` - Team master data
- `seasons` - Season master data
- `matches` - Match-level data (teams, date, scores)
- `match_team_stats` - Per-team stats (2 rows per match)
- `referees` - Referee master data
- `points_adjustments` - League-imposed deductions/additions
- `league_table` (VIEW) - Pre-computed standings with adjustments

**Important Notes:**
- Team names must match exactly: "Man City" not "Manchester City", "Nott'm Forest" not "Nottingham Forest"
- Season format: "YYYY_YYYY" (e.g., "2023_2024")
- `match_team_stats` has 2 rows per match (one per team)
- Points adjustments are applied via JOIN when calculating standings

---

## 1. League Standings

Get season standings with points adjustments applied.

```sql
-- Full season standings (using pre-built view)
SELECT
    ROW_NUMBER() OVER (ORDER BY points DESC, gd DESC, gf DESC) as position,
    team_name,
    played,
    won,
    drawn,
    lost,
    gf,
    ga,
    gd,
    points,
    points_adjustment
FROM league_table
WHERE season = '2023_2024'
ORDER BY points DESC, gd DESC, gf DESC;
```

**Points adjustments** (e.g., Everton -8, Forest -4 in 2023_2024):
```sql
-- Manual calculation with adjustments
WITH standings AS (
    SELECT
        t.team_name,
        SUM(mts.points) as match_points,
        ...
    FROM match_team_stats mts
    ...
)
SELECT
    s.*,
    COALESCE(pa.total_adjustment, 0) as points_adjustment,
    s.match_points + COALESCE(pa.total_adjustment, 0) as total_points
FROM standings s
LEFT JOIN (
    SELECT team_id, SUM(adjustment) as total_adjustment
    FROM points_adjustments
    WHERE season_id = ...
    GROUP BY team_id
) pa ON s.team_id = pa.team_id;
```

---

## 2. Team Season Statistics

Comprehensive stats for a team in a season.

```sql
SELECT
    t.team_name,
    COUNT(*) as matches_played,
    SUM(CASE WHEN mts.points = 3 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN mts.points = 1 THEN 1 ELSE 0 END) as draws,
    SUM(CASE WHEN mts.points = 0 THEN 1 ELSE 0 END) as losses,
    SUM(mts.goals_scored) as goals_scored,
    SUM(mts.goals_conceded) as goals_conceded,
    SUM(mts.shots) as total_shots,
    SUM(mts.yellow_cards) as yellow_cards,
    SUM(mts.points) as total_points
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN matches m ON mts.match_id = m.match_id
JOIN seasons s ON m.season_id = s.season_id
WHERE t.team_name = 'Arsenal'
AND s.season = '2023_2024'
GROUP BY t.team_name;
```

---

## 3. Head-to-Head Record

All matches between two teams.

```sql
SELECT
    m.match_date,
    s.season,
    ht.team_name as home_team,
    at.team_name as away_team,
    m.ft_home_goals,
    m.ft_away_goals,
    CASE
        WHEN m.ft_result = 'H' THEN ht.team_name
        WHEN m.ft_result = 'A' THEN at.team_name
        ELSE 'Draw'
    END as winner
FROM matches m
JOIN teams ht ON m.home_team_id = ht.team_id
JOIN teams at ON m.away_team_id = at.team_id
JOIN seasons s ON m.season_id = s.season_id
WHERE (
    (ht.team_name = 'Arsenal' AND at.team_name = 'Man City') OR
    (ht.team_name = 'Man City' AND at.team_name = 'Arsenal')
)
ORDER BY m.match_date DESC;
```

---

## 4. Team Form (Recent Matches)

Last N matches for a team.

```sql
SELECT
    m.match_date,
    t.team_name,
    opp.team_name as opponent,
    mts.is_home,
    mts.goals_scored,
    mts.goals_conceded,
    CASE
        WHEN mts.points = 3 THEN 'W'
        WHEN mts.points = 1 THEN 'D'
        ELSE 'L'
    END as result
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN teams opp ON mts.opponent_id = opp.team_id
JOIN matches m ON mts.match_id = m.match_id
WHERE t.team_name = 'Liverpool'
ORDER BY m.match_date DESC
LIMIT 5;
```

---

## 5. Top Goal Scorers

Teams ranked by goals scored.

```sql
SELECT
    ROW_NUMBER() OVER (ORDER BY SUM(mts.goals_scored) DESC) as rank,
    t.team_name,
    SUM(mts.goals_scored) as goals_scored,
    ROUND(AVG(mts.goals_scored), 2) as goals_per_match
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN matches m ON mts.match_id = m.match_id
JOIN seasons s ON m.season_id = s.season_id
WHERE s.season = '2024_2025'
GROUP BY t.team_name
ORDER BY goals_scored DESC
LIMIT 10;
```

---

## 6. Defensive Rankings

Teams with fewest goals conceded or most clean sheets.

```sql
-- Fewest goals conceded
SELECT
    ROW_NUMBER() OVER (ORDER BY SUM(mts.goals_conceded) ASC) as rank,
    t.team_name,
    SUM(mts.goals_conceded) as goals_conceded,
    SUM(CASE WHEN mts.goals_conceded = 0 THEN 1 ELSE 0 END) as clean_sheets
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN matches m ON mts.match_id = m.match_id
JOIN seasons s ON m.season_id = s.season_id
WHERE s.season = '2024_2025'
GROUP BY t.team_name
ORDER BY goals_conceded ASC
LIMIT 10;
```

---

## 7. Match History (Filtered)

Get matches for a team with various filters.

```sql
SELECT
    m.match_date,
    t.team_name,
    opp.team_name as opponent,
    CASE WHEN mts.is_home THEN 'Home' ELSE 'Away' END as venue,
    mts.goals_scored,
    mts.goals_conceded,
    CASE WHEN mts.points = 3 THEN 'W' WHEN mts.points = 1 THEN 'D' ELSE 'L' END as result
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN teams opp ON mts.opponent_id = opp.team_id
JOIN matches m ON mts.match_id = m.match_id
JOIN seasons s ON m.season_id = s.season_id
WHERE t.team_name = 'Chelsea'
AND s.season = '2024_2025'
AND mts.is_home = true  -- Home games only
ORDER BY m.match_date DESC;
```

---

## 8. Compare Two Teams

Side-by-side comparison of team stats.

```sql
SELECT
    t.team_name,
    SUM(CASE WHEN mts.points = 3 THEN 1 ELSE 0 END) as wins,
    SUM(mts.goals_scored) as goals_scored,
    SUM(mts.goals_conceded) as goals_conceded,
    SUM(mts.points) as total_points
FROM match_team_stats mts
JOIN teams t ON mts.team_id = t.team_id
JOIN matches m ON mts.match_id = m.match_id
JOIN seasons s ON m.season_id = s.season_id
WHERE t.team_name IN ('Liverpool', 'Man City')
AND s.season = '2023_2024'
GROUP BY t.team_name;
```

---

## 9. Referee Performance

Statistics for a specific referee.

```sql
SELECT
    r.referee_name,
    COUNT(DISTINCT m.match_id) as matches_officiated,
    SUM(CASE WHEN m.ft_result = 'H' THEN 1 ELSE 0 END) as home_wins,
    SUM(mts.yellow_cards) as total_yellow_cards,
    SUM(mts.red_cards) as total_red_cards,
    ROUND(AVG(m.ft_home_goals + m.ft_away_goals), 2) as avg_goals_per_match
FROM matches m
JOIN referees r ON m.referee_id = r.referee_id
JOIN match_team_stats mts ON m.match_id = mts.match_id
WHERE r.referee_name = 'M Oliver'
GROUP BY r.referee_name;
```

---

## 10. Season-Wide Aggregates

League-wide statistics for a season.

```sql
WITH match_totals AS (
    SELECT
        COUNT(DISTINCT m.match_id) as total_matches,
        SUM(m.ft_home_goals + m.ft_away_goals) as total_goals,
        SUM(mts.yellow_cards) as total_yellows,
        SUM(mts.red_cards) as total_reds,
        SUM(CASE WHEN m.ft_result = 'H' THEN 1 ELSE 0 END) as home_wins
    FROM matches m
    JOIN seasons s ON m.season_id = s.season_id
    JOIN match_team_stats mts ON m.match_id = mts.match_id
    WHERE s.season = '2024_2025'
)
SELECT
    total_matches,
    total_goals,
    ROUND(CAST(total_goals AS FLOAT) / total_matches, 2) as goals_per_match,
    total_yellows,
    ROUND(100.0 * home_wins / total_matches, 1) as home_win_pct
FROM match_totals;
```

---

## Common Patterns

### Home/Away Splits
Use `mts.is_home` to filter:
```sql
WHERE mts.is_home = true   -- Home games
WHERE mts.is_home = false  -- Away games
```

### Date Filtering
```sql
WHERE m.match_date >= '2024-01-01'
AND m.match_date <= '2024-12-31'
```

### Team Name Matching
Always use exact names from the teams table:
- ✓ "Man City"
- ✗ "Manchester City"
- ✓ "Nott'm Forest"
- ✗ "Nottingham Forest"

### Result Conversion
```sql
CASE
    WHEN mts.points = 3 THEN 'W'
    WHEN mts.points = 1 THEN 'D'
    ELSE 'L'
END as result
```

### Ordering (Premier League Tiebreakers)
```sql
ORDER BY points DESC, gd DESC, gf DESC
```

This follows Premier League rules: Points → Goal Difference → Goals For.
