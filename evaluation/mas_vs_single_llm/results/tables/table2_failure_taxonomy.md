# Table 2 — Semi-controlled failure taxonomy

Classification of every semi-controlled run that did not score correct.

| code | failure mode | claude | gpt | gemini | total |
|---|---|---|---|---|---|
| A | chose template when SQL needed | 0 | 0 | 0 | 0 |
| B | wrong template / params | 2 | 3 | 2 | 7 |
| C | template failed → SQL fallback, still wrong | 0 | 0 | 0 | 0 |
| D | free-SQL generation wrong | 2 | 2 | 2 | 6 |
| E | errored / unclassified | 0 | 0 | 0 | 0 |
