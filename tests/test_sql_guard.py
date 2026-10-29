from __future__ import annotations

import pytest

from grid_carbon_analyst.sql_guard import UnsafeQueryError, check_sql

MARTS = ["agg_daily_national", "agg_daily_regional"]


def test_qualifies_unqualified_marts() -> None:
    sql = check_sql("select date_day from agg_daily_national", MARTS)
    assert "marts.agg_daily_national" in sql


def test_allows_qualified_marts_joins_and_ctes() -> None:
    sql = check_sql(
        """
        with clean as (
            select date_day, min(mean_forecast_gco2_kwh) as best
            from marts.agg_daily_regional where not is_aggregate group by 1
        )
        select n.date_day, n.mean_actual_gco2_kwh, c.best
        from agg_daily_national n join clean c using (date_day)
        """,
        MARTS,
    )
    assert "marts.agg_daily_regional" in sql
    assert "marts.agg_daily_national" in sql
    assert "marts.clean" not in sql


def test_allows_union_and_subqueries() -> None:
    check_sql(
        "select date_day from agg_daily_national "
        "where mean_actual_gco2_kwh < (select avg(mean_actual_gco2_kwh) from agg_daily_national) "
        "union all select date_day from agg_daily_regional",
        MARTS,
    )


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("drop table marts.agg_daily_national", "Only read queries"),
        ("delete from agg_daily_national", "Only read queries"),
        ("insert into agg_daily_national values (1)", "Only read queries"),
        ("create table x as select 1", "Only read queries"),
        ("attach 'other.db' as other", "Only read queries"),
        ("pragma database_list", "Only read queries"),
        ("set threads = 1", "Only read queries"),
        ("copy agg_daily_national to 'out.csv'", "Only read queries"),
        ("select 1; drop table agg_daily_national", "exactly one"),
        ("select * from silver.secret", "Unknown table silver.secret"),
        ("select * from main.agg_daily_national", "Unknown table main.agg_daily_national"),
        ("select * from staging.stg_intensity_national", "Unknown table"),
        ("select * from information_schema.tables", "Unknown table"),
        ("select * from other.marts.agg_daily_national", "Do not name a database"),
        ("select * from read_parquet('data/silver/*.parquet')", "read_parquet"),
        ("select * from read_csv_auto('/etc/passwd')", "read_csv_auto"),
        ("select * from duckdb_tables()", "Table functions"),
        ("select getenv('HOME')", "getenv"),
        ("select * from glob('*')", "glob"),
        ("select * from", "does not parse"),
    ],
)
def test_rejects_unsafe_or_unknown_sql(sql: str, message: str) -> None:
    with pytest.raises(UnsafeQueryError, match=message):
        check_sql(sql, MARTS)


def test_injection_hidden_in_a_string_literal_stays_a_string() -> None:
    # A question can smuggle instructions into a filter value; it must remain data.
    sql = check_sql(
        "select * from agg_daily_regional where region_name = 'x''; drop table marts.y; --'",
        MARTS,
    )
    assert sql.lower().startswith("select")
