from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from grid_carbon_analyst.graph import build_graph, extract_sql
from grid_carbon_analyst.warehouse import Warehouse


def _sql(query: str) -> str:
    return f"```sql\n{query}\n```"


def test_extract_sql_reads_fenced_block_and_strips_semicolon() -> None:
    assert extract_sql("Here you go:\n```sql\nselect 1;\n```") == "select 1"
    assert extract_sql("select 2") == "select 2"


def test_happy_path_answers_in_one_attempt(warehouse: Warehouse) -> None:
    llm = FakeListChatModel(
        responses=[
            _sql(
                "select date_day, mean_actual_gco2_kwh from agg_daily_national "
                "where is_complete_day order by mean_actual_gco2_kwh limit 1"
            ),
            "The cleanest complete day was 2026-09-13 at 98.25 gCO2/kWh.",
        ]
    )
    state = build_graph(llm, warehouse).invoke({"question": "Which day was cleanest?"})
    assert state["attempts"] == 1
    assert state["result"].rows[0][1] == 98.25
    assert "marts.agg_daily_national" in state["sql"]
    assert state["answer"].startswith("The cleanest complete day")


def test_blocked_query_is_fed_back_and_retried(warehouse: Warehouse) -> None:
    llm = FakeListChatModel(
        responses=[
            _sql("select * from silver.secret"),
            _sql("select count(*) as days from agg_daily_national"),
            "There are 3 days of data.",
        ]
    )
    state = build_graph(llm, warehouse).invoke({"question": "How many days?"})
    assert state["attempts"] == 2
    assert state["result"].rows == [(3,)]
    assert state["answer"] == "There are 3 days of data."


def test_engine_error_is_fed_back_and_retried(warehouse: Warehouse) -> None:
    llm = FakeListChatModel(
        responses=[
            _sql("select no_such_column from agg_daily_national"),
            _sql("select max(mean_renewable_pct) as best from agg_daily_national"),
            "The highest daily renewable share was 55.5%.",
        ]
    )
    state = build_graph(llm, warehouse).invoke({"question": "Best renewable day?"})
    assert state["attempts"] == 2
    assert state["result"].rows == [(55.5,)]


def test_gives_up_after_max_attempts_without_running_anything(warehouse: Warehouse) -> None:
    llm = FakeListChatModel(responses=[_sql("drop table agg_daily_national")] * 3)
    state = build_graph(llm, warehouse, max_attempts=3).invoke({"question": "Delete it all"})
    assert state["attempts"] == 3
    assert "result" not in state or state["result"] is None
    assert state["answer"].startswith("I couldn't answer that")
    # The table is still there.
    assert warehouse.run("select count(*) from marts.agg_daily_national").rows == [(3,)]
