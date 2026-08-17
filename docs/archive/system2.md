# System 2 受控推理运行架构

> 本文只描述 System 2 的内部运行过程、控制边界和出口，不重复总体 Dify、Registry、LangGraph 或 Skill Governance 架构。

![System 2 Controlled Reasoning Architecture](assets/system2_controlled_reasoning_architecture.png)

图中的核心结论是：**System 2 不是一个拥有无限工具权限、可以无限循环的通用 Agent，而是被 Blueprint、Compiler、ACL、预算、Schema 和 Validator 包围的受控推理执行单元。**

---

## 1. System 2 在本项目中的职责

System 2 只处理三类无法由现有确定性资产直接完成的问题：

1. **Unknown**：Registry 中没有能够覆盖某个必需子目标的 FSM 或 Tool 组合；
2. **Ambiguous**：当前输入存在业务歧义，系统无法安全地确定时间、金额、审批人、收件人或执行对象；
3. **Exceptional**：执行过程中出现了不能由既有重试、补偿或确定性错误分支处理的异常。

System 2 不负责：

- 覆盖 Policy/ACL 的拒绝结果；
- 修改当前运行引用的 Active Skill；
- 临时生成任意代码、SQL、Jinja 或 Adapter 绕过 Schema；
- 为已被 FSM 覆盖的步骤重复进行 LLM 决策；
- 在工具失败后静默增加新的工具权限；
- 把“模型认为成功”直接当成任务成功。

### 1.1 两种调用形态

| 形态 | 发生时机 | System 2 做什么 | 不做什么 |
| --- | --- | --- | --- |
| Planning-time System 2 | HYBRID/NEW 计划生成或 Compiler 返回结构化错误时 | 在候选资产白名单和固定 Snapshot 内提议 Blueprint；最多进行一次受限修订 | 不自我批准计划，不绕过 Compiler |
| Runtime System 2 | Meta-Executor 调度到 `reason` Step 时 | 在单个未知子目标内执行有界 Observe/Act 循环，产生类型化 Artifact | 不改动其他 Blueprint Step，不扩展 Tool Allowlist |

NEW 并不表示把整条请求交给一个无限 Agent Loop。NEW 表示现有资产无法安全覆盖任务，因此需要 System 2 提议新的受控计划；这个计划仍然必须经过 Blueprint Compiler，运行时仍由固定 Meta-Executor 执行。

---

## 2. 图中的四类入口

### 2.1 `HYBRID — CAPABILITY GAP`

部分目标已经由 Active FSM 覆盖，但至少一个目标缺少能力或逻辑。

例如：

```text
新日志系统读取与错误判断       -> 未覆盖，进入受限 Reason
标准 Jira P1 创建             -> 已有 FSM，确定性执行
企业微信通知                  -> 已有 FSM，确定性执行
```

System 2 只处理第一步。它输出通过验证的 `VerifiedErrorFact` 后，立即退出并重新接入 Jira FSM；后两步不再逐步询问 LLM。

### 2.2 `NEW — NO SAFE COVERAGE`

出现以下任一情况时进入 NEW：

- 关键目标没有安全可执行路径；
- 现有 Skill 的前置条件、Effect 或 Schema 与任务不匹配；
- Blueprint 无法通过编译；
- 必需 Validator 缺失；
- 任务属于从未覆盖的新业务族。

NEW 允许 System 2 进行更完整的计划提议，但工具、预算、权限和风险边界仍由平台提供，不能由模型自行放宽。

### 2.3 `CLARIFY — AMBIGUOUS INPUT`

以下参数不得静默猜测：

- 收件人、审批人或通知群；
- 金额、支付账户、退款范围；
- 删除对象和批量操作范围；
- 相对时间缺少时区或日期基准；
- 多个同名业务对象无法唯一定位。

System 2 应产生结构化澄清问题并进入 `WAITING_HUMAN`，而不是连续推测多个可能值。

### 2.4 `RUNTIME EXCEPTION`

并非所有运行错误都会重新触发 System 2：

