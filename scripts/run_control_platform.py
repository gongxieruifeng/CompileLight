"""Run the local control platform from the command line."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from reduce_token_agent.application.facade import ApplicationFacade
from reduce_token_agent.domain.task import TaskRequest

app = typer.Typer(add_completion=False)


@app.command()
def plan(
    query: str = typer.Argument(..., min=2),
    tenant_id: str = typer.Option("local"),
    principal_id: str = typer.Option(...),
    scopes: list[str] | None = typer.Option(None),  # noqa: B008
) -> None:
    """Normalize, retrieve, compile, and route one local task."""
    project_root = Path(__file__).resolve().parents[1]
    try:
        result = ApplicationFacade(project_root).plan_task(
            TaskRequest(
                query=query,
                tenant_id=tenant_id,
                principal_id=principal_id,
                scopes=scopes or [],
            )
        )
    except Exception as exc:
        trace_match = re.search(r"trace_ref=(trace://\S+)", str(exc))
        typer.echo(
            json.dumps(
                {
                    "event": "control_run_failed",
                    "error": str(exc),
                    "trace_ref": trace_match.group(1) if trace_match else None,
                },
                ensure_ascii=False,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc
    else:
        typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
