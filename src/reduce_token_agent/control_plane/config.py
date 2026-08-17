"""Typed control-plane limits; no safety budget is hidden in prompts."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ControlPlaneSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_model: str = "qwen3.5:9b"
    embedding_model: str = "qwen3-embedding:0.6b"
    ollama_host: str = "http://127.0.0.1:11434"
    max_subgoals: int = Field(default=6, ge=1, le=8)
    initial_retrieval_top_k: int = Field(default=6, ge=1, le=20)
    per_subgoal_retrieval_top_k: int = Field(default=5, ge=1, le=20)
    graph_top_k: int = Field(default=6, ge=0, le=20)
    rerank_top_n: int = Field(default=3, ge=1, le=10)
    max_blueprint_steps: int = Field(default=12, ge=1, le=50)
    # System2 is still bounded, but the default must cover ordinary NEW/HYBRID
    # tasks without turning the normal path into an immediate human stop.
    max_reason_steps: int = Field(default=6, ge=0, le=10)
    max_system2_llm_calls: int = Field(default=6, ge=0, le=10)
    max_system2_tool_calls: int = Field(default=8, ge=0, le=20)
    max_wall_time_seconds: int = Field(default=180, ge=1, le=3600)
    max_token_budget: int = Field(default=24000, ge=0, le=200000)
    max_planning_llm_calls: int = Field(default=5, ge=1, le=10)
    plan_repair_attempts: int = Field(default=1, ge=0, le=1)
    supported_asset_schema_version: str = "registry-asset.v1"
    allow_validated_draft_view: bool = True

    @classmethod
    def from_yaml(cls, path: Path) -> ControlPlaneSettings:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls.model_validate(payload)
