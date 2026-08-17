# 项目设计记忆（实现阶段长期核对版）

> 状态：当前统一设计口径  
> 首次整理：2026-07-27  
> 主要依据：`System_Structure.md`  
> 用途：后续需求分析、架构决策、编码、评审和重构前先快速核对本文件。它记录的是设计意图和不可轻易破坏的约束，不是要求实现细节永久不变。

---

## 0. 如何使用和维护本文件

### 0.1 文档优先级

发现文档表述不一致时，按以下顺序判断：

1. 用户后续明确提出的新要求；
2. `System_Structure.md` 的当前主设计；
3. 专项细化稿：`database.md`、`system2.md`；
4. 综合工程化稿：`Project.md`、`diff_Fregment.md`；
5. 早期思路与研究摘录：`Token Reduce_Plan.md`、`Fregment_Plan.md`、`Fragment_FSM_WorkFlow.md`、`Agent_Improve_Method.md`、`Skill_Improve_Method.md`、`PDF Parse.md`。

早期文档用于理解设计缘起，不应覆盖后期已经完成的工程化修正。

### 0.2 更新规则

- 架构调整可以发生，但必须继续服务于本文件第 1 节的北极星目标。
- 改动“硬约束”前，必须记录：改动原因、风险、替代保护机制和验证结果。
- 真实业务数据尚未决定的阈值、模型、Top-K、样本数和 SLO 应留在配置或评测报告中，不应伪装成架构真理。
- 每次重大设计变更后，更新文末“决策与变更记录”。

---

## 1. 一句话北极星

把 Agent 在陌生任务上的高成本推理，逐步沉淀为**经过验证、版本固定、契约明确、可恢复、可审计的确定性执行资产**；未来遇到相同或部分相同任务时，仅对真正未知的局部使用受控推理，在不牺牲正确性、安全性和可回滚性的前提下，降低每个验证成功任务的 Token、成本与延迟。

这套系统追求的不是“更自由的 Agent”，而是：

> **确定性复用 + 受控推理 + 证据驱动演进。**

---

## 2. 设计要解决的三个核心问题

### Q1：历史经验只覆盖新任务的一部分

“60% 匹配”不是某个向量相似度，而是任务的部分必需子目标已经有安全、可执行、可验证的路径。

解决方式：

- 不复用端到端黑盒长 Workflow；
- 复用中等粒度、单一子目标、高内聚的 FSM Shard；
- 显式区分已覆盖部分与 Value、Adapter、Capability/Logic 缺口；
- 用类型化 Blueprint 组合确定性步骤与有限未知步骤；
- Blueprint 必须通过确定性 Compiler 后，才交给固定 Meta-Executor 执行。

### Q2：经验增长造成技能膨胀、重复和退化

经验库不能是“成功一次就追加一篇文档”的向量垃圾堆，而应像软件制品库一样治理。

解决方式：

- Trace 只生成 Experience Candidate/Draft，不能直接 Active；
- Active 资产不可变，Patch 永远产生新版本；
- 使用 Umbrella-First 判断重复、参数变体、替代实现、组合关系和真正新能力；
- 经过测试、Replay、Shadow、Canary 后才能发布；
- 退化资产先 Quarantine/Deprecated/Retired，不因低频或低分直接物理删除；
- 当前运行与后台演进严格解耦，禁止在线热修复当前 Active 版本。

### Q3：任务拆解粒度与技能粒度不一致

只做向量检索会把“文本相似”误当成“可以执行”，也会因过度拆解或欠拆解错过已有能力。

解决方式：

- 先粗拆为最少数量的业务子目标和期望状态；
- 在数据库阶段先执行 Tenant、ACL、状态、环境、风险和版本硬过滤；
- Sparse、Dense、Metadata、Capability Graph 混合召回；
- 用 RRF 融合不可直接比较的排名；
- 用一次 SAD 反馈把拆解粒度对齐实际存在的能力；
- Top-N 再加载 Contract，按 Goal、Precondition、Effect、Schema、Policy、Reliability 重排；
- 最终以 Plan Coverage 和 Compiler Gate 判定是否可执行，而不是用单一相似度阈值。