| 错误 | 默认处理 | 是否交给 System 2 |
| --- | --- | --- |
| 瞬时超时、限流、可恢复 5xx | 按确定性 Retry Policy 退避 | 否 |
| `POLICY_DENIED` | 拒绝并审计 | 否，模型不能绕过权限 |
| `INPUT_AMBIGUOUS` | Human Interrupt | 只生成澄清问题 |
| `PRECONDITION_FAILED` | 查找已注册前置能力或澄清 | 必要时重新规划，但必须重新编译 |
| `OUTPUT_VALIDATION_FAILED` | 显式修复、补偿或停止 | 只有预先允许的受限修复才可进入 |
| `SIDE_EFFECT_UNKNOWN` | 先查询/Validator 确认实际状态 | 无法确认时转人工，不直接重放写操作 |
| `BUDGET_EXCEEDED` | 安全停止 | 否 |
| `COMPENSATION_FAILED` | 立即升级人工 | 否 |

运行时禁止“工具报错 -> LLM 临时改图 -> 使用新工具继续执行”。需要新路径时，应生成新的候选 Blueprint，重新通过 Compiler 后再启动或恢复受控执行。

---

## 3. Stage 1：Freeze Context

进入 System 2 时先冻结当前运行上下文。图中包含四类输入：

### 3.1 Task State

只提供完成当前未知子目标所需的最小状态：

- 当前子目标和期望完成状态；
- 已完成步骤的安全输出摘要；
- 当前可读取的 Artifact URI；
- 明确的业务约束和验收条件。

不应把完整会话、所有历史 Trace 或无关 Skill Body 全部塞入 Prompt。

### 3.2 Snapshot

System 2 固定使用 Blueprint 中的 `registry_snapshot_id`：

- Tool、Schema、Validator 和 Adapter 均引用 Snapshot 中的精确版本；
- 当前运行不读取“最新版本”；
- Registry 即使发布新资产，也不会热切换当前 Reason Step；
- 回放时能够恢复相同的可见资产集合。

### 3.3 Caller ACL

ACL 来自已认证身份和服务身份，不由 LLM 生成：

- `tenant_id`；
- 用户/服务 Principal；
- Role 和 Scope；
- 数据区域、环境和风险上限；
- 当前可用 Tool Runtime。

System 2 只能缩小权限，不能扩大权限。

### 3.4 Evidence

Evidence 是结构化事实，不是未经验证的自由文本：

- Tool 返回的类型化结果；
- Validator 通过的中间状态；
- 错误码、错误分类和安全摘要；
- 已发生外部副作用的 Execution Ledger 记录；
- Human 已确认的输入。

---

## 4. Stage 2：Classify Gap

在调用 Reason Model 前，系统必须先判断缺口类型。

### 4.1 Value Gap

Value Gap 表示动作已经明确，只缺参数值。例如“明天下午请假”缺少 ISO 时间。

处理顺序：

```text
Session/Business Context
  -> Rule / Date Parser / Regex / NER
  -> Structured LLM Extractor
  -> JSON Schema + Business Validation
  -> Still Ambiguous: Human Interrupt
```

Value Gap 默认进入 `extract`，不是 `reason`。Extractor 只能提取字段，不能决定新增业务动作。

### 4.2 Adapter Gap

Adapter Gap 表示已有输出和下一步输入在类型或字段结构上不兼容。

```text
VerifiedErrorFact -> JiraP1CreateInput
ticket_url        -> message.text
```

只能使用 Snapshot 内已注册、已测试的 Adapter。不存在 Adapter 时，System 2 可以生成 `Adapter Candidate`，但当前运行不能执行临时生成的代码。

### 4.3 Capability / Logic Gap

只有真正的新能力、新逻辑或未知环境操作进入 `reason`：

- 新日志源尚无 FSM；
- 新业务系统只有受控 Primitive Tools；
- 需要在有限观察中判断下一次只读操作；
- 需要生成满足固定 Schema 的新事实 Artifact。

### 4.4 Policy Denied

Policy Denied 是终止条件，不是推理问题。

例如当前用户没有 `jira:issue:create` 权限时，即使模型可以写出正确参数，也不得调用 Jira。System 2 只能返回结构化拒绝原因或请求合法授权，不能寻找其他账号、其他工具或旁路 API。

---

## 5. Stage 3：Build Constraints

控制包络由普通代码和 Compiler 构建，不由 Reason Model 自己生成。

