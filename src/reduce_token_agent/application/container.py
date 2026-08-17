"""Dependency assembly for the local control-plane process."""

from __future__ import annotations

from pathlib import Path

from reduce_token_agent.control_plane.blueprint_compiler import BlueprintCompiler
from reduce_token_agent.control_plane.capability_retrieval import CapabilityRetrievalService
from reduce_token_agent.control_plane.config import ControlPlaneSettings
from reduce_token_agent.control_plane.contract_reranker import ContractReranker
from reduce_token_agent.control_plane.decomposer import TaskDecomposer
from reduce_token_agent.control_plane.mode_router import ModeRouter
from reduce_token_agent.control_plane.normalizer import TaskNormalizer
from reduce_token_agent.control_plane.output_guard import OutputGuard
from reduce_token_agent.control_plane.plan_proposer import PlanProposer
from reduce_token_agent.control_plane.sad_aligner import SadAligner
from reduce_token_agent.control_plane.service import ControlPlaneDependencies, ControlPlaneService
from reduce_token_agent.control_plane.trace_recorder import ControlTraceRecorder
from reduce_token_agent.domain.blueprint import BlueprintBudget
from reduce_token_agent.execution.meta_executor import LangGraphMetaExecutor
from reduce_token_agent.llm.embeddings import OllamaEmbeddingProvider
from reduce_token_agent.llm.ollama_client import OllamaStructuredModel
from reduce_token_agent.registry.retrieval_repository import RetrievalRepository
from reduce_token_agent.registry.service import AssetResolver
from reduce_token_agent.system2.executor import BoundedSystem2Executor


def build_control_plane(
    project_root: Path,
    *,
    settings: ControlPlaneSettings | None = None,
) -> ControlPlaneService:
    """Build one local service; no external control platform is required."""
    resolved = settings or ControlPlaneSettings()
    retrieval_repository = RetrievalRepository(project_root)
    retrieval_repository.migrate()
    resolver = AssetResolver(retrieval_repository)
    model = OllamaStructuredModel(
        model=resolved.agent_model,
        host=resolved.ollama_host,
    )
    embedding = OllamaEmbeddingProvider(
        model=resolved.embedding_model,
        host=resolved.ollama_host,
    )
    trace = ControlTraceRecorder(
        project_root / "data/db/runtime.sqlite3",
        project_root / "migrations/004_control_trace.sql",
    )
    langgraph = LangGraphMetaExecutor(
        project_root=project_root,
        resolver=resolver,
        trace=trace,
    )
    system2 = BoundedSystem2Executor(
        project_root=project_root,
        model=model,
        resolver=resolver,
        trace=trace,
    )
    budget = BlueprintBudget(
        max_steps=resolved.max_blueprint_steps,
        max_reason_steps=resolved.max_reason_steps,
        max_llm_calls=resolved.max_system2_llm_calls,
        max_tool_calls=resolved.max_system2_tool_calls,
        max_wall_time_seconds=resolved.max_wall_time_seconds,
        max_token_budget=resolved.max_token_budget,
    )
    return ControlPlaneService(
        ControlPlaneDependencies(
            normalizer=TaskNormalizer(model),
            decomposer=TaskDecomposer(model, max_subgoals=resolved.max_subgoals),
            retriever=CapabilityRetrievalService(retrieval_repository, embedding),
            reranker=ContractReranker(
                resolver,
                top_n=resolved.rerank_top_n,
                supported_asset_schema_version=resolved.supported_asset_schema_version,
            ),
            sad_aligner=SadAligner(model),
            proposer=PlanProposer(model, budget=budget),
            compiler=BlueprintCompiler(
                resolver,
                supported_asset_schema_version=resolved.supported_asset_schema_version,
                allow_validated_draft_view=resolved.allow_validated_draft_view,
            ),
            mode_router=ModeRouter(),
            guard=OutputGuard(),
            resolver=resolver,
            model=model,
            trace=trace,
            langgraph=langgraph,
            system2=system2,
            settings=resolved,
        )
    )