---

## 3. 不可轻易破坏的设计原则

### 3.1 LLM 只能提议，不能批准自己

- Plan Proposer 可以由 LLM 生成候选 Blueprint；
- Blueprint Compiler 必须由普通确定性代码实现；
- Reason Model 可以产出候选 Artifact；
- Schema、Evidence、Business Validator 和 Policy Guard 必须独立验证；
- 生成 Patch 的模型不能单独担任最终 Judge。

### 3.2 已知路径确定执行，未知路径局部推理

- 已由 FSM、Tool、Adapter、Validator 覆盖的步骤不再逐步询问 LLM“下一步做什么”；
- System 2 只处理 Unknown、Ambiguous、Exceptional；
- System 2 完成局部未知子目标后，应以类型化 Artifact 尽快接回确定性链；
- NEW 也不等于开放一个无限 Agent Loop。

### 3.3 同步任务链与异步演进链分离

同步链只负责把当前任务安全完成或安全停止。异步链根据 Trace 产生未来资产。

```text
当前任务：Normalize -> Retrieve -> SAD -> Propose -> Compile -> Execute -> Validate

后台演进：Trace -> Candidate -> Patch/Draft -> Test -> Shadow -> Canary -> Active
```

当前 Run 永远不能切换到自己刚刚生成的新版本。

### 3.4 资产事实、运行证据和检索索引分离

- Evidence 说明“过去发生过什么”；
- Registry 说明“当前允许复用什么”；
- Retrieval Projection 说明“怎样快速找到候选”；
- 索引可以重建，资产事实和审计证据不能依赖向量库唯一保存。

### 3.5 被召回不等于可执行

候选还必须依次经过：

1. SAD 粒度对齐；
2. Contract Rerank；
3. 类型、权限、风险、预算、版本、幂等和 Validator 等 Compiler Gate。

### 3.6 恢复能力不等于外部副作用严格一次

- Checkpoint 解决“图执行到哪里、恢复时状态是什么”；
- Execution Ledger、Idempotency Key、Outbox/回查和 Compensation 解决“外部写操作是否已经发生”；
- 写操作超时但状态未知时，先查询或验证，不能直接重放。

### 3.7 Token 优化不能越过正确性和安全性

- 优化目标是 `cost_per_validated_success` 和 `tokens_per_validated_success`；
- 不允许通过跳过澄清、Validator、权限或人工审批来节省 Token；
- “0 Token”只可描述已路由确定性步骤的执行决策，不代表整条请求没有路由、Embedding、SAD、抽取、Reason 或最终整理成本。

---

## 4. 总体职责划分

### 4.1 Dify：控制平面

主要职责：

- 统一用户/API 入口、会话和业务上下文；
- Task Normalization；
- Capability Retrieval 调用与候选管理；
- 一次 SAD Alignment；
- Plan Proposal；
- 模式选择和人工交互；
- 调用 Compile/Run/Status/Resume 等执行服务；
- 展示结果、状态和 Interrupt。

不应承担：

- Active 资产唯一事实源；
- 执行账本唯一事实源；
- 未经编译 Blueprint 的直接执行；
- 对 Active Skill Body 的直接覆盖。

### 4.2 LangGraph：执行平面

主要职责：

- 运行固定 Meta-Executor；
- 按编译后的 Blueprint 调度固定版本 Executor；
- 状态持久化、暂停、恢复和 Human Interrupt；
- Step 级重试、超时、验证、账本、补偿和失败升级；
- 承载 FSM、Tool、Extract、Adapter、Reason、Human 等有限 Executor 类型。

LangGraph 是高可靠“肌肉记忆引擎”，不是每个请求都重新生成的一张任意图。

### 4.3 Registry/Governance：资产与治理平面

主要职责：

- 不可变版本、发布状态、ACL、依赖图和 Snapshot；
- Route Header、Contract、Artifact 和证据链；
- Candidate、Patch、Evaluation、Release、Rollback；
- Registry Snapshot 的一致性和可复现性。