一个运行时 `reason` Step 可以使用以下结构：

```json
{
  "step_id": "reason_read_new_log_source",
  "type": "reason",
  "goal": "从授权日志源获得结构化且可验证的错误事实",
  "registry_snapshot_id": "rs_20260715_00042",
  "allowed_tool_refs": [
    "tool.newlog.search@1.0.0",
    "tool.newlog.get_context@1.0.0"
  ],
  "budgets": {
    "max_reason_steps": 3,
    "max_llm_calls": 2,
    "max_input_tokens": 2400,
    "max_output_tokens": 500,
    "deadline_ms": 15000,
    "max_tool_calls": 3
  },
  "output_schema_ref": "schema://it/verified-error-fact/1",
  "validator_refs": [
    "validator.error_fact@1.2.0"
  ],
  "side_effect_policy": "READ_ONLY",
  "human_gate": {
    "required_for": ["scope_change", "external_write", "sensitive_data_export"]
  }
}
```

### 5.1 Tool Allowlist

Reason Model 只能返回：

- `CALL_TOOL`：调用白名单中的一个工具；
- `FINISH`：提交符合 Output Schema 的候选结果；
- `ASK_HUMAN`：请求明确输入或批准；
- `ABORT`：无法安全完成。

模型返回未知工具名时，Action Gateway 直接拒绝，不尝试模糊匹配或自动注册。

### 5.2 Max Steps

`max_reason_steps` 是控制 Reason 循环的硬上限。达到上限后必须进入 Fail/Budget Exhausted，不能通过“创建新的子任务”绕过计数。

### 5.3 Token + Time

预算至少包含：

- LLM 调用次数；
- 输入/输出 Token；
- Tool 调用次数；
- Reason Loop 迭代数；
- Wall-clock Deadline；
- 可选的模型费用和工具费用。

预算检查在每次模型调用前、每次工具调用前和每次状态更新后执行。

### 5.4 Output Schema

System 2 必须产生类型化 Artifact，例如：

```json
{
  "service": "app-pay-01",
  "environment": "prod",
  "error_code": "DB_CONN_TIMEOUT",
  "suspected_cause": "database_connection_pool_exhausted",
  "observed_at": "2026-07-16T02:10:31Z",
  "evidence_refs": ["artifact://run-102/log-window-1"]
}
```

自由文本解释可以作为安全摘要，但不能替代下游 FSM 需要的结构化输出。

### 5.5 Validator

Validator 与 Reason Model 分离。模型不能同时负责生成结论和批准自己的结论。

Validator 检查：

- JSON Schema；
- 必填字段和枚举；
- 时间窗、数值范围和业务不变量；
- Evidence 是否真实存在；
- Tool Observation 是否支持该结论；
- 下游 Contract 所需的完成状态是否达到。

### 5.6 Side-effect Rule

建议 PoC 阶段的 Reason Step 默认为 `READ_ONLY`。

如果以后允许受控写操作，必须同时满足：

- Tool Contract 明确声明副作用；
- Blueprint 中显式列出写 Tool；
- 用户/服务身份具有 Scope；
- 提供服务端 Idempotency Key 或本地去重账本；
- 高风险写操作存在 Human/Policy Gate；
- 超时后先查询真实状态，不能直接重放。

---

## 6. Stage 4：Bounded Reason Loop

图中的循环为：

```text
OBSERVE
  -> SELECT ALLOWED TOOL
  -> ACT
  -> UPDATE STATE
  -> BUDGET CHECK
  -> OBSERVE / FINISH / HUMAN / ABORT
```

### 6.1 Observe

Reason Model 接收：

- 当前 Goal；
- 已冻结的权限和预算；
- 可用 Tool Header 与 Input Schema；
- 上一次 Observation 的安全摘要和 Artifact 引用；
- 尚未满足的 Output Schema 字段；
- Validator 返回的结构化错误码。

不向模型暴露 Tool Secret，也不默认提供完整底层日志。

### 6.2 Select Allowed Tool

模型输出受限枚举和结构化参数：

