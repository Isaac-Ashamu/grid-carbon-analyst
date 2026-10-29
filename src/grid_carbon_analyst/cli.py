"""Command line: ``gca ask "Which region was cleanest last week?"``."""

from __future__ import annotations

import typer
from langchain.chat_models import init_chat_model

from grid_carbon_analyst.config import get_settings
from grid_carbon_analyst.graph import build_graph
from grid_carbon_analyst.warehouse import Warehouse, render_catalog

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def ask(question: str, show_sql: bool = typer.Option(True, help="Print the SQL used.")) -> None:
    """Answer a question about the GB grid from the lakehouse marts."""
    settings = get_settings()
    warehouse = Warehouse(
        settings.warehouse_path, max_rows=settings.max_rows, timeout_s=settings.query_timeout_s
    )
    try:
        graph = build_graph(
            init_chat_model(settings.model), warehouse, max_attempts=settings.max_attempts
        )
        state = graph.invoke({"question": question})
    finally:
        warehouse.close()
    typer.echo(state["answer"])
    if show_sql and state.get("sql"):
        typer.echo(f"\nSQL ({state.get('attempts', 0)} attempt(s)):\n{state['sql']}")


@app.command()
def catalog() -> None:
    """Print the marts and column descriptions the agent sees."""
    settings = get_settings()
    warehouse = Warehouse(settings.warehouse_path)
    try:
        typer.echo(render_catalog(warehouse.catalog()))
    finally:
        warehouse.close()