### 4.4 System 2：受控推理单元

主要职责：

- 规划期在白名单和固定 Snapshot 内提议或修订 Blueprint；
- 运行期只处理单个未知子目标；
- 产出可独立验证的类型化 Artifact；
- 对真实歧义产生 Human Interrupt；
- 为后台演进贡献结构化证据。

它无权扩大 ACL、扩展 Tool Allowlist、绕过 Compiler/Validator、在线改 Active 或无限循环。

---

## 5. 在线请求的标准链路

1. **Task Normalize**  
   提取身份、租户、角色、Scope、目标、验收条件、实体、时间基准、环境、数据分类和风险。Normalizer 不规划工具顺序。

2. **Pass-1 粗拆**  
   生成最少数量的高层业务子目标及期望状态，不拆到 HTTP 连接、请求、落盘等工具内部动作。

3. **固定 Registry Snapshot**  
   从本次检索开始，到 SAD、Rerank、Compiler 和执行均使用同一个 `registry_snapshot_id`。

4. **Hard Filter**  
   在数据库候选集合阶段过滤 Tenant、ACL、发布状态、环境、风险、Runtime/Schema 版本和工具可用性。越权资产不得进入 Prompt。

5. **Hybrid Retrieval**  
   Sparse/FTS、Dense/Vector、Metadata、Capability Graph 并行召回；使用 RRF 融合，图扩展默认只允许一跳。

6. **SAD 一次对齐**  
   只给模型 Route Header 和必要 Contract 摘要，让拆解边界对齐实际能力；不得删除未覆盖用户目标；无法对齐则转 System 2 或澄清，不做无限循环。

7. **Contract Rerank**  
   只为 Top-N 加载完整 Contract 的必要部分，评估 Goal、Precondition、Effect、Schema、Policy 和 Reliability。

8. **Plan Propose**  
   LLM 只能引用当前 Snapshot 中的候选固定版本和允许的 Step 类型，输出结构化 Blueprint。

9. **Deterministic Compile**  
   校验 Schema、DAG/受控循环、类型、ACL、风险、版本、预算、幂等、补偿、Validator、Human Gate 和输入绑定。结构化错误最多允许一次受限修订。

10. **Mode Route**  
    - 全部必需目标有安全路径：`REUSE`；
    - 部分覆盖且未知部分受控：`HYBRID`；
    - 无安全路径、关键歧义、越权、缺 Validator 或编译失败：`NEW / CLARIFY / REJECT`。

11. **Meta-Executor 执行**  
    选择 Ready Step，加载固定 Contract，检查前置条件和幂等账本，执行，验证输出，写 Ledger/Checkpoint，再推进、重试、补偿或暂停。

12. **Guard 后输出**  
    只有 Schema、业务 Validator 和 Policy Guard 通过的结果才能作为成功输出。

13. **异步 Trace 入库**  
    保存结构化事件、版本、成本、错误、Validator、Human 决策和 Artifact 引用；默认不保存完整 Chain-of-Thought。

---

## 6. 资产模型与正确粒度

### 6.1 资产类型

| kind | 含义 | 是否普通召回 | 是否直接执行 |
| --- | --- | --- | --- |
| `PRIMITIVE_TOOL` | 单个受控 API/函数 | 是 | 是 |
| `FSM_SHARD` | 完成一个稳定业务子目标的小状态图 | 是，通常优先于内部 Tool | 是 |
| `WORKFLOW_SKELETON` | DAEF 宏观状态/数据流骨架 | 作为规划先验单独召回 | 否 |
| `ADAPTER` | 确定性 Schema/字段转换 | 通常由关系扩展加入 | 是 |
| `VALIDATOR` | 证明输出或业务状态已达到 | 通常由关系扩展加入 | 是 |
| `BLUEPRINT` | 某次请求的版本固定执行实例 | 否 | 由 Meta-Executor 解释执行 |

`Skill` 只是产品层上位词，代码和数据库必须使用明确 `kind`。

### 6.2 FSM Shard 的切分准则

