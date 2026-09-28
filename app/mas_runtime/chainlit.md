# Premier League Analytics Agent v2

Welcome to the Premier League Analytics Agent!

This AI-powered system helps you analyze Premier League data across multiple seasons.

## How to Use

1. **Select your preferences** in the Settings panel:
   - **Model**: Choose between Claude Sonnet 4.5 or GPT-4o
   - **Data Agent Freedom**: Choose SQL generation approach:
     - *Full Control*: Uses only predefined queries (most reliable)
     - *Semi Control*: Hybrid - can use predefined or generate custom SQL
     - *No Control*: Always generates custom SQL (most flexible)

2. **Ask questions** about:
   - League standings and tables
   - Team performance and statistics
   - Head-to-head records
   - Goals, shots, cards, and other metrics
   - Referee statistics
   - Historical trends

3. **View results**:
   - Natural language responses
   - Data tables (for small results)
   - Interactive visualizations
   - SQL queries used (in steps)

## Available Data

- **Seasons**: 2021_2022 through 2025_2026 (current incomplete)
- **Teams**: 27 teams across all seasons
- **Matches**: 1,759 total matches
- **Stats**: Goals, shots, corners, cards, attendance, referees

## Example Questions

- "What's the league table for 2024_2025?"
- "How many points did Arsenal get in 2023_2024?"
- "Show me Liverpool's goals per season"
- "Compare Man City and Arsenal in 2023_2024"
- "Which referee gives the most red cards?"
- "Top 5 goal scorers this season"

## Powered By

- **LangGraph**: Multi-agent orchestration
- **LiteLLM**: Model routing and caching
- **PostgreSQL**: Aiven database
- **Chainlit**: Conversational UI
