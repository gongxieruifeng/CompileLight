"""Synthetic trace collection models and generation utilities."""

from reduce_token_agent.trace_data.catalog import SCENARIOS, ScenarioSpec
from reduce_token_agent.trace_data.models import SyntheticTraceEnvelope

__all__ = ["SCENARIOS", "ScenarioSpec", "SyntheticTraceEnvelope"]
from reduce_token_agent.trace_data.runtime_models import RuntimeTraceEnvelope

__all__ = ["RuntimeTraceEnvelope"]