一个合格的 FSM Shard 应满足：

- 单一、可验证的业务子目标；
- 内部步骤高内聚，通常共享数据对象、权限域和恢复策略；
- 输入输出可以类型化；
- 失败、重试、回退或补偿边界局部可控；
- Filled Values 已参数化；
- 有重复证据或明确人工设计依据。

优先切分位置：

- Artifact/Schema 发生变化；
- 权限域、租户或风险等级变化；
- 进入不可逆副作用前；
- Validator/审批责任变化；
- 重试或补偿策略变化；
- 形成可独立复用的完成状态。

不应切分：

- 已由稳定 Tool 封装的内部 HTTP 动作；
- 同一事务中无法独立提交的连续步骤；
- 无法定义独立完成状态的过细动作；
- 仅因 Trace 多出一行日志。

### 6.3 DAEF 的定位

DAEF 保存领域无关的宏观阶段和状态不变量，例如：

```text
Information -> Transform -> Decision -> Action
```

它是规划先验，不绑定具体工具，不直接执行，也不能压过当前任务约束和具体 Skill Contract。

### 6.4 Contract 最小语义

每个可执行资产至少明确：

- Goal / Operation；
- Input Schema；
- Preconditions；
- Output Schema / Artifact；
- Effects 与副作用；
- Validators；
- Known Failure Modes；
- Tool/Runtime 依赖；
- Timeout / Retry；
- Idempotency / Compensation；
- Required Scopes、Tenant、环境、风险、数据分类；
- Owner、Provenance、Test Suite、Artifact Digest。

可概括为 SkillOps 的 `P/O/A/V/F`，但生产 Contract 还必须补齐版本、安全、幂等、补偿和治理信息。

---

## 7. Blueprint 与 Compiler

### 7.1 Blueprint 的本质

Blueprint 是当前任务的**数据化执行实例**，引用固定版本资产，不是直接拼接代码，也不应因一次成功自动变成全局 Skill。

固定 Step 类型：

- `fsm`
- `tool`
- `extract`
- `adapter`
- `reason`
- `validator`
- `human`

新增 Step 类型必须升级 Blueprint Schema，不能由 LLM 临时发明。

### 7.2 Compiler 的硬门禁

至少检查：

- Blueprint JSON Schema；
- Step ID 唯一、依赖存在、DAG 无环；
- 受控循环显式声明 `max_iterations`；
- 所有资产属于同一 Snapshot 且版本可见；
- 上下游 Schema/Artifact 类型兼容；
- Adapter 是已注册、已测试版本；
- 用户和服务身份满足 Tenant/ACL/Scope；
- 风险、数据分类、Secret 和跨租户访问合规；
- 必需子目标均被显式覆盖；
- Step、Reason、LLM、Token、时间和成本预算；
- 写操作具备幂等、回查或补偿；
- 高风险动作具备 Human/Policy Gate；
- Validator 完整；
- 输入绑定只能读取允许的 JSON Pointer/Path。

编译失败后最多允许一次基于结构化错误的受限修订；仍失败就澄清、拒绝或转新计划，不能无限修补。

---

## 8. LangGraph 固定 Meta-Executor

核心循环：

```text
SELECT READY STEP
  -> DISPATCH
  -> VALIDATE OUTPUT
  -> LEDGER + CHECKPOINT
  -> NEXT / RETRY / COMPENSATE / INTERRUPT
  -> SELECT READY STEP
```

推荐步骤状态：

```text
PENDING -> READY -> RUNNING -> SUCCEEDED
                         |-> RETRY_WAIT -> RUNNING
                         |-> WAITING_HUMAN -> RUNNING / CANCELLED
                         |-> FAILED -> COMPENSATING -> COMPENSATED / ESCALATED
```

关键运行语义：

