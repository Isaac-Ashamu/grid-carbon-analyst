"""Static checks on model-written SQL before it reaches the warehouse.

The warehouse connection is already read-only, so these checks are the second
layer, not the only one. They keep the agent inside the documented marts:

* exactly one statement, and it must be a query (SELECT / WITH / UNION ...)
* every table it reads is a known mart (or a CTE defined in the query)
* no table functions or file readers (``read_parquet``, ``glob``, ...), so the
  model cannot reach files, other databases or settings around the marts

Unqualified mart names are qualified with ``marts.`` so the model can write
``agg_daily_national`` instead of ``marts.agg_daily_national``.
"""

from __future__ import annotations

from collections.abc import Collection

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

MARTS_SCHEMA = "marts"

# Functions that read files, other databases or engine state. Matched on the
# lower-cased function name wherever it appears, not just in FROM.
BLOCKED_FUNCTIONS = frozenset(
    {
        "read_parquet", "parquet_scan", "parquet_metadata", "parquet_schema",
        "read_csv", "read_csv_auto", "read_json", "read_json_auto", "read_ndjson",
        "read_text", "read_blob", "glob", "sniff_csv",
        "sqlite_scan", "postgres_scan", "mysql_scan", "iceberg_scan", "delta_scan",
        "query", "query_table", "getenv", "current_setting",
    }
)  # fmt: skip


class UnsafeQueryError(ValueError):
    """The SQL failed a check. The message is written to be fed back to the model."""


def check_sql(sql: str, allowed_tables: Collection[str]) -> str:
    """Return the query re-rendered with qualified table names, or raise UnsafeQueryError."""
    allowed = {name.lower() for name in allowed_tables}
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except ParseError as error:
        raise UnsafeQueryError(f"The SQL does not parse: {error}") from error

    if len(statements) != 1:
        raise UnsafeQueryError("Write exactly one SQL statement.")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("Only read queries (SELECT) are allowed.")

    for func in tree.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name in BLOCKED_FUNCTIONS:
            raise UnsafeQueryError(f"The function {name}() is not allowed. Query the marts only.")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise UnsafeQueryError("Table functions are not allowed. Query the marts by name.")
        name = table.name.lower()
        schema = table.db.lower()
        if table.catalog:
            raise UnsafeQueryError("Do not name a database. Query the marts by name.")
        if not schema and name in cte_names:
            continue
        if schema not in ("", MARTS_SCHEMA) or name not in allowed:
            shown = f"{schema}.{name}" if schema else name
            raise UnsafeQueryError(
                f"Unknown table {shown}. Use only these marts: {', '.join(sorted(allowed))}."
            )
        table.set("db", exp.to_identifier(MARTS_SCHEMA))

    return tree.sql(dialect="duckdb")
