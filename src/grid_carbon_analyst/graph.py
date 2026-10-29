"""The LangGraph flow: write SQL -> check it -> run it -> answer, retrying on failure.

    write_sql -> check_sql -> run_sql -> answer -> END
        ^            |           |
        +---- error, attempts left ----+
                     |           |
                     +- give_up -+-> END   (no attempts left)

The model never touches the warehouse directly: its SQL goes through
``check_sql`` (static checks) and then a read-only connection with a row cap
and a timeout. Errors from either step go back to the model as feedback.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from grid_carbon_analyst import prompts
from grid_carbon_analyst.sql_guard import UnsafeQueryError, check_sql
from grid_carbon_analyst.warehouse import QueryResult, Warehouse, render_catalog

_SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class AnalystState(TypedDict, total=False):
    question: str
    sql: str
    error: str | None
    attempts: int
    result: QueryResult | None
    answer: str


def extract_sql(text: str) -> str:
    """Pull the query out of a fenced block, falling back to the whole reply."""
    match = _SQL_BLOCK.search(text)
    return (match.group(1) if match else text).strip().rstrip(";").strip()


def format_table(result: QueryResult, max_rows: int = 50) -> str:
    """A small pipe table for the answer prompt."""
    if not result.rows:
        return "(no rows)"
    lines = [" | ".join(result.columns)]
    lines += [" | ".join(_cell(v) for v in row) for row in result.rows[:max_rows]]
    if len(result.rows) > max_rows:
        lines.append(f"... {len(result.rows) - max_rows} more rows")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return "" if value is None else str(value)


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        part.get("text", "") if isinstance(part, dict) else str(part) for part in content
    )


def build_graph(
    llm: BaseChatModel, warehouse: Warehouse, *, max_attempts: int = 3
) -> CompiledStateGraph[AnalystState, Any, AnalystState, AnalystState]:
    tables = warehouse.catalog()
    allowed = [t.name for t in tables]
    write_system = prompts.WRITE_SQL_SYSTEM.format(
        domain_notes=prompts.DOMAIN_NOTES, catalog=render_catalog(tables)
    )
    answer_system = prompts.ANSWER_SYSTEM.format(domain_notes=prompts.DOMAIN_NOTES)

    def write_sql(state: AnalystState) -> AnalystState:
        messages: list[BaseMessage] = [
            SystemMessage(write_system),
            HumanMessage(prompts.WRITE_SQL_USER.format(question=state["question"])),
        ]
        if state.get("error") and state.get("sql"):
            messages += [
                AIMessage(f"```sql\n{state['sql']}\n```"),
                HumanMessage(prompts.RETRY_USER.format(sql=state["sql"], error=state["error"])),
            ]
        reply = llm.invoke(messages)
        return {
            "sql": extract_sql(_text(reply)),
            "error": None,
            "attempts": state.get("attempts", 0) + 1,
        }

    def check(state: AnalystState) -> AnalystState:
        try:
            return {"sql": check_sql(state["sql"], allowed)}
        except UnsafeQueryError as error:
            return {"error": str(error)}

    def run_sql(state: AnalystState) -> AnalystState:
        try:
            return {"result": warehouse.run(state["sql"])}
        except Exception as error:  # any engine error is feedback for the model
            return {"error": f"{type(error).__name__}: {error}".splitlines()[0]}

    def answer(state: AnalystState) -> AnalystState:
        result = state["result"]
        assert result is not None
        reply = llm.invoke(
            [
                SystemMessage(answer_system),
                HumanMessage(
                    prompts.ANSWER_USER.format(
                        question=state["question"],
                        sql=state["sql"],
                        row_count=len(result.rows),
                        truncated=", truncated" if result.truncated else "",
                        table=format_table(result),
                    )
                ),
            ]
        )
        return {"answer": _text(reply).strip()}

    def give_up(state: AnalystState) -> AnalystState:
        return {
            "answer": (
                f"I couldn't answer that with a safe, working query after "
                f"{state.get('attempts', 0)} attempts. Last error: {state.get('error')}"
            )
        }

    def after(next_step: str) -> Any:
        def route(state: AnalystState) -> str:
            if not state.get("error"):
                return next_step
            return "write_sql" if state.get("attempts", 0) < max_attempts else "give_up"

        return route

    graph = StateGraph(AnalystState)
    graph.add_node("write_sql", write_sql)
    graph.add_node("check_sql", check)
    graph.add_node("run_sql", run_sql)
    graph.add_node("answer", answer)
    graph.add_node("give_up", give_up)
    graph.add_edge(START, "write_sql")
    graph.add_edge("write_sql", "check_sql")
    graph.add_conditional_edges("check_sql", after("run_sql"))
    graph.add_conditional_edges("run_sql", after("answer"))
    graph.add_edge("answer", END)
    graph.add_edge("give_up", END)
    return graph.compile()