```json
{
  "action": "CALL_TOOL",
  "tool_ref": "tool.newlog.search@1.0.0",
  "arguments": {
    "service": "app-pay-01",
    "time_range": "PT15M",
    "query": "DB_CONN_TIMEOUT"
  },
  "reason_code": "NEED_PRIMARY_ERROR_EVIDENCE"
}
```

系统只记录 `reason_code` 和结构化决策，不要求保存完整 Chain-of-Thought。

### 6.3 Act

Action Gateway 在真正调用 Tool 前重新执行：

1. Tool 是否在 Allowlist；
2. `tool_ref` 是否属于当前 Snapshot；
3. Caller Scope 是否满足 Tool Contract；
4. 参数是否通过 Input Schema；
5. 风险、配额和环境是否允许；
6. 写操作是否具有 Idempotency Key/Human Gate；
7. 预算是否仍有余额。

模型输出不是执行授权；Action Gateway 的检查结果才是。

### 6.4 Update State

Tool 返回后，系统将结果转换为小型 Reason State：

```json
{
  "iteration": 1,
  "remaining_reason_steps": 2,
  "remaining_llm_calls": 1,
  "tool_status": "SUCCEEDED",
  "observation_summary": {
    "matched_lines": 18,
    "error_code": "DB_CONN_TIMEOUT",
    "pool_usage": "100%"
  },
  "artifact_refs": ["artifact://run-102/log-window-1"],
  "unmet_output_fields": ["suspected_cause"]
}
```

大日志写入对象存储，Checkpoint 只保存摘要、Digest 和 Artifact URI，避免状态膨胀。

### 6.5 Budget Check

以下任一条件成立时循环停止：

- 达到最大 Reason Steps；
- 达到最大 LLM/Tool Calls；
- Token 或费用超过上限；
- Deadline 到期；
- Output Schema 已完整，可以提交验证；
- 需要人工输入；
- 工具或 Policy 返回不可恢复错误。

`NO TOOL EXPANSION` 是硬约束：预算未耗尽也不能访问 Allowlist 之外的能力。

---

## 7. Stage 5：Verify Output

System 2 返回的候选结果按固定顺序验证。

### 7.1 Schema

验证类型、必填字段、枚举、格式和版本。失败时返回确定性错误，例如：

```text
OUTPUT_SCHEMA_INVALID
missing: /evidence_refs
invalid_enum: /environment
```

### 7.2 Evidence

确认结果引用的 Artifact 存在、属于当前 Run、Digest 正确且调用者有权访问。模型凭空生成的 URI 或日志行不能通过。

### 7.3 Business Validator

确认业务状态已经达到，而不是只检查 API 返回 200。

例如 `VerifiedErrorFact` 至少要求：

- 服务、环境、错误码完整；
- 观察时间处于请求时间窗；
- 至少存在一条匹配日志证据；
- 原因判断由允许的证据支持；
- 数据未跨 Tenant。

### 7.4 Policy Guard

再次检查输出的数据分类、可见范围和下游用途。读取日志被允许，不代表日志内容可以原样发送到企业微信群。

### 7.5 Ledger

记录：

- `run_id/step_id/attempt`；
- 固定的 Snapshot、Model 和 Tool 版本；
- Tool Calls、Token、延迟和费用；
- Output Schema 与 Validator 结果；
- Artifact URI 和 Digest；
- Human 决策和错误分类；
- 最终出口。

---

## 8. Outcome Router 的三个出口

### 8.1 PASS -> Typed Artifact

只有所有 Validator 和 Policy Guard 通过后，System 2 才产生已验证的类型化 Artifact。

```text
System 2 Reason Step
  -> VerifiedErrorFact
  -> Deterministic Adapter
  -> Jira FSM
  -> Notification FSM
```

这就是图中的 `REJOIN DETERMINISTIC EXECUTION`。System 2 完成未知部分后应尽快退出，不继续接管已存在的确定性路径。

### 8.2 NEED INPUT / HIGH RISK -> Human Interrupt

进入 `WAITING_HUMAN` 时必须持久化：

- 当前 Step 和 Checkpoint；
- 需要回答的问题；
- 可选项及其业务影响；
- 过期时间；
- 恢复所需的 `interrupt_id`；
- 已发生的外部副作用摘要。

恢复时使用同一 `run_id` 和 Snapshot，并重新校验 Human 的身份和权限。