- Blueprint、Contract、Tool、Adapter、Validator 和 FSM 都固定版本；
- 运行中发布新版本不影响当前 Run；
- 父图状态只保存小型控制状态、安全摘要、Digest 和 Artifact URI；
- 大文件、完整响应和大型 Trace Body 放对象存储；
- 只对已分类瞬时错误自动重试；
- 业务拒绝、权限错误和 Schema 错误不盲重试；
- 并行只适用于无依赖、无资源冲突、可独立恢复且 Reducer 确定的 Ready Step；
- PoC 优先顺序或小 DAG，先保证正确性再优化并行。

---

## 9. Gap 分型与 System 2

### 9.1 Gap 必须先分型

| Gap | 含义 | 正确处理 |
| --- | --- | --- |
| Value Gap | 动作明确，只缺字段值 | Context/规则/Parser/NER 优先，结构化 LLM 兜底，Schema 校验，仍歧义则 Human |
| Adapter Gap | 已有输出与下游输入不兼容 | 只用注册且测试过的 Adapter；没有则生成 Candidate，当前运行不能执行临时代码 |
| Capability/Logic Gap | 缺少真正能力或新逻辑 | 有界 `reason`，受 Tool、预算、Schema、Validator、ACL 和副作用策略约束 |
| Policy Denied | 权限/策略明确拒绝 | 终止并审计，不是推理问题 |

### 9.2 System 2 的受控运行阶段

1. **Freeze Context**：最小 Task State、固定 Snapshot、Caller ACL、结构化 Evidence；
2. **Classify Gap**：优先规则，小模型兜底；
3. **Build Constraints**：普通代码构建 Tool Allowlist、预算、Output Schema、Validator、Side-effect Policy 和 Human Gate；
4. **Bounded Reason Loop**：Observe -> Select Allowed Tool -> Act -> Update State -> Budget Check；
5. **Verify Output**：Schema -> Evidence -> Business Validator -> Policy Guard -> Ledger；
6. **Outcome Router**：PASS / HUMAN / SAFE STOP / COMPENSATE / ESCALATE。

硬边界：

- 只允许 `CALL_TOOL / FINISH / ASK_HUMAN / ABORT` 等受限动作；
- Action Gateway 在真正调用前重新校验版本、ACL、Schema、风险、预算和幂等；
- 不能创建新 Tool、临时 SQL、任意代码、Jinja 或 Adapter 绕过缺口；
- 不能访问 Allowlist 之外的能力；
- 预算耗尽后不能自动切换更大模型、增加步数或扩大权限；
- PoC 中 Reason Step 默认只读；
- 模型输出不是执行授权，Gateway 和 Validator 才是。

---

## 10. Registry、Experience Base 与数据存储

### 10.1 Experience Base 的三层实现

1. **Experience Evidence Layer**  
   Trace、结构化错误、Validator、Human Feedback、Replay、Token/成本。

2. **Versioned Skill Registry**  
   不可变 Tool/FSM/Skeleton/Adapter/Validator 版本、Contract、状态、ACL、关系和证据链。

3. **Retrieval Projection**  
   Route Header、FTS、Embedding、Capability Graph 所需轻量投影。

### 10.2 推荐物理布局

```text
PostgreSQL
  registry    # 资产、版本、Contract、ACL、关系、Snapshot
  retrieval   # Header、FTS、Embedding 投影
  runtime     # Blueprint、Run、Step、幂等与成本账本
  governance  # Candidate、Patch、Evaluation、Release

S3 / MinIO / Git Artifact Store
  FSM/Tool Body、OpenAPI、Fixture、Replay、报告、大型 Trace

Redis（可选）
  含 tenant + ACL digest + snapshot + query digest 的可失效缓存

LangGraph Checkpointer
  独立 schema/database 保存运行恢复状态
```

PostgreSQL 是 Registry 事实源；对象存储/Git 是大型 Artifact 事实源；FTS、Embedding 和缓存都是可重建投影。

### 10.3 Header/Contract/Body 渐进披露

- 初次召回只读取几十到数百 Token 的 Route Header；
- Top-N 才加载完整 Contract 的必要部分；
- Blueprint 固定引用后，Executor 才加载 Body；
- Header 包含正向/负向触发、输入输出摘要、前置/效果、风险、Scope、可靠度下界和最近评测时间；
- 初步响应不得包含凭据、完整 OpenAPI、FSM Body 或可执行代码。

