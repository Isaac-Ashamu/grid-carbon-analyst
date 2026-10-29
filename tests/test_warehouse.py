from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from grid_carbon_analyst.warehouse import Warehouse, render_catalog


def test_catalog_lists_marts_with_descriptions(warehouse: Warehouse) -> None:
    tables = {t.name: t for t in warehouse.catalog()}
    assert set(tables) == {"agg_daily_national", "agg_daily_regional"}
    national = tables["agg_daily_national"]
    assert national.description == "One row per UTC day, GB-wide."
    described = {c.name: c.description for c in national.columns}
    assert described["mean_actual_gco2_kwh"] == "Mean actual intensity over the day, gCO2/kWh."
    text = render_catalog(warehouse.catalog())
    assert "marts.agg_daily_national: One row per UTC day, GB-wide." in text
    assert "silver" not in text


def test_run_caps_rows_and_reports_truncation(warehouse: Warehouse) -> None:
    result = warehouse.run("select date_day from marts.agg_daily_national order by 1")
    assert result.columns == ["date_day"]
    assert len(result.rows) == 2
    assert result.truncated


def test_run_is_not_truncated_when_rows_fit(warehouse: Warehouse) -> None:
    result = warehouse.run("select count(*) as n from marts.agg_daily_national")
    assert result.rows == [(3,)]
    assert not result.truncated


def test_connection_is_read_only(warehouse: Warehouse) -> None:
    # Defence in depth: even if a write slipped past the guard, the engine refuses it.
    with pytest.raises(duckdb.Error):
        warehouse.run("drop table marts.agg_daily_national")


def test_missing_warehouse_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Build the lakehouse first"):
        Warehouse(tmp_path / "nope.duckdb")
