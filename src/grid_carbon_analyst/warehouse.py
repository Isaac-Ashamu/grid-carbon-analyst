"""Read-only access to the lakehouse marts: the catalog and query execution."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from grid_carbon_analyst.sql_guard import MARTS_SCHEMA


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    description: str


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool


class QueryTimeoutError(RuntimeError):
    pass


class Warehouse:
    """A read-only DuckDB connection to the lakehouse warehouse file."""

    def __init__(self, path: Path, *, max_rows: int = 200, timeout_s: float = 10.0) -> None:
        if not path.exists():
            raise FileNotFoundError(f"Warehouse not found at {path}. Build the lakehouse first.")
        self._con = duckdb.connect(str(path), read_only=True)
        self._con.execute("SET TimeZone = 'UTC'")
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def close(self) -> None:
        self._con.close()

    def catalog(self) -> list[Table]:
        """The marts with their dbt descriptions (persisted as DuckDB comments)."""
        tables = self._con.execute(
            "select table_name, coalesce(comment, '') from duckdb_tables() "
            "where schema_name = ? order by table_name",
            [MARTS_SCHEMA],
        ).fetchall()
        columns = self._con.execute(
            "select table_name, column_name, data_type, coalesce(comment, '') "
            "from duckdb_columns() where schema_name = ? order by table_name, column_index",
            [MARTS_SCHEMA],
        ).fetchall()
        by_table: dict[str, list[Column]] = {}
        for table_name, column_name, data_type, description in columns:
            by_table.setdefault(table_name, []).append(Column(column_name, data_type, description))
        return [
            Table(name, description, tuple(by_table.get(name, []))) for name, description in tables
        ]

    def run(self, sql: str) -> QueryResult:
        """Run a checked query, returning at most ``max_rows`` rows."""
        timer = threading.Timer(self.timeout_s, self._con.interrupt)
        timer.start()
        try:
            cursor = self._con.execute(sql)
            rows = cursor.fetchmany(self.max_rows + 1)
        except duckdb.InterruptException as error:
            raise QueryTimeoutError(
                f"The query took longer than {self.timeout_s:g}s. Aggregate more or filter by date."
            ) from error
        finally:
            timer.cancel()
        columns = [d[0] for d in cursor.description or []]
        return QueryResult(columns, rows[: self.max_rows], truncated=len(rows) > self.max_rows)


def render_catalog(tables: list[Table]) -> str:
    """The catalog as compact text for the prompt."""
    lines: list[str] = []
    for table in tables:
        lines.append(f"marts.{table.name}: {table.description}".rstrip(": "))
        for col in table.columns:
            detail = f" - {col.description}" if col.description else ""
            lines.append(f"  {col.name} ({col.data_type}){detail}")
        lines.append("")
    return "\n".join(lines).strip()
