#!/usr/bin/env python3
"""Verify relevant retrieval, detail resolution, and real local invocation."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reduce_token_agent.control_plane.capability_retrieval import (
    CapabilityRetrievalService,
)
from reduce_token_agent.domain.capability import RetrievalPhase, RetrievalQuery
from reduce_token_agent.llm.embeddings import OllamaEmbeddingProvider
from reduce_token_agent.registry.retrieval_repository import RetrievalRepository
from reduce_token_agent.registry.service import AssetResolver, RetrievedAssetInvoker


@dataclass(frozen=True, slots=True)
class VerificationCase:
    case_id: str
    query: str
    phase: RetrievalPhase
    domain: str
    expected_ref: str
    scopes: tuple[str, ...] = ()


CASES = (
    VerificationCase(
        case_id="corporate_vendor_status_tool",
        query="查询采购供应商是否完成尽调和准入",
        phase=RetrievalPhase.PER_SUBGOAL,
        domain="corporate_operations",
        expected_ref="tool.corporate_ops.procurement.vendor_status_lookup@1.0.0",
        scopes=("vendor:read",),
    ),
    VerificationCase(
        case_id="corporate_expense_pre_audit",
        query="预审差旅费用报销，检查重复票据和住宿是否超过标准",
        phase=RetrievalPhase.PER_SUBGOAL,
        domain="corporate_operations",
        expected_ref="fsm.corporate_ops.expense.pre_audit@1.0.0",
    ),
    VerificationCase(
        case_id="customer_fraud_escalation",
        query="客户报告疑似盗刷欺诈，需要脱敏并升级安全团队处理",
        phase=RetrievalPhase.PER_SUBGOAL,
        domain="customer_service",
        expected_ref="fsm.customer_service.escalation.triage_route@1.0.0",
    ),
    VerificationCase(
        case_id="financial_balance_reconciliation",
        query="资产负债表不平，检查会计恒等式并定位勾稽差异",
        phase=RetrievalPhase.PER_SUBGOAL,
        domain="financial_report",
        expected_ref=(
            "fsm.financial_report.reconciliation.balance_sheet_route@1.0.0"
        ),
    ),
    VerificationCase(
        case_id="customer_planning_prior",
        query="为客服任务规划从信息受理到结果验证的宏观 DAEF 执行流",
        phase=RetrievalPhase.PLANNING_PRIOR,
        domain="customer_service",
        expected_ref="skeleton.customer_service.intake_resolution_daef@1.0.0",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()

    project_root = arguments.project_root.resolve()
    repository = RetrievalRepository(project_root)
    provider = OllamaEmbeddingProvider(model=arguments.model, host=arguments.host)
    retrieval = CapabilityRetrievalService(repository, provider)
    resolver = AssetResolver(repository)
    invoker = RetrievedAssetInvoker(project_root, repository)
    records: list[dict[str, Any]] = []
    failed = 0

    for case in CASES:
        result = retrieval.retrieve(
            RetrievalQuery(
                text=case.query,
                phase=case.phase,
                domains=[case.domain],
                scopes=list(case.scopes),
                top_k=3,
                graph_top_k=4,
            )
        )
        top_ref = result.candidates[0].asset_ref if result.candidates else None
        detail = resolver.resolve(case.expected_ref)
        invocation = invoker.invoke(case.expected_ref)
        relevant = top_ref == case.expected_ref
        callable_ok = invocation.success
        passed = relevant and callable_ok
        failed += int(not passed)
        record = {
            "case": asdict(case),
            "passed": passed,
            "relevant_top1": relevant,
            "top_ref": top_ref,
            "candidate_refs": [
                {
                    "asset_ref": candidate.asset_ref,
                    "rank": candidate.rank,
                    "source": candidate.provenance.source,
                    "edge_type": candidate.provenance.edge_type,
                }
                for candidate in result.candidates
            ],
            "resolved": {
                "name": detail.name,
                "summary": detail.summary,
                "kind": detail.kind.value,
                "release_status": detail.release_status,
                "validation_status": detail.validation_status,
                "implementation_ref": detail.call.implementation_ref,
                "execution_mode": detail.call.execution_mode,
                "runtime_status": detail.call.runtime_status,
                "policy_version": detail.call.policy_version,
                "tested_at": detail.call.tested_at,
                "input_schema": detail.call.input_schema,
                "output_schema": detail.call.output_schema,
                "sample_payload": detail.call.sample_payload,
                "required_validator_ref": detail.call.required_validator_ref,
            },
            "invocation": invocation.as_json(),
        }
        records.append(record)
        print(
            json.dumps(
                {
                    "event": "retrieval_case_verified",
                    "case_id": case.case_id,
                    "top_ref": top_ref,
                    "expected_ref": case.expected_ref,
                    "retrieval_ok": relevant,
                    "invocation_status": invocation.execution_status,
                    "validator_status": invocation.validation_status_runtime,
                    "passed": passed,
                },
                ensure_ascii=False,
            )
        )

    timestamp = datetime.now(UTC).isoformat()
    report_path = arguments.report or (
        project_root / "data/reports/retrieval/RETRIEVAL_VERIFICATION.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "generated_at": timestamp,
                "summary": {
                    "total": len(records),
                    "passed": len(records) - failed,
                    "failed": failed,
                    "embedding_model": arguments.model,
                },
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event": "retrieval_verification_finished",
                "passed": len(records) - failed,
                "failed": failed,
                "report": str(report_path.relative_to(project_root)),
            },
            ensure_ascii=False,
        )
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