### 10.4 Snapshot 一致性

- Snapshot 保存当前可见资产的精确版本集合和索引版本；
- 新 Snapshot 先 BUILDING，完整后标记 READY，再原子切换 Head；
- 已开始规划继续使用旧 Snapshot；
- Retrieval、SAD、Rerank、Compiler、System 2 和 Executor 都不能中途重新解析“最新版本”。

---

## 11. 检索、对齐和组合的关键口径

### 11.1 Hard Filter 在语义召回之前

Tenant、ACL、Scope、状态、环境、风险、区域、Runtime/Schema 和 Tool 可用性都应在数据库候选阶段执行。

### 11.2 混合召回

- Sparse：工具名、系统名、错误码、ID、精确业务术语；
- Dense：同义表达、语义目标、前置/完成状态；
- Metadata：领域、租户、环境、风险、发布状态；
- Graph：Dependency、Alternative、Required Validator、Compatible via Adapter；
- RRF：融合排名而不是直接相加 BM25/FTS 与 Cosine 原始分数。

### 11.3 SAD 只做一次反馈式对齐

规则：

- 一个 FSM 能完成整个子目标时，不拆其内部动作；
- 必须由两个独立 Contract 完成时，保留两个子目标；
- 不得删除用户明确要求；
- 未覆盖目标显式标记；
- 输出每个目标的前置状态和完成状态；
- Hint 数和 Top-K 是评测参数，不是固定 15。

### 11.4 Plan Coverage

概念表达：

```text
coverage_i =
  semantic_match
  × precondition_satisfied
  × effect_match
  × schema_compatible
  × policy_allowed
  × reliability_lower_bound
```

Precondition、Schema 或 Policy 等硬失败时覆盖为 0。公式用于表达多因素覆盖思想，具体权重、阈值和聚合方式必须按任务族校准。

---

## 12. 证据驱动的技能演进

### 12.1 生命周期

```text
DRAFT
  -> VALIDATING
  -> SHADOW
  -> CANARY
  -> ACTIVE
  -> DEPRECATED
  -> RETIRED

任一验证、Shadow、Canary 或 Active 监控失败 -> QUARANTINED
QUARANTINED 的修复 -> 新 Draft，而不是原地解锁修改
```

### 12.2 Candidate 不是 Skill

一次成功只说明“这条路径值得分析”，不能说明它：

- 已经泛化；
- 没有 Filled Values；
- 能处理失败与边界；
- 不会越权；
- 不会与已有资产重复；
- 可以安全上线。

### 12.3 Umbrella-First 顺序

1. Exact Duplicate：不新增，只关联新证据；
2. Parameter Variant：扩展参数并产生新版本；
3. Alternative：目标相同但工具、区域、成本、风险或可靠性不同，保留替代实现；
4. Composition：只新增 Skeleton/Blueprint Template，不复制执行体；
5. New Capability：只有新的可验证效果或必要控制结构才创建新 ID。

权限、风险、数据分类或补偿语义不同的资产不能只因文本相似而强制合并。

### 12.4 Patch Protocol

Patch 必须有：

- `base_version`；
- 证据 Trace；
- Patch 类型；
- 变更操作；
- 新增测试；
- 预期指标变化；
- 作者/模型/人工编辑记录。

类型至少区分 Workflow、Semantics、Attachment、Contract、Test。使用乐观锁；冲突后 Rebase 并重跑完整测试。

### 12.5 发布门禁

从低成本到高成本：

1. Static/Contract Lint；
2. Unit/Contract Test；
3. Sandbox Integration；
4. Golden Replay；
5. Production Trace Replay；
6. Property/Metamorphic Test；
7. Security/Adversarial Test；
8. Shadow；
9. Canary；
10. 风险要求下的 Human Approval。

任何越权或严重安全失败均为硬阻断，不能被平均收益抵消。

### 12.6 健康度

至少跟踪：

