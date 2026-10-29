from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from grid_carbon_analyst.warehouse import Warehouse


@pytest.fixture
def warehouse_path(tmp_path: Path) -> Path:
    """A tiny stand-in for the lakehouse warehouse: two documented marts."""
    path = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema marts")
    con.execute(
        """
        create table marts.agg_daily_national as
        select * from (values
            (date '2026-09-12', true, 120.5, 45.0),
            (date '2026-09-13', true, 98.25, 55.5),
            (date '2026-09-14', false, 150.0, 30.0)
        ) as t(date_day, is_complete_day, mean_actual_gco2_kwh, mean_renewable_pct)
        """
    )
    con.execute(
        """
        create table marts.agg_daily_regional as
        select * from (values
            (date '2026-09-13', 1, 'North Scotland', false, 12.0),
            (date '2026-09-13', 13, 'London', false, 160.0),
            (date '2026-09-13', 18, 'GB', true, 98.0)
        ) as t(date_day, region_id, region_name, is_aggregate, mean_forecast_gco2_kwh)
        """
    )
    con.execute("create schema silver")
    con.execute("create table silver.secret as select 1 as x")
    con.execute("comment on table marts.agg_daily_national is 'One row per UTC day, GB-wide.'")
    con.execute(
        "comment on column marts.agg_daily_national.mean_actual_gco2_kwh is "
        "'Mean actual intensity over the day, gCO2/kWh.'"
    )
    con.close()
    return path


@pytest.fixture
def warehouse(warehouse_path: Path) -> Iterator[Warehouse]:
    wh = Warehouse(warehouse_path, max_rows=2, timeout_s=5)
    yield wh
    wh.close()
