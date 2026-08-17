"""Deterministic Blueprint compiler implementing the hard planning gates."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from reduce_token_agent.domain.blueprint import (
    BlueprintProposal,
    CompiledBlueprint,
    CompileError,
    CompileErrorCode,
    CompileResult,
    RegistryViewRef,
    StepType,
)
from reduce_token_agent.domain.capability import AssetDetails, VisibilityPolicy
from reduce_token_agent.domain.task import TaskContext
from reduce_token_agent.registry.models import AssetKind, RiskLevel, SideEffect
from reduce_token_agent.registry.service import AssetResolver

_STEP_KIND = {
    StepType.FSM: AssetKind.FSM_SHARD,
    StepType.TOOL: AssetKind.PRIMITIVE_TOOL,
    StepType.ADAPTER: AssetKind.ADAPTER,
    StepType.VALIDATOR: AssetKind.VALIDATOR,
}
_PRIMARY_STEPS = {StepType.FSM, StepType.TOOL, StepType.EXTRACT, StepType.REASON, StepType.HUMAN}
_POINTER = re.compile(r"^/steps/(?P<step_id>step_[a-z0-9_]{2,60})(?:/.*)?$")


class BlueprintCompiler:
    """Compile an LLM proposal using deterministic, typed gates only."""

    def __init__(
        self,
        resolver: AssetResolver,
        *,
        supported_asset_schema_version: str,
        allow_validated_draft_view: bool,
    ) -> None:
        self.resolver = resolver
        self.supported_asset_schema_version = supported_asset_schema_version
        self.allow_validated_draft_view = allow_validated_draft_view

    def compile(
        self,
        *,
        proposal: BlueprintProposal,
        context: TaskContext,
        allowed_asset_refs: set[str],
        expected_registry_view: RegistryViewRef,
    ) -> CompileResult:
        """Run all hard gates and return error codes rather than model prose."""
        errors: list[CompileError] = []
        self._gate_registry_view(proposal, expected_registry_view, errors)
        self._gate_graph(proposal, errors)
        self._gate_budget(proposal, errors)
        details_by_ref = self._gate_assets(
            proposal,
            context,
            allowed_asset_refs,
            errors,
        )
        self._gate_bindings(proposal, errors)
        self._gate_subgoal_coverage(proposal, errors)
        self._gate_validators(proposal, details_by_ref, errors)
        self._gate_side_effects(proposal, context, details_by_ref, errors)
        if errors:
            return CompileResult(
                success=False,
                errors=_unique_errors(errors),
                repair_attempts_used=proposal.repair_attempt,
            )
        canonical = json.dumps(
            proposal.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return CompileResult(
            success=True,
            compiled_blueprint=CompiledBlueprint(
                blueprint_id=proposal.blueprint_id,
                task_id=proposal.task_id,
                registry_view=proposal.registry_view,
                steps=proposal.steps,
                budget=proposal.budget,
                proposal_digest=digest,
                compiled_at=datetime.now(UTC),
            ),
            repair_attempts_used=proposal.repair_attempt,
        )

    def _gate_registry_view(
        self,
        proposal: BlueprintProposal,
        expected: RegistryViewRef,
        errors: list[CompileError],
    ) -> None:
        if proposal.registry_view != expected:
            errors.append(_error(CompileErrorCode.SNAPSHOT_MISMATCH, "registry_view", False))
        if (
            proposal.registry_view.visibility_policy is VisibilityPolicy.VALIDATED_DRAFT
            and not self.allow_validated_draft_view
        ):
            errors.append(_error(CompileErrorCode.POLICY_DENIED, "draft_visibility", False))

    def _gate_graph(
        self,
        proposal: BlueprintProposal,
        errors: list[CompileError],
    ) -> None:
        ids = [step.step_id for step in proposal.steps]
        known = set(ids)
        if len(ids) != len(known):
            errors.append(_error(CompileErrorCode.DEPENDENCY_INVALID, "step_unique", True))
            return
        for step in proposal.steps:
            if step.step_id in step.depends_on or not set(step.depends_on).issubset(known):
                errors.append(
                    _error(
                        CompileErrorCode.DEPENDENCY_INVALID,
                        "dependency_exists",
                        True,
                        step_id=step.step_id,
                    )
                )
        if _has_cycle({step.step_id: step.depends_on for step in proposal.steps}):
            errors.append(_error(CompileErrorCode.DAG_CYCLE, "dag_acyclic", True))

    def _gate_budget(
        self,
        proposal: BlueprintProposal,
        errors: list[CompileError],
    ) -> None:
        reason_steps = [step for step in proposal.steps if step.step_type is StepType.REASON]
        tool_steps = [step for step in proposal.steps if step.step_type is StepType.TOOL]
        exceeded = (
            len(proposal.steps) > proposal.budget.max_steps
            or len(reason_steps) > proposal.budget.max_reason_steps
            or len(tool_steps) > proposal.budget.max_tool_calls
            or any(
                (step.max_iterations or 0) > proposal.budget.max_llm_calls
                for step in reason_steps
            )
        )
        if exceeded:
            errors.append(_error(CompileErrorCode.BUDGET_EXCEEDED, "budget", True))

    def _gate_assets(
        self,
        proposal: BlueprintProposal,
        context: TaskContext,
        allowed: set[str],
        errors: list[CompileError],
    ) -> dict[str, AssetDetails]:
        details_by_ref: dict[str, AssetDetails] = {}
        for step in proposal.steps:
            if step.asset_ref is None:
                continue
            if step.asset_ref not in allowed:
                errors.append(
                    _error(
                        CompileErrorCode.ASSET_NOT_AVAILABLE,
                        "candidate_allowlist",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
                continue
            try:
                details = self.resolver.resolve(step.asset_ref)
            except (LookupError, FileNotFoundError):
                errors.append(
                    _error(
                        CompileErrorCode.ASSET_NOT_AVAILABLE,
                        "asset_resolve",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
                continue
            details_by_ref[step.asset_ref] = details
            if _STEP_KIND.get(step.step_type) is not details.kind:
                errors.append(
                    _error(
                        CompileErrorCode.TYPE_MISMATCH,
                        "step_kind",
                        True,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            contract = details.contract
            if details.artifact_schema_version != self.supported_asset_schema_version:
                errors.append(
                    _error(
                        CompileErrorCode.SCHEMA_VERSION_UNSUPPORTED,
                        "asset_schema",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            if (
                details.validation_status != "PASS"
                or details.call.tested_at is None
                or details.call.runtime_status not in {"READY", "PLANNING_ONLY"}
            ):
                errors.append(
                    _error(
                        CompileErrorCode.ASSET_NOT_AVAILABLE,
                        "runtime_readiness",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            if contract["tenant_scope"] != context.tenant_id:
                errors.append(
                    _error(
                        CompileErrorCode.POLICY_DENIED,
                        "tenant",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            required_scopes = set(contract["required_scopes"])
            if not required_scopes.issubset(context.scopes):
                errors.append(
                    _error(
                        CompileErrorCode.SCOPE_DENIED,
                        "scope",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            if set(step.required_scopes) != required_scopes:
                errors.append(
                    _error(
                        CompileErrorCode.SCOPE_DENIED,
                        "declared_scope_exact",
                        True,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            if step.side_effect.value != contract["side_effect"]:
                errors.append(
                    _error(
                        CompileErrorCode.SIDE_EFFECT_UNKNOWN,
                        "side_effect_exact",
                        True,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
            if details.kind is AssetKind.WORKFLOW_SKELETON:
                errors.append(
                    _error(
                        CompileErrorCode.TOOL_NOT_ALLOWED,
                        "skeleton_not_executable",
                        False,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )
        return details_by_ref

    def _gate_bindings(
        self,
        proposal: BlueprintProposal,
        errors: list[CompileError],
    ) -> None:
        by_id = {step.step_id: step for step in proposal.steps}
        for step in proposal.steps:
            for pointer in step.input_bindings.values():
                match = _POINTER.match(pointer)
                if match is None:
                    continue
                source = match.group("step_id")
                if source not in by_id or source not in step.depends_on:
                    errors.append(
                        _error(
                            CompileErrorCode.INPUT_BINDING_INVALID,
                            "binding_dependency",
                            True,
                            step_id=step.step_id,
                        )
                    )

    def _gate_subgoal_coverage(
        self,
        proposal: BlueprintProposal,
        errors: list[CompileError],
    ) -> None:
        covered = {
            step.subgoal_id
            for step in proposal.steps
            if step.step_type in _PRIMARY_STEPS
        }
        for subgoal_id in proposal.required_subgoal_ids:
            if subgoal_id not in covered:
                errors.append(
                    _error(
                        CompileErrorCode.SUBGOAL_UNCOVERED,
                        "required_subgoal",
                        True,
                    )
                )

    def _gate_validators(
        self,
        proposal: BlueprintProposal,
        details_by_ref: dict[str, AssetDetails],
        errors: list[CompileError],
    ) -> None:
        selected = {step.asset_ref for step in proposal.steps if step.asset_ref}
        for step in proposal.steps:
            if step.asset_ref is None:
                continue
            details = details_by_ref.get(step.asset_ref)
            if details is None:
                continue
            required = details.call.required_validator_ref
            if required and required not in selected:
                errors.append(
                    _error(
                        CompileErrorCode.VALIDATOR_MISSING,
                        "required_validator",
                        True,
                        step_id=step.step_id,
                        asset_ref=required,
                    )
                )

    def _gate_side_effects(
        self,
        proposal: BlueprintProposal,
        context: TaskContext,
        details_by_ref: dict[str, AssetDetails],
        errors: list[CompileError],
    ) -> None:
        for step in proposal.steps:
            if step.asset_ref is None:
                continue
            details = details_by_ref.get(step.asset_ref)
            if details is None:
                continue
            contract = details.contract
            if step.side_effect is SideEffect.LOCAL_WRITE:
                if not step.idempotency_key:
                    errors.append(
                        _error(
                            CompileErrorCode.SIDE_EFFECT_UNKNOWN,
                            "idempotency",
                            True,
                            step_id=step.step_id,
                            asset_ref=step.asset_ref,
                        )
                    )
                if contract["compensation"] and not step.compensation_ref:
                    errors.append(
                        _error(
                            CompileErrorCode.SIDE_EFFECT_UNKNOWN,
                            "compensation",
                            True,
                            step_id=step.step_id,
                            asset_ref=step.asset_ref,
                        )
                    )
            high_risk_action = (
                step.side_effect is SideEffect.HUMAN_HANDOFF
                or (
                    context.risk_level is RiskLevel.HIGH
                    and step.side_effect is SideEffect.LOCAL_WRITE
                )
            )
            if high_risk_action and not step.human_gate:
                errors.append(
                    _error(
                        CompileErrorCode.RISK_GATE_REQUIRED,
                        "human_gate",
                        True,
                        step_id=step.step_id,
                        asset_ref=step.asset_ref,
                    )
                )


def _error(
    code: CompileErrorCode,
    gate: str,
    repairable: bool,
    *,
    step_id: str | None = None,
    asset_ref: str | None = None,
) -> CompileError:
    return CompileError(
        code=code,
        gate=gate,
        message=f"{gate} gate rejected the proposal",
        step_id=step_id,
        asset_ref=asset_ref,
        repairable=repairable,
    )


def _has_cycle(dependencies: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(dependency) for dependency in dependencies.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in dependencies)


def _unique_errors(errors: list[CompileError]) -> list[CompileError]:
    unique: dict[tuple[object, ...], CompileError] = {}
    for error in errors:
        key = (error.code, error.gate, error.step_id, error.asset_ref)
        unique.setdefault(key, error)
    return list(unique.values())