### 8.3 FAIL / BUDGET EXHAUSTED

失败出口根据副作用状态选择：

- **SAFE STOP**：尚未产生外部副作用，安全终止；
- **COMPENSATE**：已执行可补偿写操作，按预注册 Saga 补偿；
- **ESCALATE**：状态不确定、补偿失败或风险过高，升级人工。

预算耗尽不能自动切换到更大模型、增加步数或申请更多工具权限。

---

## 9. One Plan Repair Only

图上方表示规划期的单次修复通道：

```text
STRUCTURED COMPILER ERROR
  -> CONSTRAINED REVISION
  -> RECOMPILE
  -> PASS 或 CLARIFY / REJECT
```

Compiler 必须返回结构化错误，例如：

```json
{
  "error_code": "TYPE_MISMATCH",
  "step_id": "create_ticket",
  "from_schema": "VerifiedErrorFact@1",
  "to_schema": "JiraP1CreateInput@3",
  "allowed_adapter_refs": ["adapter.errorfact_to_jira@1.0.0"]
}
```

System 2 只能在以下范围内修订：

- 使用 Compiler 提供的已注册 Adapter；
- 修改候选 Step 的合法输入绑定；
- 删除不可达或重复 Step；
- 在候选白名单中选择替代资产；
- 对真实歧义生成 Human Step。

修订后只允许重新编译一次。仍然无效时进入 CLARIFY/REJECT，不能形成无限“提议—编译—修改”循环。

---

## 10. 异步证据演进，不在线热修复

图底部紫色路径为：

```text
STRUCTURED TRACE
  -> CANDIDATE DISTILLER
  -> DRAFT PATCH / NEW SKILL
  -> TEST
  -> SHADOW
  -> CANARY
  -> ACTIVE
```

System 2 成功不代表其本次行为立即变成 Skill。异步治理流程必须满足：

1. Trace 只保存动作、结构化理由码、输入输出摘要、Validator、错误、Token 和 Artifact 引用；
2. 多次独立成功才具有更强的沉淀价值；
3. Umbrella-First 检查能否作为已有 Skill 的参数、Patch、组合或新版本；
4. 新资产先进入 Draft；
5. 通过 Contract Test、Golden、Replay、Security Test；
6. 经 Shadow 和 Canary 验证；
7. 发布新 Active 版本并进入新的 Registry Snapshot；
8. 当前 Run 永远不切换到刚生成的新版本。

这条异步路径是 Token 随使用下降的关键：高频且稳定的 Reason Step 被离线蒸馏为 FSM 后，未来同类请求会从 NEW/HYBRID 逐步转为 REUSE。

---

## 11. 一个完整的 HYBRID System 2 运行示例

任务：

```text
从尚未沉淀 FSM 的 NewLog 系统读取 app-pay-01 最近 15 分钟日志，
确认 DB_CONN_TIMEOUT 后创建 Jira P1 并通知 payment-oncall。
```

已有能力：

- `fsm.jira.p1.create@1.3.2`；
- `fsm.wecom.notify_oncall@2.1.0`。

缺口：NewLog 只有两个受控只读 Tool，没有 FSM。

运行过程：

1. Mode Router 选择 `HYBRID`；
2. Blueprint 包含一个 `reason` Step 和两个版本固定 FSM；
3. Compiler 校验 Tool Allowlist、Scope、预算、Output Schema、Validator 和下游类型；
4. Meta-Executor 调度 `reason_read_new_log_source`；
5. System 2 冻结 Snapshot、Caller ACL 和当前 Task State；
6. Gap Classifier 判定为 `Capability/Logic Gap`；
7. Constraint Builder 设置 3 个 Reason Steps、2 次 LLM、3 次 Tool Call、15 秒、只读副作用；
8. 第一次 Observe 后选择 `tool.newlog.search@1.0.0`；
9. Action Gateway 验证白名单、Scope 和参数 Schema 后调用；
10. Tool 返回 18 条匹配日志，完整内容写对象存储；
11. Reason State 保存错误码、连接池利用率摘要和 Artifact URI；
12. System 2 输出 `VerifiedErrorFact` 候选；
13. Schema、Evidence、Business Validator 和 Policy Guard 通过；
14. Ledger 写入 Token、Tool Call、版本和验证结果；
15. Outcome Router 输出 PASS；
16. `VerifiedErrorFact` 重新接入确定性 Jira FSM；
17. Jira FSM 完成后进入确定性企业微信 FSM；
18. Reason Trace 异步进入 Candidate Distiller，但当前 Run 不修改 Active Registry。