- Validator Success/Failure、Timeout、Compensation、Human Correction；
- 路由命中后采用率、False Reuse；
- P50/P95 Token、成本和延迟；
- Validator 覆盖率、依赖/Schema 漂移、最近评测时间；
- 按任务族、租户、工具版本和风险分层的结果。

排序使用 Wilson Lower Bound 或 Beta-Binomial 等保守下界，避免小样本 100% 成功率误导。时效衰减用于降权和触发复测，不直接删除。

---

## 13. Token Reduce 的真实目标和账本

单次请求可能包含：

```text
T_run =
  T_normalize
  + T_decompose
  + T_SAD
  + T_rerank
  + T_plan
  + T_extract
  + T_reason
  + T_finalize
```

核心目标：

- 提升 REUSE 占比；
- 减少 HYBRID 中 Reason 的范围和次数；
- 将高频稳定 Reason 路径治理为 FSM；
- 用规则/Parser/NER 替代高频参数抽取；
- 防止库膨胀导致 False Reuse 和 Prompt 成本反弹。

必须记录：

- 各阶段 input/output Token；
- Embedding units；
- LLM/Tool 调用次数；
- Deterministic/Reused Step 数；
- Model/Tool 成本；
- 延迟；
- Validator 结果；
- Human Interrupt；
- 最终是否为 Validated Success。

主要 KPI：

- `cost_per_validated_success`
- `tokens_per_validated_success`
- `reasoning_avoidance_rate`
- `reuse_execution_ratio`
- `validated_task_success_rate`
- `false_reuse_rate`
- `compile_rejection_rate`（合理拒绝是安全能力，不应盲目追求为 0）

长期下降应按相同任务族、风险等级和滑动时间窗口比较，不能承诺每个新请求都单调下降。

---

## 14. 已被后期设计明确修正的早期想法

实现时不要恢复以下旧口径：

| 早期想法 | 当前统一口径 |
| --- | --- |
| 高相似度直接 REUSE | 相似度只做候选排序；由 Plan Coverage + Compiler Gate 决定 |
| 中相似度把整篇旧 Workflow 塞回 Prompt | 对子目标做 HYBRID，已覆盖部分确定执行，只推理未知部分 |
| 一次成功后自动写入经验库并可执行 | 只生成 Candidate/Draft，完整治理后才能 Active |
| 每个请求动态编译临时 LangGraph | 固定 Meta-Executor，把 Blueprint 当数据解释 |
| 40% 未知都做一次参数提取 | 区分 Value、Adapter、Capability/Logic Gap |
| 在线生成 Jinja/Python/Adapter 修类型错 | 只能使用受限绑定和已注册 Adapter |
| Checkpoint 等于 exactly-once | 必须补 Execution Ledger、Idempotency、回查和补偿 |
| 低频/低分技能直接物理删除 | 先降权、复测、Quarantine/Deprecated/Retired，并保护历史引用 |
| 3 个临时 LLM 用例即可决定发布 | Golden、Replay、Property、Security、Shadow、Canary，样本按风险决定 |
| 当前失败后 System 2 顺手修 Active | 当前 Run 不热修；异步产生新版本 |
| 整条复用链 0 Token | 仅确定性执行决策可为 0 LLM Token，整链必须记账 |

---

## 15. 实现顺序

### Phase 0：先建立可验证基础

- 冻结 Contract、Blueprint、错误码、Trace 和 Token Ledger Schema；
- 建立 20-50 个 Golden Tasks 和旧 Agent 基线；
- 为 5-10 个高频、结果可验证的工具/子流程补齐 Validator、ACL、幂等和补偿。

### Phase 1：先证明纯 REUSE

- PostgreSQL Registry MVP；
- READY Snapshot；
- Blueprint Compiler V1；
- 固定 LangGraph Meta-Executor；
- 5-10 个手工审阅 Active FSM；
- Compile -> Run -> Status/Resume；
- 顺序或小型 DAG，不做在线自动修复。

### Phase 2：再处理 60/40

