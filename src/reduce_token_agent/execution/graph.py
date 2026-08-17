"""Build the single fixed LangGraph parent graph."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from reduce_token_agent.execution.state import ExecutionGraphState


class GraphNodeHandler(Protocol):
    def load_compiled_blueprint(
        self, state: ExecutionGraphState
    ) -> dict[str, Any]: ...

    def select_ready_step(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def after_select(
        self, state: ExecutionGraphState
    ) -> Literal["dispatch", "finalize"]: ...

    def dispatch(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def validate_output(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def persist_ledger(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def route_next(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def after_route(
        self, state: ExecutionGraphState
    ) -> Literal[
        "select_ready_step",
        "retry_wait",
        "human_interrupt",
        "compensate",
        "finalize",
    ]: ...

    def retry_wait(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def human_interrupt(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def compensate(self, state: ExecutionGraphState) -> dict[str, Any]: ...

    def finalize(self, state: ExecutionGraphState) -> dict[str, Any]: ...


def build_fixed_execution_graph(
    handler: GraphNodeHandler,
    checkpointer: BaseCheckpointSaver[Any],
) -> Any:
    """Compile one immutable parent graph; request Blueprints remain state data."""
    graph = StateGraph(ExecutionGraphState)
    graph.add_node("load_compiled_blueprint", handler.load_compiled_blueprint)
    graph.add_node("select_ready_step", handler.select_ready_step)
    graph.add_node("dispatch", handler.dispatch)
    graph.add_node("validate_output", handler.validate_output)
    graph.add_node("persist_ledger", handler.persist_ledger)
    graph.add_node("route_next", handler.route_next)
    graph.add_node("retry_wait", handler.retry_wait)
    graph.add_node("human_interrupt", handler.human_interrupt)
    graph.add_node("compensate", handler.compensate)
    graph.add_node("finalize", handler.finalize)

    graph.add_edge(START, "load_compiled_blueprint")
    graph.add_edge("load_compiled_blueprint", "select_ready_step")
    graph.add_conditional_edges(
        "select_ready_step",
        handler.after_select,
        {"dispatch": "dispatch", "finalize": "finalize"},
    )
    graph.add_edge("dispatch", "validate_output")
    graph.add_edge("validate_output", "persist_ledger")
    graph.add_edge("persist_ledger", "route_next")
    graph.add_conditional_edges(
        "route_next",
        handler.after_route,
        {
            "select_ready_step": "select_ready_step",
            "retry_wait": "retry_wait",
            "human_interrupt": "human_interrupt",
            "compensate": "compensate",
            "finalize": "finalize",
        },
    )
    graph.add_edge("retry_wait", "select_ready_step")
    graph.add_edge("human_interrupt", "finalize")
    graph.add_edge("compensate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