如果第 13 步 Validator 不通过：

- 仍有预算且错误属于预先允许的证据缺失，可再执行一次白名单只读查询；
- 出现业务歧义则 Human Interrupt；
- 达到预算或仍不满足 Validator，则 Safe Stop；
- 不允许跳过 Validator 继续创建 Jira。

---

## 12. System 2 的实现组件

| 组件 | 推荐职责 |
| --- | --- |
| `System2InvocationService` | 组装冻结上下文，创建受控 Reason Run |
| `GapClassifier` | 使用规则优先、小模型兜底区分 Value/Adapter/Capability/Policy Gap |
| `ConstraintBuilder` | 从编译后的 Blueprint 生成 Allowlist、预算和验证约束 |
| `BoundedReasonNode` | 调用模型并维护有限 Observe/Act 状态 |
| `ActionGateway` | 在 Tool 调用前执行版本、ACL、Schema、风险和预算检查 |
| `ArtifactStore` | 保存大型 Observation、日志和模型输出制品 |
| `ValidatorRunner` | 独立执行 Schema、Evidence 和业务 Validator |
| `ExecutionLedger` | 保存 Tool 副作用、幂等键、成本和状态转换 |
| `HumanInterruptService` | 持久化澄清/审批并安全恢复 |
| `CandidateDistiller` | 异步从 Trace 产生 Draft Patch 或 Skill Candidate |

推荐把 `BoundedReasonNode` 作为固定 LangGraph Meta-Executor 的一种 Executor 类型，而不是为每个请求动态生成一张新 LangGraph。

---

## 13. Token 与可观测性

System 2 每次运行至少记录：

```text
reason_input_tokens
reason_output_tokens
reason_llm_call_count
reason_step_count
reason_tool_call_count
reason_latency_ms
reason_model_cost
validator_pass / validator_error_code
human_interrupt_count
exit_mode = PASS / HUMAN / SAFE_STOP / COMPENSATE / ESCALATE
```

跨服务统一携带：

```text
trace_id / run_id / step_id / attempt / registry_snapshot_id
```

关键指标：

- `bounded_reason_success_rate`；
- `reason_budget_exhaustion_rate`；
- `reason_to_human_rate`；
- `validator_rejection_rate`；
- `reasoning_avoidance_rate`；
- `reason_candidate_to_active_rate`；
- `cost_per_validated_success`。

随着成功的未知路径被治理为 Active FSM，同任务族的 `reason_step_count`、`reason_llm_call_count` 和 NEW/HYBRID 占比应下降。

---

## 14. 验收条件

System 2 上线前至少满足：

| 验收项 | 通过标准 |
| --- | --- |
| Tool Allowlist | 100% 拒绝 Blueprint 之外的 Tool Ref |
| ACL | 越权调用为 0，Policy Denied 不能被模型重试绕过 |
| Budget | 达到 Step/Token/Time/Cost 任一上限后可靠停止 |
| Schema | 不符合 Output Schema 的结果不能进入下游 FSM |
| Validator | 每个 PASS 都有独立 Validator 证据 |
| Snapshot | Reason Step 全程使用同一个 Registry Snapshot |
| Side Effect | 写操作具备幂等/补偿/Human Gate；未知状态不盲重放 |
| Plan Repair | Compiler 修订最多一次，仍失败则澄清或拒绝 |
| Trace | 不默认保存完整 Chain-of-Thought；敏感数据只存脱敏摘要或引用 |
| Evolution | 当前 Run 不热修改 Active 资产；只异步生成 Draft/Candidate |
| Rejoin | System 2 完成未知子目标后能以类型化 Artifact 接回确定性链 |

最终边界可以概括为：

> System 2 可以探索，但探索范围必须预先编译；可以调用工具，但只能调用白名单；可以提出结果，但不能自行批准；可以贡献经验，但不能在线修改当前运行的生产资产。
