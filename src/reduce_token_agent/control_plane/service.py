"""End-to-end control flow: normalize, retrieve, align, propose, compile, route."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from reduce_token_agent.control_plane.blueprint_compiler import BlueprintCompiler
from reduce_token_agent.control_plane.capability_retrieval import (
    CapabilityRetrievalService,
)
from reduce_token_agent.control_plane.config import ControlPlaneSettings
from reduce_token_agent.control_plane.contract_reranker import ContractReranker
from reduce_token_agent.control_plane.decomposer import TaskDecomposer
from reduce_token_agent.control_plane.failure_router import fixed_failure_policy
from reduce_token_agent.control_plane.final_response import compose_final_response
from reduce_token_agent.control_plane.mode_router import ModeRouter
from reduce_token_agent.control_plane.normalizer import TaskNormalizer
from reduce_token_agent.control_plane.output_guard import OutputGuard
from reduce_token_agent.control_plane.plan_proposer import PlanProposer
from reduce_token_agent.control_plane.sad_aligner import SadAligner
from reduce_token_agent.control_plane.trace_recorder import ControlTraceRecorder
from reduce_token_agent.domain.blueprint import (
    BlueprintBudget,
    Destination,
    PipelineMode,
    RegistryViewRef,
)
from reduce_token_agent.domain.capability import (
    RetrievalPhase,
    RetrievalQuery,
    VisibilityPolicy,
)
from reduce_token_agent.domain.control import (
    ControlPlatformResult,
    CoverageSummary,
    HandoffReceipt,
    LangGraphHandoff,
    RoutingDecision,
    System2Handoff,
)
from reduce_token_agent.domain.task import ClarificationRequest, TaskRequest
from reduce_token_agent.execution.port import LangGraphExecutionPort
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage
from reduce_token_agent.system2.port import System2Port


@dataclass(frozen=True, slots=True)
class ControlPlaneDependencies:
    """Ports and services required by the control flow."""

    normalizer: TaskNormalizer
    decomposer: TaskDecomposer
    retriever: CapabilityRetrievalService
    reranker: ContractReranker
    sad_aligner: SadAligner
    proposer: PlanProposer
    compiler: BlueprintCompiler
    mode_router: ModeRouter
    guard: OutputGuard
    resolver: Any
    model: StructuredModel
    trace: ControlTraceRecorder
    langgraph: LangGraphExecutionPort
    system2: System2Port
    settings: ControlPlaneSettings


class ControlPlaneService:
    """Plan, compile, and execute deterministic Blueprint steps."""

    def __init__(self, dependencies: ControlPlaneDependencies) -> None:
        self.d = dependencies

    def plan(self, request: TaskRequest) -> ControlPlatformResult:
        """Plan one request and preserve a reviewable trace even on failure."""
        run_id = "run_" + secrets.token_hex(8)
        try:
            return self._plan_with_run_id(request, run_id)
        except Exception as exc:
            code = str(getattr(exc, "code", type(exc).__name__.upper()))
            trace_ref = self.d.trace.fail(
                run_id=run_id,
                task_id=None,
                stage="control_plane",
                failure_code=code,
                message=str(exc)[:500],
            )
            raise RuntimeError(f"{exc} [trace_ref={trace_ref}]") from exc

    def _plan_with_run_id(
        self,
        request: TaskRequest,
        run_id: str,
    ) -> ControlPlatformResult:
        self.d.trace.migrate()
        self.d.trace.start(
            run_id=run_id,
            query=request.query,
            tenant_id=request.tenant_id,
            principal_id=request.principal_id,
        )
        normalized = self.d.normalizer.normalize(request)
        self.d.trace.event(
            run_id=run_id,
            stage="normalize",
            event_type="completed",
            payload=normalized.clarification or normalized.context or {},
        )
        if normalized.context is None:
            routing = RoutingDecision(
                mode=PipelineMode.CLARIFY,
                destinations=[Destination.HUMAN],
                coverage=CoverageSummary(
                    required_subgoals=0,
                    deterministic_covered=0,
                    gap_covered=0,
                    uncovered=0,
                    deterministic_ratio=0.0,
                ),
                reason_codes=["MISSING_IDENTITY"],
            )
            guard = self.d.guard.validate(
                routing=routing,
                has_compiled_blueprint=False,
                has_langgraph_handoff=False,
                has_system2_handoff=False,
                receipt_statuses=[],
            )
            final_response, final_usage = compose_final_response(
                run_id=run_id,
                routing=routing,
                execution_status="CLARIFY",
                proposal=None,
                langgraph_receipt=None,
                system2_receipt=None,
                clarification=normalized.clarification,
            )
            if final_usage is not None:
                self._usage(run_id, final_usage)
            self.d.trace.event(
                run_id=run_id,
                stage="final_response",
                event_type="completed",
                payload=final_response,
            )
            trace_ref = self.d.trace.finish(
                run_id=run_id,
                task_id=None,
                status="CLARIFY",
                mode=routing.mode.value,
                destinations=[item.value for item in routing.destinations],
            )
            return _result(
                run_id=run_id,
                context=None,
                clarification=normalized.clarification,
                routing=routing,
                guard=guard,
                trace_ref=trace_ref,
                final_response={**final_response, "trace_ref": trace_ref},
            )

        context = normalized.context
        decomposition, usage = self.d.decomposer.decompose(context)
        self._usage(run_id, usage)
        self.d.trace.event(
            run_id=run_id,
            stage="decompose",
            event_type="completed",
            payload=decomposition,
        )
        state = self.d.retriever.repository.current_index()
        visibility = VisibilityPolicy(state.visibility_policy)
        view = RegistryViewRef(
            index_id=state.index_id,
            asset_set_digest=state.asset_set_digest,
            visibility_policy=visibility,
            snapshot_id=state.snapshot_id,
        )
        initial = self.d.retriever.retrieve(
            RetrievalQuery(
                text=context.query,
                phase=RetrievalPhase.INITIAL,
                domains=context.domain_hints,
                scopes=context.scopes,
                tenant_id=context.tenant_id,
                environment=context.environment,
                data_classification=context.data_classification.value,
                risk_ceiling=context.risk_level,
                top_k=self.d.settings.initial_retrieval_top_k,
                graph_top_k=self.d.settings.graph_top_k,
                visibility_policy=visibility,
                snapshot_id=state.snapshot_id,
            )
        )
        self.d.trace.event(
            run_id=run_id,
            stage="retrieve_initial",
            event_type="completed",
            payload=initial,
        )
        summaries = [
            (
                candidate.model_dump(mode="json"),
                self.d.reranker._score(context, decomposition.subgoals[0], candidate).contract,
            )
            for candidate in initial.candidates[: self.d.settings.initial_retrieval_top_k]
        ] if decomposition.subgoals else []
        alignment, usage = self.d.sad_aligner.align_once(
            context=context,
            decomposition=decomposition,
            candidate_summaries=summaries,
        )
        self._usage(run_id, usage)
        self.d.trace.event(
            run_id=run_id,
            stage="sad_align",
            event_type="completed",
            payload=alignment,
        )
        subgoal_results: list[tuple[Any, Any]] = []
        for subgoal in alignment.aligned_subgoals:
            result = self.d.retriever.retrieve(
                RetrievalQuery(
                    text=f"{subgoal.goal} {subgoal.expected_state}",
                    phase=RetrievalPhase.PER_SUBGOAL,
                    domains=context.domain_hints,
                    scopes=context.scopes,
                    tenant_id=context.tenant_id,
                    environment=context.environment,
                    data_classification=context.data_classification.value,
                    risk_ceiling=context.risk_level,
                    top_k=self.d.settings.per_subgoal_retrieval_top_k,
                    graph_top_k=self.d.settings.graph_top_k,
                    visibility_policy=visibility,
                    snapshot_id=state.snapshot_id,
                )
            )
            subgoal_results.append(
                (
                    next(
                        item
                        for item in decomposition.subgoals
                        if item.subgoal_id == subgoal.source_subgoal_ids[0]
                    ),
                    result,
                )
            )
        reranked = self.d.reranker.rerank(
            context=context,
            subgoal_results=subgoal_results,
        )
        self.d.trace.event(
            run_id=run_id,
            stage="contract_rerank",
            event_type="completed",
            payload=reranked,
        )
        planning_priors: list[dict[str, object]] = []
        if context.domain_hints:
            prior = self.d.retriever.retrieve(
                RetrievalQuery(
                    text=context.query,
                    phase=RetrievalPhase.PLANNING_PRIOR,
                    domains=context.domain_hints,
                    scopes=context.scopes,
                    tenant_id=context.tenant_id,
                    environment=context.environment,
                    data_classification=context.data_classification.value,
                    risk_ceiling=context.risk_level,
                    top_k=2,
                    graph_top_k=0,
                    visibility_policy=visibility,
                    snapshot_id=state.snapshot_id,
                )
            )
            planning_priors = [item.model_dump(mode="json") for item in prior.candidates]
        budget = BlueprintBudget(
            max_steps=self.d.settings.max_blueprint_steps,
            max_reason_steps=self.d.settings.max_reason_steps,
            max_llm_calls=self.d.settings.max_system2_llm_calls,
            max_tool_calls=self.d.settings.max_system2_tool_calls,
            max_wall_time_seconds=self.d.settings.max_wall_time_seconds,
            max_token_budget=self.d.settings.max_token_budget,
        )
        # Proposer is constructed with the same budget in the application container.
        proposal, usage = self.d.proposer.propose(
            context=context,
            alignment=alignment,
            reranked=reranked,
            registry_view=view,
            planning_priors=planning_priors,
        )
        self._usage(run_id, usage)
        compile_result = self.d.compiler.compile(
            proposal=proposal,
            context=context,
            allowed_asset_refs=set(reranked.allowed_asset_refs),
            expected_registry_view=view,
        )
        if (
            not compile_result.success
            and compile_result.repair_attempts_used == 0
            and any(error.repairable for error in compile_result.errors)
            and self.d.settings.plan_repair_attempts
        ):
            proposal, usage = self.d.proposer.propose(
                context=context,
                alignment=alignment,
                reranked=reranked,
                registry_view=view,
                planning_priors=planning_priors,
                repair_errors=compile_result.errors,
            )
            self._usage(run_id, usage)
            compile_result = self.d.compiler.compile(
                proposal=proposal,
                context=context,
                allowed_asset_refs=set(reranked.allowed_asset_refs),
                expected_registry_view=view,
            )
        self.d.trace.blueprint(
            run_id=run_id,
            proposal=proposal,
            compile_result=compile_result,
            registry_view=view,
            repair_attempts=compile_result.repair_attempts_used,
        )
        routing = self.d.mode_router.route(
            compile_result=compile_result,
            required_subgoal_ids=proposal.required_subgoal_ids,
        )
        langgraph_handoff = None
        system2_handoff = None
        langgraph_receipt = None
        system2_receipt = None
        system2_resolution = None
        if Destination.SYSTEM2 in routing.destinations:
            gap_steps = [
                step
                for step in proposal.steps
                if step.step_type.value in {"REASON", "EXTRACT", "HUMAN"}
            ]
            system2_handoff = System2Handoff(
                run_id=run_id,
                task_id=context.task_id,
                subgoal_ids=list(
                    dict.fromkeys(
                        step.subgoal_id
                        for step in gap_steps
                        if step.subgoal_id in proposal.required_subgoal_ids
                    )
                ),
                reason_step_ids=[step.step_id for step in gap_steps],
                registry_view=view,
                allowed_asset_refs=reranked.allowed_asset_refs,
                max_reason_steps=budget.max_reason_steps,
                max_llm_calls=budget.max_llm_calls,
                max_tool_calls=budget.max_tool_calls,
                side_effect_policy="READ_ONLY",
                execution_contract="BOUNDED_SYSTEM2_V1",
            )
            if (
                Destination.LANGGRAPH_EXECUTION in routing.destinations
                and compile_result.success
            ):
                assert compile_result.compiled_blueprint is not None
                system2_resolution = self.d.system2.resolve(
                    system2_handoff,
                    compile_result.compiled_blueprint.steps,
                    context,
                )
                if system2_resolution is not None:
                    system2_receipt = HandoffReceipt(
                        target="SYSTEM2",
                        status=system2_resolution.status,
                        accepted=True,
                        message=(
                            f"System2 resolved {len(system2_resolution.step_outcomes)} "
                            "bounded gap step(s) for the fixed LangGraph executor."
                        ),
                    )
                else:
                    system2_receipt = self.d.system2.submit(
                        system2_handoff,
                        gap_steps,
                        context,
                    )
            else:
                system2_receipt = self.d.system2.submit(
                    system2_handoff,
                    gap_steps,
                    context,
                )
        if Destination.LANGGRAPH_EXECUTION in routing.destinations and compile_result.success:
            assert compile_result.compiled_blueprint is not None
            reason_steps = [
                step.step_id
                for step in compile_result.compiled_blueprint.steps
                if step.step_type.value == "REASON"
            ]
            langgraph_handoff = LangGraphHandoff(
                run_id=run_id,
                compiled_blueprint_id=compile_result.compiled_blueprint.blueprint_id,
                registry_view=view,
                reason_step_ids=reason_steps,
                failure_policy=fixed_failure_policy(),
                execution_contract="FIXED_META_EXECUTOR_V1",
            )
            langgraph_receipt = self.d.langgraph.submit(
                langgraph_handoff,
                compile_result.compiled_blueprint,
                context,
                system2_resolution,
            )
        guard = self.d.guard.validate(
            routing=routing,
            has_compiled_blueprint=compile_result.success,
            has_langgraph_handoff=langgraph_handoff is not None,
            has_system2_handoff=system2_handoff is not None,
            receipt_statuses=[
                receipt.status
                for receipt in (langgraph_receipt, system2_receipt)
                if receipt is not None
            ],
        )
        self.d.trace.event(
            run_id=run_id,
            stage="route_guard",
            event_type="completed",
            payload={"routing": routing, "guard": guard},
        )
        execution_status = _combined_execution_status(
            langgraph_receipt,
            system2_receipt,
        )
        status = (
            execution_status
            if execution_status in {"SUCCEEDED", "PARTIAL", "FAILED"}
            else "PLANNED"
            if guard.passed
            else "SAFE_STOP"
        )
        final_response, final_usage = compose_final_response(
            run_id=run_id,
            routing=routing,
            execution_status=status,
            proposal=proposal,
            langgraph_receipt=langgraph_receipt,
            system2_receipt=system2_receipt,
            task_context=context,
            model=self.d.model,
        )
        if final_usage is not None:
            self._usage(run_id, final_usage)
        self.d.trace.event(
            run_id=run_id,
            stage="final_response",
            event_type="completed",
            payload=final_response,
        )
        trace_ref = self.d.trace.finish(
            run_id=run_id,
            task_id=context.task_id,
            status=status,
            mode=routing.mode.value,
            destinations=[item.value for item in routing.destinations],
        )
        return _result(
            run_id=run_id,
            context=context,
            clarification=None,
            coarse_subgoals=decomposition.subgoals,
            sad_alignment=alignment,
            proposal=proposal,
            compile_result=compile_result,
            routing=routing,
            langgraph_handoff=langgraph_handoff,
            system2_handoff=system2_handoff,
            langgraph_receipt=langgraph_receipt,
            system2_receipt=system2_receipt,
            guard=guard,
            trace_ref=trace_ref,
            final_response={**final_response, "trace_ref": trace_ref},
        )

    def resume_human(
        self,
        previous: ControlPlatformResult,
        *,
        human_answers: dict[str, dict[str, Any]],
    ) -> ControlPlatformResult:
        """Resume one PARTIAL HUMAN run without replanning or changing its graph."""
        if not human_answers:
            raise ValueError("human_answers cannot be empty")
        if (
            previous.task_context is None
            or previous.proposal is None
            or previous.system2_handoff is None
        ):
            raise ValueError("run has no resumable System2 HUMAN handoff")
        if (
            previous.compile_result is None
            or not previous.compile_result.success
            or previous.compile_result.compiled_blueprint is None
        ):
            raise ValueError("run has no compiled Blueprint to resume")

        run_id = previous.run_id
        self.d.trace.event(
            run_id=run_id,
            stage="human_interaction",
            event_type="human_answer_received",
            payload={
                "step_ids": sorted(human_answers),
                "answers": human_answers,
            },
        )
        previous_execution = (
            previous.langgraph_receipt.execution
            if previous.langgraph_receipt is not None
            and previous.langgraph_receipt.execution is not None
            else previous.system2_receipt.execution
            if previous.system2_receipt is not None
            else None
        )
        resolution = self.d.system2.resume(
            previous.system2_handoff,
            previous.compile_result.compiled_blueprint.steps,
            previous.task_context,
            human_answers=human_answers,
            prior_outputs=(
                previous_execution.outputs
                if previous_execution is not None
                else None
            ),
        )
        system2_receipt = HandoffReceipt(
            target="SYSTEM2",
            status=resolution.status,
            accepted=True,
            message=(
                f"System2 resumed {len(resolution.step_outcomes)} gap step(s) "
                "with typed human input."
            ),
        )
        langgraph_receipt = None
        if (
            previous.langgraph_handoff is not None
            and Destination.LANGGRAPH_EXECUTION in previous.routing.destinations
        ):
            langgraph_receipt = self.d.langgraph.submit(
                previous.langgraph_handoff,
                previous.compile_result.compiled_blueprint,
                previous.task_context,
                resolution,
                resume=True,
                previous_execution=previous_execution,
            )
        else:
            system2_receipt = self.d.system2.submit(
                previous.system2_handoff,
                previous.proposal.steps,
                previous.task_context,
                observed_outputs={
                    **(
                        previous_execution.outputs
                        if previous_execution is not None
                        else {}
                    ),
                    **human_answers,
                },
                resume=True,
            )

        execution_status = _combined_execution_status(
            langgraph_receipt,
            system2_receipt,
        )
        final_response, final_usage = compose_final_response(
            run_id=run_id,
            routing=previous.routing,
            execution_status=execution_status,
            proposal=previous.proposal,
            langgraph_receipt=langgraph_receipt,
            system2_receipt=system2_receipt,
            task_context=previous.task_context,
            model=self.d.model,
        )
        if final_usage is not None:
            self._usage(run_id, final_usage)
        self.d.trace.event(
            run_id=run_id,
            stage="final_response",
            event_type="completed",
            payload=final_response,
        )
        trace_ref = self.d.trace.finish(
            run_id=run_id,
            task_id=previous.task_context.task_id,
            status=execution_status,
            mode=previous.routing.mode.value,
            destinations=[
                item.value for item in previous.routing.destinations
            ],
        )
        return _result(
            run_id=run_id,
            context=previous.task_context,
            clarification=None,
            coarse_subgoals=previous.coarse_subgoals,
            sad_alignment=previous.sad_alignment,
            proposal=previous.proposal,
            compile_result=previous.compile_result,
            routing=previous.routing,
            langgraph_handoff=previous.langgraph_handoff,
            system2_handoff=previous.system2_handoff,
            langgraph_receipt=langgraph_receipt,
            system2_receipt=system2_receipt,
            guard=previous.guard,
            trace_ref=trace_ref,
            final_response={**final_response, "trace_ref": trace_ref},
        )

    def _usage(self, run_id: str, usage: StructuredUsage) -> None:
        self.d.trace.event(run_id=run_id, stage=usage.stage, event_type="llm_usage", payload={
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_duration_ns": usage.total_duration_ns,
            "estimated": usage.estimated,
            "attempts": usage.attempts,
        })


def _result(
    *,
    run_id: str,
    context: Any = None,
    clarification: ClarificationRequest | None = None,
    coarse_subgoals: list[Any] | None = None,
    sad_alignment: Any = None,
    proposal: Any = None,
    compile_result: Any = None,
    routing: RoutingDecision,
    langgraph_handoff: Any = None,
    system2_handoff: Any = None,
    langgraph_receipt: HandoffReceipt | None = None,
    system2_receipt: HandoffReceipt | None = None,
    guard: Any = None,
    trace_ref: str,
    final_response: dict[str, Any] | None = None,
) -> ControlPlatformResult:
    execution = (
        langgraph_receipt.execution
        if langgraph_receipt is not None and langgraph_receipt.execution is not None
        else system2_receipt.execution
        if system2_receipt is not None
        else None
    )
    return ControlPlatformResult(
        run_id=run_id,
        task_context=context,
        clarification=clarification,
        coarse_subgoals=coarse_subgoals or [],
        sad_alignment=sad_alignment,
        proposal=proposal,
        compile_result=compile_result,
        routing=routing,
        langgraph_handoff=langgraph_handoff,
        system2_handoff=system2_handoff,
        langgraph_receipt=langgraph_receipt,
        system2_receipt=system2_receipt,
        guard=guard,
        trace_ref=trace_ref,
        structured_output={
            "run_id": run_id,
            "mode": routing.mode.value,
            "destinations": [item.value for item in routing.destinations],
            "guard_passed": guard.passed if guard else False,
            "execution_status": _combined_execution_status(
                langgraph_receipt,
                system2_receipt,
            ),
            "execution_result": (
                execution.model_dump(mode="json") if execution is not None else None
            ),
            "final_response": final_response,
        },
    )


def _combined_execution_status(
    langgraph_receipt: HandoffReceipt | None,
    system2_receipt: HandoffReceipt | None,
) -> str:
    statuses = [
        receipt.status
        for receipt in (langgraph_receipt, system2_receipt)
        if receipt is not None
    ]
    if not statuses:
        return "NOT_EXECUTED"
    if "FAILED" in statuses:
        return "FAILED"
    if "PARTIAL" in statuses or "NOT_IMPLEMENTED" in statuses:
        return "PARTIAL"
    return "SUCCEEDED"