- Header/Body 渐进披露；
- Hard Filter + Sparse + Dense + RRF + 一跳 Graph；
- 一次 SAD；
- Contract Rerank；
- Extract、Human 和只读受限 Reason；
- 分层测 Decompose、Recall、Rerank、Compile、False Reuse 和 Validated Success。

### Phase 3：最后开放受控自进化

- Candidate Distiller；
- Umbrella-First；
- Patch + 乐观锁；
- Golden/Replay/Property/Security；
- Shadow/Canary/Quarantine/Rollback；
- 高风险人工审批工作台。

### Phase 4：有数据后规模化优化

- 专用 Cross-Encoder/Reranker；
- 基于 Accepted Blueprint 的 Composer；
- 更强 Capability Graph；
- 缓存、分片、并行；
- 自动 Adapter 提议但仍走治理门禁；
- 规则/NER 替代高频 LLM 抽取。

研究模型和论文机制是优化项，不是 MVP 正确性的前置依赖。

---

## 16. 后续实现前的快速自检

每个实现方案至少回答：

1. 它属于控制平面、执行平面、Registry/Governance 还是 Tool Runtime？
2. 它处理的是 Value、Adapter、Capability/Logic，还是 Policy 问题？
3. LLM 是在提议，还是被错误地赋予了批准/执行权限？
4. 输入、输出、前置、效果、Validator 和失败模式是否可类型化？
5. 是否固定 Registry Snapshot 和所有资产版本？
6. 是否可能让越权资产进入候选或 Prompt？
7. 外部副作用如何幂等、回查、补偿和审计？
8. Checkpoint 是否只存小状态与 Artifact 引用？
9. 当前 Run 是否与 Candidate/发布链彻底解耦？
10. 失败时是显式 Retry/Clarify/Compensate/Escalate，还是让 LLM 静默改图？
11. Token 优化是否用 Validated Success 作分母？
12. 这个方案是否会随请求次数制造重复 Skill？
13. 所用阈值是否来自真实任务族评测，而不是论文或拍脑袋常量？

若以上问题无法明确回答，方案尚未满足本项目的设计精神。

---

## 17. 当前仍可调整的实现空间

以下选项尚未被设计理念锁死，可以在真实约束下选择：

- Dify 内部具体 Workflow 拆法和 UI；
- PostgreSQL 表字段细节、服务边界和编程语言；
- pgvector 与外部向量服务的切换时机；
- 中文 Sparse 检索使用应用层分词、PG 扩展还是 OpenSearch；
- Embedding、Reranker、Reason Model 的具体型号；
- 每个任务族的 Top-K、SAD Hint 数、Rerank N 和 Coverage 阈值；
- Golden/Replay 样本规模与 Canary 比例；
- FSM Body 采用数据化解释、预注册 LangGraph 子图或两者混合；
- Artifact Store 采用 S3、MinIO、Git 或组合；
- 并行调度、缓存、分片和多租户隔离的具体实现。

选择标准始终是：可验证、可执行、可恢复、可审计、可回滚，并能真实降低单位验证成功成本。

---

## 18. 决策与变更记录

### 2026-07-27：首次统一整理

- 以 `System_Structure.md` 为主要系统设计；
- 用 `database.md` 补齐 Experience/Registry/Projection、Snapshot 和 Retrieval 数据边界；
- 用 `system2.md` 补齐受控推理的内部运行边界；
- 用 `Project.md`、`diff_Fregment.md` 核对工程化修正、实施阶段和验收口径；
- 早期设计保留“Dify + LangGraph、双系统、DAEF + FSM、SAD、技能治理、Token Reduce”的原始意图；
- 明确采纳后期修正：固定 Meta-Executor、不可变 Registry、Candidate 门禁、Gap 分型、Plan Coverage、幂等账本和异步演进。

### 待真实项目数据决定

- 首批业务任务族与 5-10 个种子 FSM；
- 具体 Tool/Identity/ACL 接入方式；
- Contract、Blueprint、Trace 和错误码 Schema 的最终字段；
- 任务族检索与路由阈值；
- PoC 的成功率、成本、延迟和安全 SLO；
- Reason Step 在首版是否完全限制为只读。

