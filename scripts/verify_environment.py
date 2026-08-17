"""Verify that the local development environment can load the planned stack."""

from __future__ import annotations

import json
import sqlite3
import sys
from importlib.metadata import version
from typing import TypedDict

import gradio as gr
from fastapi import FastAPI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from reduce_token_agent import __version__


class _GraphState(TypedDict):
    value: int


class _SchemaProbe(BaseModel):
    status: str


def _increment(state: _GraphState) -> _GraphState:
    return {"value": state["value"] + 1}


def main() -> None:
    """Run deterministic, network-free smoke checks for the planned dependencies."""
    assert sys.version_info[:2] == (3, 12)
    assert _SchemaProbe(status="ok").status == "ok"
    assert __version__ == "0.1.0"

    api = FastAPI()
    assert api.title == "FastAPI"

    with gr.Blocks() as ui:
        gr.Markdown("ReduceTokenAgent environment check")
    assert ui is not None

    graph_builder = StateGraph(_GraphState)
    graph_builder.add_node("increment", _increment)
    graph_builder.add_edge(START, "increment")
    graph_builder.add_edge("increment", END)
    graph = graph_builder.compile()
    assert graph.invoke({"value": 0}) == {"value": 1}

    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE VIRTUAL TABLE capability_search USING fts5(content)")
    connection.execute("INSERT INTO capability_search(content) VALUES (?)", ("ticket",))
    match = connection.execute(
        "SELECT content FROM capability_search WHERE capability_search MATCH ?",
        ("ticket",),
    ).fetchone()
    connection.close()
    assert match == ("ticket",)

    assert SqliteSaver is not None

    packages = [
        "aiosqlite",
        "fastapi",
        "gradio",
        "httpx",
        "langgraph",
        "langgraph-checkpoint-sqlite",
        "numpy",
        "ollama",
        "pydantic",
        "pydantic-settings",
        "PyYAML",
        "structlog",
        "tenacity",
        "typer",
        "uvicorn",
    ]
    report = {
        "status": "ok",
        "python": sys.version.split()[0],
        "project": __version__,
        "packages": {package: version(package) for package in packages},
        "checks": [
            "package_import",
            "pydantic_validation",
            "fastapi_construction",
            "gradio_blocks_construction",
            "langgraph_compile_and_invoke",
            "sqlite_fts5",
            "langgraph_sqlite_checkpointer_import",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

