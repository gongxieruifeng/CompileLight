"""Polished Gradio business demo mounted into the local FastAPI process."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, cast

import gradio as gr

from reduce_token_agent.application.view_models import TaskRunView
from reduce_token_agent.ui.handlers import LocalUiHandlers
from reduce_token_agent.ui.presenters import (
    render_audit_summary,
    render_step_evidence,
    render_task_flow,
)

UI_CSS = """
:root { --rta-ink: #10231f; --rta-muted: #62706b; --rta-green: #0f766e; }
.gradio-container { background: #f4f7f5 !important; }
.rta-hero {
  border-radius: 24px; padding: 26px 30px; margin: 4px 0 18px;
  color: #f8fffc; background:
    radial-gradient(circle at 82% 12%, rgba(74,222,128,.22), transparent 28%),
    linear-gradient(125deg, #0b2f29 0%, #145a4c 58%, #187c68 100%);
  box-shadow: 0 18px 45px rgba(13, 74, 62, .18);
}
.rta-eyebrow { color: #9de7cf; font-size: 12px; letter-spacing: .16em; font-weight: 750; }
.rta-hero h1 { margin: 8px 0 6px; font-size: 30px; line-height: 1.15;
  color: #f8fffc !important; }
.rta-hero p { margin: 0; color: #d5efe6; max-width: 800px; }
.rta-card { background: #fff !important; border: 1px solid #dfe9e4 !important;
  border-radius: 18px !important; padding: 8px !important;
  box-shadow: 0 8px 24px rgba(24,52,45,.05); }
.rta-section h3 { margin: 2px 0 4px; color: var(--rta-ink); }
.rta-section p { color: var(--rta-muted); font-size: 13px; }
.rta-status-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.rta-stat { background:#fff; border:1px solid #dce9e3; border-radius:14px; padding:12px 14px; }
.rta-stat small { color:#70807a; display:block; margin-bottom:4px; }
.rta-stat strong { color:#123c33; font-size:14px; overflow-wrap:anywhere; }
.rta-answer { background: linear-gradient(135deg,#ffffff,#f3fbf7); border-left:4px solid #10b981;
  border-radius:14px; padding:16px 18px; min-height:92px; }
.rta-demo-note { background:#edf8f3; border:1px solid #c9e9dc;
  border-radius:14px; padding:12px 15px; }
.rta-demo-note strong { color:#0c5f50; }
.rta-demo-choice { min-height:112px; border:1px solid #d7e7df; border-radius:16px;
  padding:15px 17px; background:linear-gradient(145deg,#fff,#f5faf7); }
.rta-demo-choice.dm { border-color:#d9d5f3;
  background:linear-gradient(145deg,#fff,#f7f5ff); }
.rta-demo-choice .rta-demo-badge { display:inline-flex; padding:4px 8px; border-radius:999px;
  color:#0d725e; background:#e6f6ef; font-size:9px; font-weight:850; letter-spacing:.08em; }
.rta-demo-choice.dm .rta-demo-badge { color:#6540a5; background:#eee9ff; }
.rta-demo-choice h3 { margin:8px 0 4px; color:#173c33; font-size:16px; }
.rta-demo-choice p { margin:0; color:#6b7974; font-size:11px; line-height:1.55; }
.rta-demo-guide { margin:12px 0 16px; border-radius:14px; padding:13px 16px;
  border:1px solid #cbe8db; background:#eff9f4; color:#49645b; font-size:11px; }
.rta-demo-guide.dm { border-color:#dcd5f3; background:#f6f3ff; }
.rta-demo-guide strong { color:#164d40; }.rta-demo-guide.dm strong { color:#5e4294; }
.rta-demo-guide code { color:#3b5e54; background:rgba(255,255,255,.72); border-radius:6px;
  padding:2px 5px; }
.rta-demo-guide .rta-guide-row { display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:7px; }
.rta-demo-guide .rta-guide-row span { display:inline-flex; align-items:center; gap:5px; }
.rta-demo-guide .rta-runtime-ready { color:#08745e; font-weight:800; }
.rta-demo-guide .rta-runtime-off { color:#b45309; font-weight:800; }
.rta-evidence-title { margin:28px 2px 12px; }
.rta-evidence-title h2 { color:#10231f; font-size:23px; margin:0 0 5px; }
.rta-evidence-title p { color:#687771; margin:0; }
.rta-flow-board,.rta-audit-board { background:#fff; border:1px solid #dbe8e2;
  border-radius:20px; padding:22px; box-shadow:0 10px 30px rgba(25,58,49,.055); }
.rta-flow-head { display:flex; justify-content:space-between; gap:18px; align-items:flex-start;
  margin-bottom:20px; }
.rta-flow-head h3,.rta-audit-section h3 { color:#10231f; margin:3px 0 4px; font-size:20px; }
.rta-flow-head p { color:#687771; margin:0; font-size:13px; }
.rta-kicker { color:#0f8a71; font-size:10px; letter-spacing:.16em; font-weight:800; }
.rta-flow-outcome { min-width:155px; padding:10px 14px; border-radius:13px;
  background:#eef9f4; border:1px solid #ccebdd; text-align:right; }
.rta-flow-outcome span { display:block; color:#0d7a65; font-size:11px; font-weight:800; }
.rta-flow-outcome strong { color:#15483d; font-size:13px; }
.rta-kind,.rta-run-status { display:inline-flex; align-items:center; border-radius:999px;
  padding:4px 8px; font-size:10px; font-weight:800; line-height:1; }
.rta-kind { color:#166352; background:#e6f7f0; }
.rta-kind.kind-tool { color:#1d5e9e; background:#eaf3ff; }
.rta-kind.kind-validator { color:#6540a5; background:#f0eaff; }
.rta-kind.kind-reason { color:#9a6000; background:#fff3d8; }
.rta-kind.kind-human { color:#a93434; background:#ffe9e9; }
.rta-journey-start,.rta-journey-finish { border-radius:15px; padding:14px 18px;
  display:grid; grid-template-columns:auto 1fr; column-gap:14px; align-items:center; }
.rta-journey-start { background:#102f29; color:#fff; }
.rta-journey-start span,.rta-journey-finish span { grid-row:1/3; font-size:10px;
  letter-spacing:.11em; font-weight:850; text-transform:uppercase; }
.rta-journey-start strong { color:#f3fff9; font-size:14px; }
.rta-journey-start small { color:#accdc2; font-size:10px; margin-top:2px; }
.rta-journey { position:relative; padding:18px 0; }
.rta-journey::before { content:""; position:absolute; left:25px; top:0; bottom:0;
  border-left:2px solid #c7ddd5; }
.rta-journey-step { position:relative; margin-left:54px; background:#fff;
  border:1px solid #dbe8e2; border-left:4px solid #93b7aa; border-radius:17px;
  padding:17px 19px; box-shadow:0 8px 24px rgba(22,58,48,.055); }
.rta-journey-step::before { content:""; position:absolute; left:-42px; top:28px;
  width:14px; height:14px; border-radius:50%; background:#fff; border:4px solid #10b981;
  box-shadow:0 0 0 5px #f4f7f5; }
.rta-journey-step.kind-border-tool { border-left-color:#3b82f6; }
.rta-journey-step.kind-border-fsm,
.rta-journey-step.kind-border-dm_direct { border-left-color:#10b981; }
.rta-journey-step.kind-border-validator { border-left-color:#8b5cf6; }
.rta-journey-step.kind-border-reason { border-left-color:#f59e0b; }
.rta-journey-step.kind-border-human { border-left-color:#ef4444; }
.rta-journey-step.node-failed { background:#fff8f8; border-color:#efb9b9; }
.rta-journey-step.node-waiting { background:#fffbf1; border-color:#ead095; }
.rta-journey-step-head { display:flex; align-items:flex-start; gap:13px; }
.rta-step-list { display:grid; gap:14px; }
.rta-blueprint-board { background:#fff; border:1px solid #dbe8e2; border-radius:20px;
  padding:22px; box-shadow:0 10px 30px rgba(25,58,49,.055); }
.rta-blueprint-intro { margin-bottom:16px; }
.rta-blueprint-intro h3 { color:#10231f; margin:3px 0 4px; font-size:20px; }
.rta-blueprint-intro p { color:#687771; margin:0; font-size:12px; }
.rta-blueprint-card { background:#fff; border:1px solid #dce8e3; border-radius:18px;
  padding:18px 20px; box-shadow:0 7px 22px rgba(25,58,49,.045); }
.rta-blueprint-card header { display:flex; align-items:flex-start; gap:13px; }
.rta-step-index { width:36px; height:36px; border-radius:11px; background:#133e35;
  color:#c9f8e7; display:grid; flex:0 0 auto; place-items:center;
  font:800 11px ui-monospace,monospace; }
.rta-step-title { flex:1; min-width:0; }
.rta-step-title h4 { margin:7px 0 5px; color:#173a32; font-size:16px; }
.rta-step-title code { display:block; color:#63766f; font-size:11px;
  overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.rta-run-status { margin-left:6px; }.status-success { color:#0c745f; background:#e5f8ef; }
.status-ready { color:#526c63; background:#eef3f1; }
.status-waiting { color:#9a6000; background:#fff3d8; }
.status-failed { color:#a93434; background:#ffe9e9; }
.rta-validation { color:#71817b; font-size:11px; text-align:right; }
.rta-validation strong { display:block; color:#0f7c67; font-size:13px; margin-top:3px; }
.rta-step-id { max-width:210px; text-align:right; }
.rta-step-id span { display:block; color:#8a9994; font-size:9px; letter-spacing:.12em; }
.rta-step-id strong { color:#506860; font:700 10px ui-monospace,monospace;
  overflow-wrap:anywhere; }
.rta-data-lane { display:grid; grid-template-columns:minmax(0,1fr) 34px minmax(170px,.7fr)
  34px minmax(0,1fr); align-items:stretch; gap:8px; margin-top:16px; }
.rta-lane-panel { min-width:0; background:#f7faf8; border:1px solid #e4ede9;
  border-radius:13px; padding:13px; }
.rta-lane-panel.action { display:flex; flex-direction:column; align-items:center;
  justify-content:center; text-align:center; background:linear-gradient(145deg,#eef8f4,#fbfffd); }
.rta-lane-panel.output { background:#f7f5ff; border-color:#e6def8; }
.rta-lane-title { display:flex; align-items:center; gap:7px; color:#315c50;
  margin-bottom:10px; font-size:11px; }
.rta-lane-title span { width:22px; height:22px; display:grid; place-items:center;
  border-radius:7px; background:#e4f2ed; color:#147460; font:800 9px ui-monospace,monospace; }
.rta-source-chip { display:inline-flex; color:#155f51; background:#e5f5ef;
  border-radius:999px; padding:5px 8px; font-size:9px; font-weight:750; margin-bottom:10px; }
.rta-dependency { margin:10px 0 0; padding-top:8px; border-top:1px dashed #dbe5e1;
  color:#75847f; font-size:9px; }
.rta-lane-arrow { display:grid; place-items:center; color:#6f998c; position:relative; }
.rta-lane-arrow::before { content:""; position:absolute; left:0; right:0; top:50%;
  border-top:1px solid #b9d2c9; }
.rta-lane-arrow span { z-index:1; width:24px; height:24px; display:grid; place-items:center;
  border-radius:50%; border:1px solid #b9d2c9; background:#fff; font-size:11px; }
.rta-capability-icon { width:42px; height:42px; display:grid; place-items:center;
  border-radius:13px; background:#0f766e; color:#fff; font-weight:850; margin:4px 0 8px; }
.rta-capability-name { color:#173f35; font-size:13px; }
.rta-lane-panel.action code { max-width:100%; color:#416259; background:#e7f0ed;
  padding:5px 7px; border-radius:7px; margin:6px 0; font-size:9px;
  overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.rta-lane-panel.action small { color:#7a8984; font-size:9px; }
.rta-decision { color:#465f57; font-size:10px; line-height:1.45; margin:9px 0; }
.rta-validator-box { display:flex; justify-content:space-between; align-items:center;
  margin-top:10px; padding:8px 10px; border-radius:9px; background:#e8f7f0;
  color:#15705d; font-size:10px; }
.rta-validator-box.validator-fail,.rta-validator-box.validator-failed {
  background:#feecec; color:#a83737; }
.rta-validator-box.validator-not_run { background:#eef2f0; color:#66756f; }
.rta-handoff { position:relative; min-height:62px; margin-left:54px; display:flex;
  align-items:center; gap:12px; color:#587069; }
.rta-handoff i { width:24px; height:24px; margin-left:-40px; flex:0 0 auto;
  border-radius:50%; background:#fff; border:1px solid #a9c8bd; position:relative; }
.rta-handoff i::after { content:"↓"; position:absolute; inset:0; display:grid; place-items:center;
  color:#187a66; font-style:normal; font-weight:900; font-size:11px; }
.rta-handoff div { display:flex; gap:8px; align-items:center; padding:7px 11px;
  border-radius:9px; background:#eef7f3; font-size:10px; }
.rta-handoff.independent div { background:#f5f7f6; border:1px dashed #cfdcd7; }
.rta-handoff.ordered div { background:#fff7e8; border:1px solid #eed9ae; }
.rta-handoff strong { color:#28564a; }.rta-handoff span { color:#75847f; }
.rta-journey-finish { background:linear-gradient(135deg,#ddf7e9,#f6fffb);
  border:1px solid #bfe5d3; color:#0f6d59; }
.rta-journey-finish strong { color:#164b3f; font-size:15px; }
.rta-journey-finish p { margin:3px 0 0; color:#4c675f; font-size:11px; line-height:1.45; }
.rta-journey-finish.status-failed { background:#fff1f1; border-color:#efc2c2; }
.rta-blueprint-meta { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px;
  margin-top:14px; }
.rta-blueprint-meta>div { background:#f7faf8; border:1px solid #e5ede9;
  border-radius:10px; padding:10px; }
.rta-blueprint-meta span { display:block; color:#7b8b85; font-size:9px; margin-bottom:4px; }
.rta-blueprint-meta strong { color:#36564d; font-size:10px; overflow-wrap:anywhere; }
.rta-facts { display:grid; gap:7px; }.rta-fact-row { display:flex; justify-content:space-between;
  gap:12px; font-size:11px; border-bottom:1px dashed #e0e9e5; padding-bottom:6px; }
.rta-fact-row span { color:#73827d; }.rta-fact-row strong { color:#29483f; text-align:right; }
.rta-empty-copy { color:#8a9994; font-size:11px; margin:0; }
.rta-tech-detail { margin-top:12px; color:#65746f; font-size:11px; }
.rta-tech-detail summary { cursor:pointer; color:#16735f; font-weight:700; }
.rta-tech-detail pre { max-height:280px; overflow:auto; background:#102a24; color:#d7f5e8;
  border-radius:12px; padding:14px; white-space:pre-wrap; }
.rta-audit-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.rta-audit-metric { background:#f6faf8; border:1px solid #e2ece7;
  border-radius:13px; padding:12px; }
.rta-audit-metric span { color:#72817c; font-size:10px; display:block; margin-bottom:5px; }
.rta-audit-metric strong { color:#1a4439; font-size:13px; display:block;
  overflow:hidden; white-space:nowrap; text-overflow:ellipsis; }
.rta-audit-section { margin-top:18px; padding-top:17px; border-top:1px solid #e4ece8; }
.rta-stage-rail { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.rta-stage-chip { color:#176a58; background:#eaf7f1; border:1px solid #d0eade;
  border-radius:999px; padding:6px 10px; font-size:10px; font-weight:700; }
.rta-stage-chip.muted { color:#73817c; background:#f2f5f4; }
.rta-governance-strip { margin-top:18px; display:flex; flex-wrap:wrap; gap:18px;
  background:#133e35; border-radius:13px; padding:12px 14px; color:#b9d6cc; font-size:10px; }
.rta-governance-strip strong { color:#f0fff9; margin-left:4px; }
.rta-empty-panel { background:#fff; border:1px dashed #cadbd4; border-radius:18px;
  padding:35px; text-align:center; color:#71827b; }
.rta-empty-panel>span { font-size:25px; color:#18a37f; }.rta-empty-panel h3 { color:#244b40; }
footer { display:none !important; }
@media (max-width: 800px) {
  .rta-status-grid,.rta-audit-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .rta-flow-head { flex-direction:column; }.rta-flow-outcome { text-align:left; }
  .rta-data-lane { grid-template-columns:1fr; }
  .rta-lane-arrow { height:24px; }.rta-lane-arrow::before { left:50%; right:auto; top:0;
    bottom:0; border-top:0; border-left:1px solid #b9d2c9; }
  .rta-lane-arrow span { transform:rotate(90deg); }
  .rta-blueprint-meta { grid-template-columns:1fr; }
  .rta-demo-choice { min-height:auto; }
}
"""


def ui_theme() -> gr.Theme:
    return gr.themes.Soft(
        primary_hue="emerald",
        secondary_hue="teal",
        neutral_hue="slate",
        radius_size="lg",
    )


def build_ui(handlers: LocalUiHandlers) -> gr.Blocks:
    with gr.Blocks(title="ReduceTokenAgent 业务验证台", fill_width=True) as demo:
        run_state = gr.State("")
        gr.HTML(
            """
            <div class="rta-hero">
              <div class="rta-eyebrow">DETERMINISTIC AGENT · LOCAL POC</div>
              <h1 style="color:#f8fffc !important">ReduceTokenAgent 业务验证台</h1>
              <p>观察一个真实业务目标如何完成能力召回、Blueprint 编译、固定执行与独立验证。</p>
            </div>
            """
        )

        with gr.Tab("业务演示"):
            with gr.Row(equal_height=True):
                with gr.Column(scale=1):
                    gr.HTML(
                        """
                        <div class="rta-demo-choice">
                          <span class="rta-demo-badge">LOCAL REUSE · DETERMINISTIC</span>
                          <h3>上海差旅费用报销预审</h3>
                          <p>复用本地 Tool、FSM 和 Validator，识别重复票据与住宿超标，
                          不执行付款或修改财务状态。</p>
                        </div>
                        """
                    )
                    load_demo = gr.Button("载入费用预审演示", variant="secondary")
                with gr.Column(scale=1):
                    gr.HTML(
                        """
                        <div class="rta-demo-choice dm">
                          <span class="rta-demo-badge">SIT · DM DIRECT · ROBOT 353</span>
                          <h3>贷款被拒原因咨询</h3>
                          <p>唯一命中已激活机器人能力后跳过 Blueprint 和本地 LLM，
                          由 Robot 353 追问并在同一对话中继续处理。</p>
                        </div>
                        """
                    )
                    load_dm_demo = gr.Button("载入 Robot 353 DM 演示", variant="secondary")
            demo_guide = gr.HTML(_demo_guide("expense"))
            with gr.Row(equal_height=False):
                with gr.Column(scale=5, elem_classes=["rta-card"]):
                    gr.Markdown("### 1. 业务请求\n输入目标，并提供确定性执行所需的权威业务事实。")
                    query = gr.Textbox(
                        label="业务目标",
                        lines=5,
                        placeholder="描述需要完成的业务结果，不要拆成HTTP或函数动作。",
                    )
                    business_facts = gr.Code(
                        label="权威业务事实（JSON）",
                        language="json",
                        lines=16,
                        value="{}",
                    )
                    acceptance = gr.Textbox(
                        label="验收标准（每行一条）",
                        lines=3,
                        placeholder="结果必须满足的可验证条件",
                    )
                    with gr.Accordion("调用身份与治理上下文", open=False):
                        with gr.Row():
                            tenant = gr.Textbox(label="Tenant", value="local")
                            principal = gr.Textbox(label="Principal", value="principal-local")
                        scopes = gr.Textbox(label="Scopes（逗号分隔）", value="")
                        domain_hint = gr.Dropdown(
                            [
                                "",
                                "corporate_operations",
                                "customer_service",
                                "financial_report",
                                "internal_communication",
                                "loan_contract",
                                "risk_compliance",
                            ],
                            value="",
                            label="Authoritative Domain Hint",
                        )
                        with gr.Row():
                            environment = gr.Dropdown(
                                ["local", "sit", "staging", "production"],
                                value="local",
                                label="Environment",
                            )
                            classification = gr.Dropdown(
                                [
                                    "",
                                    "PUBLIC",
                                    "INTERNAL",
                                    "CONFIDENTIAL",
                                    "RESTRICTED",
                                    "SYNTHETIC",
                                ],
                                value="SYNTHETIC",
                                label="Data Classification",
                            )
                            risk = gr.Dropdown(
                                ["", "LOW", "MEDIUM", "HIGH"],
                                value="MEDIUM",
                                label="Risk",
                            )
                    execute_button = gr.Button("开始路由并执行", variant="primary", size="lg")

                with gr.Column(scale=6, elem_classes=["rta-card"]):
                    gr.Markdown("### 2. 交付结果\n先看业务结论，再按需展开技术证据。")
                    interaction = gr.HTML(_empty_status())
                    final_answer = gr.Markdown(
                        "尚未执行。载入推荐案例后点击“开始路由并执行”。",
                        elem_classes=["rta-answer"],
                    )
                    chat = gr.Chatbot(label="业务对话", height=260)
                    with gr.Group():
                        dm_input = gr.Textbox(
                            label="机器人要求补充信息时，在这里输入真实用户回复",
                            placeholder="仅在交互状态为 DM_USER_INPUT 时使用。",
                        )
                        dm_resume = gr.Button("提交回复并继续原会话")

            gr.HTML(
                '<div class="rta-evidence-title"><h2>3. 任务流转与执行证据</h2>'
                "<p>先按真实运行顺序查看每一步的数据流，再按需核对 Blueprint "
                "依赖与审计信息。</p></div>"
            )
            with gr.Tabs():
                with gr.Tab("实际执行过程"):
                    flow_html = gr.HTML(render_task_flow(_empty_view()))
                with gr.Tab("Blueprint 依赖"):
                    evidence_html = gr.HTML(render_step_evidence(_empty_view()))
                with gr.Tab("运行审计"):
                    audit_html = gr.HTML(render_audit_summary(_empty_view()))
                    trace_ref = gr.Textbox(label="Trace Ref", interactive=False)

        with gr.Tab("运行检查"):
            gr.Markdown(
                "### 历史 Trace 审查\n"
                "可读取当前进程或 SQLite 中已持久化的历史运行，不重新执行任务。"
            )
            with gr.Row():
                inspect_run = gr.Textbox(
                    label="Run ID / Trace ID / Trace Ref",
                    placeholder="例如 run_458f364b6a8a0359 或 trace_run_458f364b6a8a0359",
                    scale=5,
                )
                inspect_button = gr.Button("读取历史运行", variant="primary", scale=1)
            inspect_status = gr.HTML(_empty_status())
            inspect_answer = gr.Markdown(elem_classes=["rta-answer"])
            inspect_flow = gr.HTML(render_task_flow(_empty_view()))
            with gr.Tabs():
                with gr.Tab("Blueprint 依赖"):
                    inspect_evidence = gr.HTML(render_step_evidence(_empty_view()))
                with gr.Tab("运行审计"):
                    inspect_audit = gr.HTML(render_audit_summary(_empty_view()))
                    inspect_trace_ref = gr.Textbox(label="Trace Ref", interactive=False)

        with gr.Tab("组件验证"):
            gr.Markdown(
                "### 受控组件检查\n"
                "只读取Application结果或Trace投影，不允许绕过Gateway执行任意代码。"
            )
            component = gr.Dropdown(
                [
                    "Application Result Contract",
                    "Runtime Trace Projection",
                    "DM Conversation Contract",
                ],
                value="Application Result Contract",
                label="受控组件",
            )
            component_run = gr.Textbox(label="Run ID")
            component_button = gr.Button("运行组件检查")
            component_output = gr.JSON(label="结构化结果")

        with gr.Tab("人工审批"):
            gr.Markdown(
                "### HUMAN Review 独立入口\n"
                "只处理Blueprint中的HUMAN节点，不会推进机器人Question节点。"
            )
            human_run = gr.Textbox(label="Run ID")
            human_answers = gr.Code(
                label="按 Step ID 提交 typed JSON",
                language="json",
                value='{"step_human": {"confirmed": true, "decision": "同意"}}',
            )
            human_button = gr.Button("提交人工审批", variant="primary")
            human_output = gr.JSON(label="恢复结果")

        load_demo.click(
            fn=lambda: (*_load_demo_case(), _demo_guide("expense")),
            outputs=[
                query,
                business_facts,
                acceptance,
                tenant,
                principal,
                scopes,
                domain_hint,
                environment,
                classification,
                risk,
                demo_guide,
            ],
        )
        load_dm_demo.click(
            fn=lambda: (
                *_load_dm_demo_case(),
                _demo_guide("dm", handlers.dm_runtime_status()),
            ),
            outputs=[
                query,
                business_facts,
                acceptance,
                tenant,
                principal,
                scopes,
                domain_hint,
                environment,
                classification,
                risk,
                demo_guide,
            ],
        )
        execute_button.click(
            fn=lambda *args: _execute_ui(handlers, *args),
            inputs=[
                query,
                tenant,
                principal,
                scopes,
                environment,
                classification,
                risk,
                business_facts,
                acceptance,
                domain_hint,
            ],
            outputs=[
                chat,
                run_state,
                interaction,
                final_answer,
                trace_ref,
                flow_html,
                evidence_html,
                audit_html,
            ],
        )
        dm_resume.click(
            fn=lambda run_id, message, history: _resume_dm_ui(handlers, run_id, message, history),
            inputs=[run_state, dm_input, chat],
            outputs=[
                chat,
                dm_input,
                interaction,
                final_answer,
                trace_ref,
                flow_html,
                evidence_html,
                audit_html,
            ],
        )
        inspect_button.click(
            fn=lambda run_id: _inspect_ui(handlers, run_id),
            inputs=[inspect_run],
            outputs=[
                inspect_status,
                inspect_answer,
                inspect_flow,
                inspect_evidence,
                inspect_audit,
                inspect_trace_ref,
            ],
        )
        component_button.click(
            fn=lambda selected, run_id: handlers.component_probe(selected, run_id),
            inputs=[component, component_run],
            outputs=[component_output],
        )
        human_button.click(
            fn=lambda run_id, answers: _human_ui(handlers, run_id, answers),
            inputs=[human_run, human_answers],
            outputs=[human_output],
        )
    return cast(gr.Blocks, demo.queue(default_concurrency_limit=4))


def _load_demo_case() -> tuple[str, str, str, str, str, str, str, str, str, str]:
    return _load_case("expense_reimbursement_pre_audit.json")


def _load_dm_demo_case() -> tuple[str, str, str, str, str, str, str, str, str, str]:
    return _load_case("robot_353_loan_rejection_dm.json")


def _load_case(
    filename: str,
) -> tuple[str, str, str, str, str, str, str, str, str, str]:
    path = Path(__file__).resolve().parents[3] / "data/demo_cases" / filename
    payload = json.loads(path.read_text(encoding="utf-8"))
    domains = payload.get("domain_hints", [])
    domain = str(domains[0]) if domains else ""
    return (
        str(payload["query"]),
        json.dumps(payload.get("business_facts", {}), ensure_ascii=False, indent=2),
        "\n".join(str(item) for item in payload.get("acceptance_criteria", [])),
        str(payload["tenant_id"]),
        str(payload["principal_id"]),
        ",".join(str(item) for item in payload.get("scopes", [])),
        domain,
        str(payload["environment"]),
        str(payload["data_classification"]),
        str(payload["risk_level"]),
    )


def _demo_guide(kind: str, dm_status: dict[str, object] | None = None) -> str:
    if kind == "dm":
        enabled = bool(
            dm_status
            and dm_status.get("enabled")
            and dm_status.get("sit_enabled")
            and dm_status.get("robot_353_enabled")
        )
        runtime_badge = (
            '<span class="rta-runtime-ready">● 当前实例已开启 Robot 353 SIT</span>'
            if enabled
            else (
                '<span class="rta-runtime-off">● 当前实例未开启 Robot 353 SIT；'
                "执行会回退原 Control Plane</span>"
            )
        )
        return (
            '<div class="rta-demo-guide dm"><strong>真实 DM 演示说明</strong>：'
            "该案例使用已激活的 <code>robot_353.loan_rejection</code>，首轮预期进入 "
            "<code>DM_USER_INPUT</code>。机器人追问后，请在右侧输入 "
            "<code>Ya pagué mi préstamo anterior, pero fui rechazado.</code> 并继续原会话。"
            f'<div class="rta-guide-row">{runtime_badge}'
            "<span>✓ 本地 LLM：0 次</span><span>✓ 不编译 Blueprint</span>"
            "<span>✓ 不执行业务写操作</span><span>⚠ 需使用 DM SIT 配置和授权 Key 启动</span>"
            "</div></div>"
        )
    return (
        '<div class="rta-demo-guide"><strong>本地确定性演示说明</strong>：'
        "使用脱敏模拟业务事实，预期召回重复票据 Tool 与费用预审 FSM，计算住宿超标 "
        "120 元并给出人工复核路由；不会执行付款。"
        '<div class="rta-guide-row"><span>✓ 本地资产复用</span>'
        "<span>✓ 独立 Validator</span><span>✓ 可审计 Trace</span></div></div>"
    )


def _execute_ui(
    handlers: LocalUiHandlers,
    query: str,
    tenant: str,
    principal: str,
    scopes: str,
    environment: str,
    classification: str,
    risk: str,
    business_facts: str,
    acceptance: str,
    domain_hint: str,
) -> tuple[list[dict[str, Any]], str, str, str, str, str, str, str]:
    try:
        view = handlers.execute(
            query=query,
            tenant_id=tenant,
            principal_id=principal,
            scopes=scopes,
            environment=environment,
            data_classification=classification,
            risk_level=risk,
            business_facts_json=business_facts,
            acceptance_criteria=acceptance,
            domain_hint=domain_hint,
        )
    except Exception as exc:
        raise gr.Error(str(exc)) from exc
    history = [{"role": "user", "content": query}, *_chat_messages(view)]
    return _ui_result(view, history)


def _resume_dm_ui(
    handlers: LocalUiHandlers,
    run_id: str,
    message: str,
    history: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], str, str, str, str, str, str, str]:
    if not run_id or not message.strip():
        raise gr.Error("需要当前 Run ID 和真实用户回复。")
    try:
        view = handlers.resume_dm(run_id=run_id, message=message)
    except Exception as exc:
        raise gr.Error(str(exc)) from exc
    updated = [
        *(history or []),
        {"role": "user", "content": message},
        *_chat_messages(view),
    ]
    result = _ui_result(view, updated)
    return result[0], "", result[2], result[3], result[4], result[5], result[6], result[7]


def _chat_messages(view: TaskRunView) -> list[dict[str, str]]:
    messages = [
        {
            "role": str(message.get("role", "assistant")),
            "content": str(message.get("content", "")),
        }
        for message in view.messages
        if str(message.get("content", "")).strip()
    ]
    if not messages and view.answer.strip():
        messages.append({"role": "assistant", "content": view.answer})
    return messages


def _inspect_ui(
    handlers: LocalUiHandlers,
    run_id: str,
) -> tuple[str, str, str, str, str, str]:
    try:
        view = handlers.inspect(run_id)
    except Exception as exc:
        raise gr.Error(str(exc)) from exc
    return (
        _status_html(view),
        view.answer,
        render_task_flow(view),
        render_step_evidence(view),
        render_audit_summary(view),
        view.trace_ref or "",
    )


def _human_ui(handlers: LocalUiHandlers, run_id: str, answers: str) -> dict[str, Any]:
    try:
        return handlers.resume_human(
            run_id=run_id,
            answers_json=answers,
        ).model_dump(mode="json")
    except (ValueError, json.JSONDecodeError) as exc:
        raise gr.Error(str(exc)) from exc


def _ui_result(
    view: TaskRunView,
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, str, str, str, str, str, str]:
    return (
        history,
        view.run_id,
        _status_html(view),
        view.answer,
        view.trace_ref or "",
        render_task_flow(view),
        render_step_evidence(view),
        render_audit_summary(view),
    )


def _empty_view() -> TaskRunView:
    return TaskRunView(
        run_id="run_0000000000000000",
        route="CONTROL_PLANE",
        mode="—",
        status="NOT_EXECUTED",
        answer="尚未执行。",
        interaction_kind="NONE",
    )


def _empty_status() -> str:
    return """
    <div class="rta-status-grid">
      <div class="rta-stat"><small>运行状态</small><strong>尚未执行</strong></div>
      <div class="rta-stat"><small>决策路径</small><strong>—</strong></div>
      <div class="rta-stat"><small>业务验证</small><strong>—</strong></div>
      <div class="rta-stat"><small>交互状态</small><strong>—</strong></div>
    </div>
    """


def _status_html(view: TaskRunView) -> str:
    validated = "已通过" if view.business_validated else "待验证 / 不适用"
    status = html.escape(view.status)
    route = html.escape(view.route)
    mode = html.escape(view.mode)
    interaction = html.escape(view.interaction_kind)
    return (
        '<div class="rta-status-grid">'
        f'<div class="rta-stat"><small>运行状态</small><strong>{status}</strong></div>'
        f'<div class="rta-stat"><small>决策路径</small><strong>{route} · {mode}</strong></div>'
        f'<div class="rta-stat"><small>业务验证</small><strong>{validated}</strong></div>'
        f'<div class="rta-stat"><small>交互状态</small><strong>{interaction}</strong></div>'
        "</div>"
    )
