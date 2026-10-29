# Grid Carbon Analyst

Ask a plain-English question about the GB electricity grid and get an answer
backed by a real query, with the SQL it used.

```
$ gca ask "Which region had the cleanest electricity on the last complete day?"
North Scotland, at 12 gCO2/kWh (forecast) on 2026-09-13 (UTC) ...

SQL (1 attempt(s)):
SELECT region_name, mean_forecast_gco2_kwh FROM marts.agg_daily_regional ...
```

It sits on top of [uk-grid-carbon-lakehouse](https://github.com/Isaac-Ashamu/uk-grid-carbon-lakehouse)
and reads only its documented dbt marts. The column descriptions written in
dbt are persisted into DuckDB and are what the agent reads to choose tables.

## How it works

A LangGraph flow:

```
write_sql -> check_sql -> run_sql -> answer
     ^           |           |
     +-- error, attempts left --+      (no attempts left -> give_up)
```

1. **write_sql**: the model writes one DuckDB query from the question, the mart
   catalog and some domain notes (UTC everywhere, regional data is forecast only,
   regions 15-18 are aggregates, ...).
2. **check_sql**: static checks with sqlglot. One statement, read-only, known marts
   only, no table functions or file readers. Unqualified mart names are qualified.
3. **run_sql**: a read-only DuckDB connection, a row cap and a timeout.
4. **answer**: the model answers from the result only.

A failed check or a database error goes back to the model as feedback, up to
`GCA_MAX_ATTEMPTS` times.

## Safety

Two independent layers: the SQL guard and a read-only connection. The tests
cover writes, DDL, `ATTACH`, `PRAGMA`, `COPY`, multi-statement input, other
schemas, table functions and file readers, plus a write that is attempted on
every retry and never runs.

## Run it

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env              # set your model API key and the warehouse path
gca catalog                       # what the agent sees
gca ask "When is electricity cleanest in London, by hour of day?"
pytest
```

## Roadmap

- [x] Read-only SQL tool with static checks
- [x] Write -> check -> run -> answer flow with retries
- [ ] Evaluation set of questions with reference SQL, run in CI
- [ ] Retrieval over the dbt docs and worked examples (pgvector)
- [ ] Route to the lakehouse's FastAPI endpoints when one already answers the question
- [ ] Clarifying questions with saved state, and charts
- [ ] Tracing, cost per question, caching and model tiering
- [ ] BigQuery, Vertex AI and Cloud Run, provisioned with Terraform
