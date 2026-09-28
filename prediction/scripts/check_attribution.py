"""Compare old vs new team-attribution drop rates against the live DB."""
from prediction_agent.data import aiven_loader
import pandas as pd

LEAGUE = "ENG-PL"

NEW_QUERY = """
WITH pmp_with_match AS (
    SELECT pmp.game_id, pmp.player_id, s.season_id,
           m.home_team_id, m.away_team_id,
           pmp.xg_pmp, pmp.npxg_pmp, pmp.xa_pmp, pmp.xgchain_pmp,
           pmp.xgbuildup_pmp, pmp.key_passes_pmp, pmp.match_shots,
           pmp.shots_on_target_pmp, pmp.minutes_played
    FROM player_match_performance pmp
    JOIN seasons s ON s.season = pmp.season
    JOIN competitions c ON s.competition_id = c.competition_id
    JOIN matches m ON m.game_id = pmp.game_id
    WHERE c.league_code = %s
),
player_match_team AS (
    SELECT DISTINCT ON (pm.game_id, pm.player_id)
           pm.*, pss.team_id AS resolved_team_id
    FROM pmp_with_match pm
    JOIN player_season_stats pss
      ON pss.player_id = pm.player_id
     AND pss.season_id = pm.season_id
     AND pss.team_id IN (pm.home_team_id, pm.away_team_id)
    ORDER BY pm.game_id, pm.player_id, pss.starts DESC NULLS LAST
),
team_match_aggregated AS (
    SELECT game_id, resolved_team_id AS team_id,
           COALESCE(SUM(xg_pmp),0)::float AS team_xg
    FROM player_match_team
    GROUP BY game_id, resolved_team_id
)
SELECT tma.*,
       CASE WHEN m.home_team_id = tma.team_id THEN 'home'
            WHEN m.away_team_id = tma.team_id THEN 'away'
            ELSE 'unknown' END AS side
FROM team_match_aggregated tma
JOIN matches m ON m.game_id = tma.game_id
"""

with aiven_loader._connection() as c:
    new = pd.read_sql(NEW_QUERY, c, params=[LEAGUE])
    # player-match resolution coverage
    cov = pd.read_sql("""
      WITH pmp_with_match AS (
        SELECT pmp.game_id, pmp.player_id, s.season_id, m.home_team_id, m.away_team_id
        FROM player_match_performance pmp
        JOIN seasons s ON s.season = pmp.season
        JOIN competitions c ON s.competition_id = c.competition_id
        JOIN matches m ON m.game_id = pmp.game_id
        WHERE c.league_code = %s)
      SELECT
        (SELECT COUNT(*) FROM pmp_with_match) AS total_player_matches,
        (SELECT COUNT(*) FROM pmp_with_match pm
           WHERE EXISTS (SELECT 1 FROM player_season_stats pss
             WHERE pss.player_id=pm.player_id AND pss.season_id=pm.season_id
               AND pss.team_id IN (pm.home_team_id, pm.away_team_id))) AS resolved
    """, c, params=[LEAGUE])

print(f"NEW total team-match rows: {len(new)}")
print(f"NEW unknown rows: {(new['side']=='unknown').sum()}  "
      f"({100*(new['side']=='unknown').mean():.1f}%)")
print()
t, r = int(cov['total_player_matches'][0]), int(cov['resolved'][0])
print(f"player-match resolution: {r}/{t} resolved "
      f"({100*r/t:.1f}%), {t-r} unresolved ({100*(t-r)/t:.1f}%)")
print()
print("OLD method dropped 1692 team-match rows (~31%). Compare to NEW unknown above.")
