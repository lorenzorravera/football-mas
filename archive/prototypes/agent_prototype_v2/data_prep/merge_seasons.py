import pandas as pd

df_21 = pd.read_csv("premier_league_21.csv")
df_22 = pd.read_csv("premier_league_22.csv")
df_23 = pd.read_csv("premier_league_23.csv")
df_24 = pd.read_csv("premier_league_24.csv")
df_25 = pd.read_csv("premier_league_25.csv")

# Column mapping: old_name -> new_name
column_mapping = {
    'Div': 'league_division',
    'Date': 'match_date',
    'Time': 'match_kickoff_time',
    'HomeTeam': 'home_team',
    'AwayTeam': 'away_team',
    'FTHG': 'full_time_home_team_goals',
    'FTAG': 'full_time_away_team_goals',
    'FTR': 'full_time_result',
    'HTHG': 'half_time_home_team_goals',
    'HTAG': 'half_time_away_team_goals',
    'HTR': 'half_time_result',
    'Referee': 'match_referee',
    'HS': 'home_team_shots',
    'AS': 'away_team_shots',
    'HST': 'home_team_shots_on_target',
    'AST': 'away_team_shots_on_target',
    'HF': 'home_team_fouls_committed',
    'AF': 'away_team_fouls_committed',
    'HC': 'home_team_corners',
    'AC': 'away_team_corners',
    'HY': 'home_team_yellow_cards',
    'AY': 'away_team_yellow_cards',
    'HR': 'home_team_red_cards',
    'AR': 'away_team_red_cards'
}

# Season mapping
season_mapping = {
    21: '2021_2022',
    22: '2022_2023',
    23: '2023_2024',
    24: '2024_2025',
    25: '2025_2026'
}

# DataFrames with their year identifiers
dataframes = [
    (df_21, 21),
    (df_22, 22),
    (df_23, 23),
    (df_24, 24),
    (df_25, 25)
]

# Process each dataframe: select columns, rename, add season
processed_dfs = []
for df, year in dataframes:
    df_subset = df[list(column_mapping.keys())].copy()
    df_subset = df_subset.rename(columns=column_mapping)
    df_subset['season'] = season_mapping[year]
    processed_dfs.append(df_subset)

# Concatenate all
df_merged = pd.concat(processed_dfs, ignore_index=True)

# Save to CSV
df_merged.to_csv('premier_league_merged.csv', index=False)