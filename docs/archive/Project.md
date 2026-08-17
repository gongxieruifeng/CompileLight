# Project：Self-Evolving Token Reduce 系统可视化方案与实施说明

> 文档目标：用四张统一风格的架构图说明更新后的整体架构，以及 Q1、Q2、Q3 的详细解决方案、实施路径与最终 Token 目标核验。

---

## 0. 阅读说明

四张图沿用原始架构图的视觉语言，并采用统一语义：

| 视觉元素 | 统一含义 |
| --- | --- |
| 深蓝/蓝色 | Dify 控制平面、检索、规划、编译和同步控制流 |
| 绿色 | 已验证的确定性执行、Active 版本和可安全复用路径 |
| 橙色 | 仍需受控推理、参数抽取、局部未知或 Canary 状态 |
| 紫色 | Trace、候选经验、版本注册表和异步演进闭环 |
| 红色 | 越权、不可执行、隔离、回滚或人工升级 |
| 黑色实线 | 当前请求的同步数据/控制流 |
| 紫色虚线 | 异步 Trace、治理和经验回写 |
| 绿色路径 | 已通过 Contract、Policy 和 Validator 的确定性路径 |
| 橙色路径 | 在预算、工具和输出 Schema 内受控的不确定路径 |

这套系统的核心不是让 LLM “记住更多文本”，而是把重复出现、能够验证的推理过程逐步编译为**有版本、有契约、可确定执行的程序资产**。

---

## 1. 更新后的总体架构图

![更新后的 Self-Evolving Token Reduce 总体架构](assets/token_reduce_updated_architecture.png)

### 1.1 图中主流程

总体架构被拆成四个明确区域：

1. **Dify Control Plane**：负责理解任务、检索能力、生成候选计划和选择执行模式。
2. **Versioned Skill Registry**：保存可检索 Header、完整 Contract、能力关系图和可复现的 Registry Snapshot。
3. **LangGraph Execution Plane**：运行一张固定的元解释器图，根据已编译 Blueprint 确定性调度 FSM、Tool、Extractor、Adapter、Reason 和 Human 节点。
4. **Evidence-Driven Evolution Loop**：把执行结果转为 Candidate，经 Patch、测试、Shadow 和 Canary 后才允许发布新 Active 版本。

一次请求的同步路径如下：

```text
User/API
  -> Task Normalizer
  -> Capability Retrieval
  -> SAD Alignment
  -> Plan Proposer
  -> Blueprint Compiler
  -> Mode Router(REUSE / HYBRID / NEW)
  -> LangGraph Fixed Meta-Executor
  -> Validator + Policy Guard
  -> Validated Result
```

异步演进路径如下：

```text
Execution Trace
  -> Candidate Distiller
  -> Typed Patch
  -> Compile + Test
  -> Shadow
  -> Canary
  -> Active Version
  -> Registry Snapshot
```

同步路径解决当前任务，异步路径只负责产生未来可复用资产。两条路径必须解耦：当前请求失败时可以触发修复建议，但不能原地修改当前正在执行的 Active 版本。

### 1.2 Dify 控制平面的六个组件

#### 1. Task Normalizer

它把自然语言请求转为规划所需的结构化上下文：

- 用户身份、租户、角色与权限；
- 任务目标和验收条件；
- 业务实体、时间、金额、对象 ID；
- 数据分类和风险等级；
- 当前环境与可用工具；
- 对歧义参数的澄清需求。

Normalizer 不负责制定工具调用序列。它只把“用户说了什么”转为“系统必须满足什么”。

#### 2. Capability Retrieval

它从 Registry 的 Route Header 中召回候选能力，而不是直接读取所有技能执行体。召回信号包括：

- Sparse/BM25：工具名、系统名、错误码、业务术语；
- Dense Vector：语义相似子目标；
- Metadata：租户、环境、风险、领域、状态；
- Capability Graph：前置依赖、兼容、替代、验证器与 Adapter。

只有进入最终候选集的资产才加载完整 Contract；只有被 Blueprint 固定引用的资产才加载执行体。

#### 3. SAD Alignment

SAD 采用一次反馈式拆解：

1. 第一次按任务语义粗拆子目标；
2. 用粗拆结果检索实际存在的能力 Header；
3. 将 Header 作为“可用能力词表”；
4. 第二次调整边界，避免过度拆解或欠拆解；
5. 保留所有未覆盖目标，禁止为了匹配库中能力而删除用户需求。

SAD 默认只迭代一次。再次无法对齐时转 System 2 或人工澄清，不能进入无限拆解循环。

#### 4. Plan Proposer

Plan Proposer 可以由 LLM 实现，但它只能：

- 从当前 Registry Snapshot 中选择可见的固定版本资产；
- 使用已定义的 Step 类型；
- 输出结构化 Blueprint；
- 对未覆盖目标显式使用 `reason`、`extract` 或 `human`；
- 给出输入绑定、依赖和期望输出 Schema。

它只能“提议计划”，没有最终执行权。

#### 5. Blueprint Compiler

Compiler 是普通确定性代码，负责：

- JSON Schema；
- Step/Dependency/DAG；
- 输入输出类型；
- ACL、租户和风险；
- 版本可见性；
- 最大步数、LLM、时间和成本预算；
- 写操作幂等与补偿；
- Validator 和人工 Gate；
- Secret/数据跨租户访问；
- 受控循环的最大迭代次数。

Compiler 未通过的 Blueprint 不允许进入 LangGraph。LLM 最多根据结构化错误修复一次，仍然失败则进入 NEW、澄清或拒绝。

#### 6. Mode Router

Router 不再依据单一向量分数决定路径：

| 模式 | 条件 | 行为 |
| --- | --- | --- |
| `REUSE` | 所有必需子目标都有通过 Contract 的确定性路径 | 执行阶段不逐步调用 LLM 做决策 |
| `HYBRID` | 部分目标可复用，未知部分在风险和预算内可控 | 只对未知 Step 使用抽取、受限 Reason 或 Human |
| `NEW / CLARIFY` | 无安全路径、关键参数歧义、越权或风险过高 | 完整 System 2、询问用户或拒绝执行 |

### 1.3 LangGraph 执行平面

LangGraph 不为每次请求重新编译一张临时图，而是运行固定 Meta-Executor：

```text
SELECT READY STEP
  -> DISPATCH
  -> VALIDATE OUTPUT
  -> LEDGER + CHECKPOINT
  -> NEXT / COMPENSATE
  -> SELECT READY STEP
```

支持的执行器类型：

- `FSM`：版本固定的原子状态机子图；
- `TOOL`：单一注册工具；
- `EXTRACT`：规则/NER/结构化 LLM 参数抽取；
- `ADAPTER`：已注册、已测试的 Schema 转换；
- `REASON`：受限工具、受限步数、受限 Token 的 System 2；
- `HUMAN`：审批、补充输入或高风险确认。

每个 Step 都必须完成：

1. 读取版本固定的 Contract；
2. 校验前置条件；
3. 检查 Execution Ledger，防止重复副作用；
4. 执行；
5. 校验 Output Schema 和业务 Validator；
6. 写入 Step 状态、成本、错误和 Artifact 引用；
7. 推进、重试、补偿或暂停。

Checkpoint 解决“恢复到哪里”，Execution Ledger 和 Idempotency Key 解决“外部写操作是否已经发生”。二者缺一不可。

### 1.4 Registry 与数据存储

推荐实现：

```text
PostgreSQL
  ├── skill / skill_version
  ├── route_header + tsvector + embedding
  ├── skill_contract
  ├── capability_edge
  ├── validator / adapter
  ├── blueprint / registry_snapshot
  ├── execution_run / execution_step
  └── patch / evaluation / release

Object Storage or Git Artifact Store
  ├── large execution bodies
  ├── test fixtures
  ├── replay data
  └── reports and immutable artifacts
```

PostgreSQL 是事实源；向量、全文检索和缓存是可重建索引。Dify 知识库可以作为知识入口，但不承担版本发布、依赖事务和执行账本的唯一事实源。

### 1.5 总体实施路径

| 阶段 | 首要交付 | 系统能力 |
| --- | --- | --- |
| Phase 0 | Contract、Blueprint、Validator、Trace、Token 基线 | 能测量、能判定结果是否正确 |
| Phase 1 | Registry MVP、固定 Meta-Executor、纯 REUSE | 高频重复任务确定性执行 |
| Phase 2 | Hybrid Retrieval、SAD、Rerank、HYBRID | 处理 60/40 部分匹配任务 |
| Phase 3 | Candidate、Patch、测试、Shadow、Canary | 受控自进化和安全回滚 |
| Phase 4 | 专用 Reranker、组合模型、并行与缓存 | 规模化降低成本和延迟 |

总体架构可以工程实现，原因是关键正确性不依赖某个未成熟研究模型：MVP 可由 PostgreSQL、Dify、LangGraph、JSON Schema、普通编译校验代码和现有工具 API 组成；论文方法只用于优化检索、拆解和候选生成。

---

## 2. Q1：部分匹配任务的组合方案

![Q1：60/40 部分匹配与安全混合执行](assets/q1_partial_match_composition.png)

### 2.1 Q1 的本质

Q1 不是“相似度达到 60% 后怎样调用旧 Workflow”，而是：

- 当前任务包含哪些必须完成的子目标；
- 哪些目标已有通过验证的执行资产；
- 哪些目标只缺参数，哪些缺 Adapter，哪些缺真正能力；
- 复用资产与未知步骤能否形成一个可编译、可验证、可恢复的执行计划。

因此，60/40 是覆盖关系，不是一个固定的向量分数。

### 2.2 六步规划流程

#### Step 1：Task Normalize

得到任务目标、上下文、约束和验收条件。例如：

```text
目标 1：从服务器日志获得经过验证的错误事实
目标 2：创建符合团队规范的 Jira 工单
目标 3：向授权团队发送通知
```

#### Step 2：Hybrid Retrieval

按每个目标召回 FSM、Tool、Adapter 和 Validator。此时只读取轻量 Route Header，避免把几百个完整执行体塞进 Prompt。

#### Step 3：SAD Alignment

根据实际能力调整粒度。例如库里已有完整 `http_fetch` 时，不把“连接、请求、落盘”当成三个子技能；如果“下载”和“解析 CSV”确实由两个独立 Contract 完成，则保留两个子目标。

#### Step 4：Plan Proposer

将候选能力组合为 Blueprint。Plan Proposer 必须显式标记：

- 哪些 Step 是 `fsm`；
- 哪些是 `extract`；
- 哪些是 `adapter`；
- 哪些是 `reason`；
- 哪些需要 `human`；
- 每个 Step 的固定版本、依赖和输出 Schema。

#### Step 5：Blueprint Compiler

执行图中六类核心门禁：

| Gate | 核验内容 |
| --- | --- |
| Schema | Blueprint 结构和每个 Step 的输入输出是否合法 |
| Type | 上游 Artifact 是否能满足下游输入 |
| ACL | 用户、租户和服务身份是否有调用权限 |
| Budget | 步数、Reason 次数、Token、时间和成本是否超限 |
| Version | Skill/Tool/Validator 是否来自同一可见 Snapshot |
| Idempotency | 外部写操作是否有幂等、回查或补偿 |

#### Step 6：Execution Mode

Compiler 通过后，Router 才能决定 REUSE、HYBRID 或 NEW。模式是编译结果的产物，不是仅由 LLM 主观判断。

### 2.3 60% 可复用路径

绿色区域中的 `FSM A@1.3`、`FSM B@2.1` 表示版本固定的可执行子图。它们具有：

- 明确输入 Schema；
- 前置条件和完成条件；
- 固定 Tool 依赖；
- Validator；
- Retry/Timeout；
- Idempotency/Compensation；
- 权限和数据分类；
- 测试与发布证据。

执行阶段不再逐步询问 LLM“下一步做什么”。如果一个 FSM 内部只包含确定工具调用、条件判断和参数绑定，它的**步骤决策 Token 为 0**。

### 2.4 40% 缺口必须分型

#### Value Gap

示例：用户说“明天下午请假”，缺少 ISO 时间。

处理顺序：

1. 会话/业务上下文直接取值；
2. 规则、日期解析、正则或 NER；
3. 一次结构化 LLM 抽取；
4. JSON Schema 和业务规则验证；
5. 仍有歧义则 Human Interrupt。

参数抽取不能决定新的业务动作，也不能猜测审批人、收件人、支付金额等高风险参数。

#### Adapter Gap

示例：上游输出 `{ticket_url}`，下游要求 `{message: {text}}`。

只能使用已注册 Adapter。Adapter 也必须有：

- 源/目标 Schema；
- 版本和 Digest；
- 单元测试和边界测试；
- 无副作用声明；
- 失败错误码。

线上不能让 LLM 临时生成任意 Python/Jinja 表达式绕过类型错误。

#### Capability Gap

示例：需要从一个从未接入的新日志系统读取并判断故障。

使用受限 Reason 节点：

- 只允许调用 Blueprint 列出的工具；
- 最大步数和最大 Token；
- 输入、输出 Schema；
- 强制 Validator；
- 高风险动作必须人工；
- 失败后不能静默扩展工具权限。

多次成功的 Capability Gap 可以成为候选经验，但必须走 Q2 的完整生命周期，不能自动变成 Active。

### 2.5 固定 Meta-Executor 的执行方式

元解释器维护如下步骤状态：

```text
PENDING -> READY -> RUNNING -> SUCCEEDED
                         |-> RETRY_WAIT -> RUNNING
                         |-> WAITING_HUMAN -> RUNNING / CANCELLED
                         |-> FAILED -> COMPENSATING -> COMPENSATED / ESCALATED
```

执行逻辑：

1. 选择依赖均成功的 Ready Step；
2. 加载 Blueprint 固定的 `asset_ref`；
3. 渲染受限 JSON Pointer 参数绑定；
4. 检查 Step Idempotency Key；
5. 执行；
6. Validator 检查真实结果，而不是只看 API 返回 200；
7. 写 Ledger 和 Checkpoint；
8. 推进下一 Step；
9. 失败时按错误类别重试、补偿或人工升级。

### 2.6 Q1 实施步骤

1. 先选择 5-10 个高频、结果可验证的业务子流程。
2. 将每个子流程改造成版本化 FSM Contract。
3. 开发 Blueprint Schema 和 Compiler V1。
4. 开发固定 LangGraph Meta-Executor，只支持顺序执行和小型 DAG。
5. 接入 Execution Ledger、幂等和 Checkpoint。
6. 增加 `extract` 和 `human`，最后再开放受限 `reason`。
7. 以 20-50 个 Golden Tasks 测 REUSE 和 HYBRID。
8. 通过后再扩大技能与工具范围。

### 2.7 Q1 验收条件

- 100% 拒绝 Schema 非法、越权、环路和类型不兼容 Blueprint；
- 运行中发布新版本不会改变当前 Blueprint；
- 故障恢复测试不产生重复工单、邮件或审批；
- 复用 Step 的执行决策不调用 LLM；
- Capability Gap 不能访问 Blueprint 之外的工具；
- 每个成功结果都有 Validator 证据；
- 无法安全组合时能够明确转 NEW/Clarify，而不是“尽量执行”。

**Q1 结论：已在架构层解决。**部分匹配不再依赖黑盒 Workflow 复用，而是由原子 FSM、缺口分型、类型化 Blueprint 和固定 Meta-Executor 组成安全混合计划。

---

## 3. Q2：技能库长期治理方案

![Q2：版本化、测试门禁和可回滚的技能生命周期](assets/q2_skill_lifecycle_governance.png)

### 3.1 Q2 的本质

技能库增长后的主要问题不是单纯存储量，而是技术债：

- 重复能力挤占检索候选；
- 特定任务 Filled Values 被写死；
- 工具 API 变化造成接口漂移；
- 缺少 Validator 的技能被误判成功；
- LLM Patch 造成负迁移；
- 旧 Blueprint 依赖的版本被直接删除；
- 高调用率并不等于高效用；
- 修复 Agent 与在线 Agent 相互覆盖。

因此，Q2 的解决方案必须把技能库当成软件制品库，而不是可自由编辑的文档集合。

### 3.2 三类证据输入

#### Execution Trace

保存：

- Step、工具、固定版本和运行环境；
- 结构化输入输出摘要；
- Artifact 引用；
- Token、延迟和成本；
- Validator 和完成状态；
- 用户/任务族/租户的脱敏上下文。

默认不保存完整思维链，只保存动作证据、结构化理由码和结果。

#### Failure + Validator

失败证据包括：

- 工具错误码；
- Schema/Contract 错误；
- Validator 失败；
- 超时后副作用未知；
- 补偿失败；
- 误路由和人工纠正；
- 重放与实际结果差异。

失败轨迹与成功轨迹同等重要，因为它们决定边界条件和已知 Failure Mode。

#### Human Feedback

人工反馈分为：

- 业务结果纠正；
- 参数/权限纠正；
- 安全审批；
- Merge/Alternative 判断；
- 高风险 Patch 审批；
- Golden Case 和验收规则维护。

### 3.3 类型化 Patch Protocol

Patch 必须指定 `base_version`、证据 Trace 和变更类型：

| Patch 类型 | 允许修改 |
| --- | --- |
| Workflow | 节点、边、显式分支、循环、审批和补偿 |
| Semantics | 前置/后置、Predicate、本地 Retry、接受/拒绝条件 |
| Attachment | 工具绑定、配置、模板、资源、Secret Ref |
| Contract | 输入输出 Schema、权限、风险、数据分类和效果 |
| Test | Validator、Golden、Replay、Property 和 Security Test |

Patch 永远产生新版本。`base_version` 使用乐观锁：如果目标已经被其他 Patch 升级，当前 Patch 必须 Rebase 后重新执行全部测试。

生成 Patch 的模型不能单独担任最终 Judge。高风险变更必须由不同评测过程和人工审批决定。

### 3.4 Umbrella-First 判定顺序

新增 Candidate 时按图中五类处理：

1. **Exact Duplicate**：执行图、Contract 和 Digest 相同，拒绝新增，仅关联新证据。
2. **Parameter Variant**：逻辑相同、常量不同，扩展已有参数并生成新版本。
3. **Alternative**：目标相同但工具、地区、成本或可靠性不同，保留两个实现并建立替代边。
4. **Composition**：Candidate 只是多个现有技能的固定组合，新增 Skeleton/Blueprint Template，不复制执行体。
5. **New Capability**：具有新的可验证效果或必要控制结构，才创建新 `skill_id`。

语义相似但权限、风险、数据分类或补偿语义不同的技能不能强制合并。

### 3.5 生命周期状态

```text
DRAFT
  -> VALIDATING
  -> SHADOW
  -> CANARY
  -> ACTIVE
  -> DEPRECATED
  -> RETIRED
```

任一验证、Shadow、Canary 或 Active 监控失败都可进入 `QUARANTINED`。修复方式是从隔离版本生成新的 Draft，不是解除锁后直接修改原版本。

状态定义：

| 状态 | 是否参与新规划 | 是否可执行 | 说明 |
| --- | --- | --- | --- |
| Draft | 否 | 仅测试 | 候选与 Patch 工作区 |
| Validating | 否 | 沙箱 | 静态、Contract、集成和回放测试 |
| Shadow | 否 | 无真实副作用 | 与 Active 对比计划或结果 |
| Canary | 小流量 | 受限 | 隔离租户/审批/小流量验证 |
| Active | 是 | 是 | 不可变正式版本 |
| Deprecated | 不进入新规划 | 允许旧 Run/兼容期 | 有替代版本 |
| Quarantined | 否 | 默认禁止 | 安全或质量隔离 |
| Retired | 否 | 否 | 保留审计，等待引用与保留期清理 |

### 3.6 质量门禁

图中门禁从低成本到高成本排列：

1. Static + Contract；
2. Sandbox Integration；
3. Golden Replay；
4. Property + Security；
5. Shadow Comparison；
6. Human Approval。

具体测试内容：

- 合法/非法输入；
- 输出 Schema；
- 已知失败模式；
- 429、5xx、超时、部分成功；
- 幂等重放；
- 日期、时区、空值和极值；
- Prompt Injection、越权租户和 Secret 泄漏；
- 补偿成功与补偿失败；
- 新旧版本在真实脱敏 Trace 上的差异。

不能只让 LLM 临时生成 3 个用例然后根据 1% 差异发布。样本数、业务分层和置信区间应由风险等级决定。

### 3.7 健康信号

每个技能至少记录：

- 成功、Validator 失败、超时、补偿和人工纠正；
- 路由命中后采用率；
- False Reuse；
- P50/P95 Token、延迟和成本；
- 最近验证日期与依赖版本；
- Validator 覆盖率；
- Schema/工具漂移；
- 任务族、租户和风险分层结果。

排序使用 Wilson Lower Bound 或 Beta-Binomial 后验下界，不让两次成功的技能以 100% 成功率压过运行数百次的稳定技能。

时效衰减用于降权和触发复测，不直接删除。低频技能可能是低频但关键的应急能力。

### 3.8 Versioned Skill Registry

Registry 需要保存：

- 不可变版本和 Artifact Digest；
- dependency、compatibility、alternative、redundancy、version 边；
- 一次规划的一致 Snapshot；
- Tenant ACL 和 Required Scope；
- Tool/Validator/Adapter 固定版本；
- Patch、Test、Release 和回滚记录。

四条不可妥协规则：

1. 不直接修改 Active；
2. 有历史引用时不物理删除；
3. 高风险变更必须人工；
4. Canary/Active 退化时回滚到上一 Active。

### 3.9 Q2 实施步骤

1. 将现有技能注册为稳定 `skill_id` 与不可变版本。
2. 定义 Draft/Active/Deprecated/Quarantined 等状态和 ACL。
3. 增加 Artifact Digest、Owner、Provenance 和 Test Suite。
4. 实现 Exact Duplicate 和 Contract/Graph 判重。
5. 实现 Patch Proposal 与乐观锁。
6. 建立 Golden、Replay、Property、Security Test。
7. 增加 Shadow 和 Canary 发布器。
8. 增加依赖图影响分析和一键回滚。
9. 最后才允许自动生成低风险 Patch Candidate。

### 3.10 Q2 验收条件

- 自动生成内容不能绕过 Draft；
- Active 版本修改次数为 0；
- 每个版本都能追溯到证据、测试、作者和 Digest；
- 发布冲突能够被 `base_version` 检测；
- Canary 失败能停止新流量并回滚；
- Deprecated/Retired 不破坏旧 Blueprint 审计与恢复；
- 高风险 Patch 无人工审批不能 Active；
- 库规模增长时 False Reuse 和检索质量不持续恶化。

**Q2 结论：已在架构层解决。**技能库从“文档堆”升级为版本化、测试门禁、可回滚的资产生态，膨胀、失效和自动修复污染均有明确控制点。

---

## 4. Q3：结构感知的检索、拆解与组合方案

![Q3：结构感知的 Skill Retrieval、SAD 与任务状态图](assets/q3_structure_aware_retrieval.png)

### 4.1 Q3 的本质

Q3 的根因包括：

- 用户请求粒度与库中技能粒度不同；
- 文本相似但前置条件不同；
- 候选技能输出不能满足下游输入；
- 只按 Top-K 返回固定数量技能；
- 库越大，完整技能正文占用的 Prompt 越多；
- 向量分数高但权限、环境或版本不可用。

因此需要把检索分成：硬过滤、召回、SAD 对齐、Contract 重排、状态图组合和 Blueprint 编译。

### 4.2 Hard Filter 必须先于语义检索

过滤维度：

- Tenant；
- ACL/Required Scope；
- Active/Canary 可见状态；
- 风险等级；
- 当前环境与工具可用性；
- Schema/Runtime 兼容版本；
- 数据区域和合规要求。

越权技能不应先被向量召回再依赖 LLM 自觉不选，而应在数据库查询阶段不可见。

### 4.3 Pass-1 Decompose

第一次拆解只追求最少数量的有意义子目标，并输出期望状态：

```json
{
  "subgoals": [
    {
      "goal": "读取服务器日志并获得错误事实",
      "expected_state": "错误事实已结构化且通过验证"
    },
    {
      "goal": "创建 Jira 工单",
      "expected_state": "工单已存在且字段符合团队模板"
    },
    {
      "goal": "通知团队",
      "expected_state": "授权接收方已收到工单链接"
    }
  ]
}
```

### 4.4 Hybrid Retrieve

四个召回通道并行：

| 通道 | 强项 | 示例 |
| --- | --- | --- |
| Sparse/BM25 | 精确词、工具、错误码、产品名 | Jira、IT-8899、WeCom |
| Dense/Vector | 同义表达和语义目标 | “提醒团队”与“发送企业消息” |
| Metadata | 领域、租户、风险、状态、环境 | IT Support、Active、Prod |
| Graph Expansion | 依赖、替代、Validator、Adapter | create-ticket -> notify |

不同通道的原始分数不可直接相加。采用 Reciprocal Rank Fusion：

```text
RRF(d) = Σ 1 / (k + rank_i(d))
```

这样融合的是排名而不是不可比的 BM25/Cosine 数值。

### 4.5 SAD Hinting 与 Pass-2 Align

系统只把候选 Route Header 和 Contract 摘要作为 Hint，不加载执行代码。

Pass-2 规则：

- 一个现有 FSM 能完成整个子目标时，不拆它的内部实现；
- 两个独立 Contract 才能完成时，保留两个子目标；
- 不得删除用户明确目标；
- 不能覆盖的目标标记 `uncovered=true`；
- 每个目标输出前置状态和完成状态。

图中的三个对齐目标为：

1. Verified Error Fact；
2. Ticket Created；
3. Team Notified。

### 4.6 Contract Rerank

重排不只看描述，而是看五类可执行证据：

1. **Goal**：技能效果是否满足子目标；
2. **Precondition**：当前状态是否可调用；
3. **Effect**：完成后产生什么业务状态和副作用；
4. **Schema**：输入输出是否可连接；
5. **Reliability**：在相同任务族/环境中的保守可靠度下界。

Cross-Encoder 或小模型只用于 Top-N 候选，避免在全库执行高成本重排。

### 4.7 Task-State Execution Graph

图中把任务中间状态作为节点、技能作为边：

```text
STATE 0
  -> fsm.log.read@2.0
  -> STATE 1: verified error fact
  -> fsm.jira.create@1.3
  -> STATE 2: ticket created
  -> fsm.wecom.notify@2.1
  -> GOAL
```

每条边要求：

- 当前 State 满足 Skill Precondition；
- Skill Output/Effect 产生下一个 State；
- Output Type 与下一技能 Input Type 兼容；
- Validator 能证明状态已经达到。

当 `fsm.log.read` 不存在时，系统不伪造匹配，而是建立橙色分支：

```text
STATE 0 -> BOUNDED REASON -> VALIDATOR -> STATE 1
```

只有 Validator 通过，未知路径才能重新接入确定性链。

### 4.8 Plan Coverage 与模式判定

每个子目标的覆盖不只由语义分数决定：

```text
coverage_i = semantic_match
             × precondition_satisfied
             × effect_match
             × schema_compatible
             × policy_allowed
             × reliability_lower_bound
```

前置条件、Schema 或 Policy 任一硬失败时，该目标覆盖为 0。

- 所有必需目标有安全路径：REUSE；
- 部分目标有安全路径，未知部分可受控：HYBRID；
- 关键目标无路径、越权、缺 Validator 或编译失败：NEW/Clarify。

阈值必须按任务族在标注集上校准，不能把 `0.7/0.95` 当成跨模型、跨数据集的固定真理。

### 4.9 PostgreSQL Skill Registry

图中底部五类数据：

1. Route Headers；
2. Versioned Contracts；
3. Capability Graph；
4. Registry Snapshot；
5. FTS + pgvector Index。

索引可重建，资产事实不可丢。一次规划固定一个 Snapshot，防止检索、重排和执行期间 Active 集合发生变化。

### 4.10 分阶段评测

Q3 不能只看最终任务成功率，需要测每一层：

| 阶段 | 指标 | 失败含义 |
| --- | --- | --- |
| Decompose | Granularity/Decomposition Accuracy | 子目标切错 |
| Retrieve | Recall@K | 正确技能未进入候选集 |
| Rerank | Top-1/MRR/NDCG | 候选存在但排序错误 |
| Compose | Blueprint Compile Pass Rate | 接口、依赖或策略无法形成计划 |
| Execute | Validated Task Success | 工具/业务运行失败 |
| Safety | False Reuse Rate | 系统误把不适用经验当作可复用 |

### 4.11 Q3 实施步骤

1. 从 Registry 拆出 Route Header 与完整 Contract。
2. PostgreSQL 增加 FTS/pgvector 和 Metadata 索引。
3. 先实现 Hard Filter 与 RRF。
4. 建立带正确技能链的标注任务集。
5. 实现 Pass-1、Hint Retrieval 和一次 Pass-2 SAD。
6. 实现 Contract Rerank。
7. 用 Plan Proposer 生成 1-3 个受限候选 Blueprint。
8. Compiler 选择最短、风险最低的可执行候选。
9. 分层记录 Decompose、Recall、Rerank、Compile 和 False Reuse。
10. 数据积累后再训练专用 Reranker 或 Skill Composer。

### 4.12 Q3 验收条件

- 越权/不可见资产不会进入候选集；
- 过度拆解和欠拆解在 SAD 后得到明显改善；
- 正确技能的 Recall@K 达到任务族上线目标；
- Contract Rerank 优于只看 Description 的检索；
- 类型不兼容时 Compiler 拒绝或使用注册 Adapter；
- 未覆盖子目标不会被忽略；
- 库扩大时前台 Prompt 只按候选数量增长，不随完整技能库线性增长；
- False Reuse 保持在风险等级允许范围内。

**Q3 结论：已在架构层解决。**系统通过任务状态、Contract 和能力图建立“拆解—检索—重排—组合”的可测链路，能够区分粒度错误、召回错误、接口错误和执行错误。

---

## 5. 最终目标核验：Token 是否会随系统使用逐步降低

### 5.1 Token 成本组成

单次请求的模型 Token 可分解为：

```text
T_run = T_normalize
      + T_decompose
      + T_SAD
      + T_rerank
      + T_plan
      + T_extract
      + T_reason
      + T_finalize
```

确定性 FSM、Tool、Adapter、Validator 和普通控制流本身不需要 LLM Token，但以下项目仍可能产生成本：

- Embedding 服务的输入计量；
- 轻量任务路由/拆解；
- SAD 第二次对齐；
- 结构化参数抽取；
- HYBRID 未知部分的受限 Reason；
- 最终自然语言结果整理。

因此，正确的目标不是“整条链永远 0 Token”，而是：

> 随着高质量 Active 能力覆盖率增加，逐步降低每次验证成功任务所需的推理 Token 和 LLM 调用次数。

### 5.2 为什么预期成本会下降

设第 `n` 个时间窗口中：

- `p_R(n)`：REUSE 请求占比；
- `p_H(n)`：HYBRID 请求占比；
- `p_N(n)`：NEW 请求占比；
- `T_R < T_H < T_N`：三类请求的平均 Token。

则：

```text
E[T(n)] = p_R(n) × T_R
        + p_H(n) × T_H
        + p_N(n) × T_N
```

系统长期运行后，只要满足以下条件：

1. 重复任务族具有稳定分布；
2. 成功的未知步骤经过 Q2 门禁转为 Active FSM；
3. 检索与 Q3 组合能找到这些 FSM；
4. 技能库没有因膨胀和失效导致 False Reuse 上升；
5. 高价值参数抽取逐步被规则/NER 替代；

那么 `p_R(n)` 会增加，`p_N(n)` 和每个 HYBRID 请求的 `T_reason` 会下降，最终 `E[T(n)]` 与 `cost_per_validated_success` 下降。

### 5.3 不是每个请求都单调下降

系统不能承诺任何时间点、任何请求都比上一次便宜：

- 新业务或新工具会进入 NEW；
- 任务组合更复杂时 Token 会增加；
- 安全澄清和人工审批不能为了省 Token 被跳过；
- 模型/Embedding 计价会变化；
- 任务分布发生漂移时 REUSE 比例可能暂时下降；
- Shadow/Canary 和离线治理本身有额外成本。

所以最终目标应按**相同任务族、相同风险等级、滑动时间窗口**核验，而不是比较两个随机请求。

### 5.4 必须记录的 Token 账本

```text
router_input_tokens / router_output_tokens
decompose_tokens / sad_tokens / rerank_tokens
plan_tokens / extractor_tokens / reason_tokens
finalizer_tokens / embedding_units
llm_call_count
reused_deterministic_steps / all_steps
tool_call_count
model_cost / tool_cost / total_latency
validated_success
```

主要 KPI：

- `cost_per_validated_success`；
- `tokens_per_validated_success`；
- `reasoning_avoidance_rate`；
- `reuse_execution_ratio`；
- `false_reuse_rate`；
- `validated_task_success_rate`；
- P50/P95 Token、成本和延迟。

### 5.5 推荐的 PoC Go/No-Go 门槛

以下是建议的初始目标，正式数值应在 Phase 0 基线后确认：

| 场景 | 建议目标 |
| --- | --- |
| REUSE 重复任务 | 相对旧 Agent 的 LLM Token 降低至少 70%；确定性执行阶段不调用决策 LLM |
| HYBRID 部分匹配任务 | 相对旧 REFERENCE 分支 Token 降低至少 30% |
| 正确性 | Validated Success 不低于基线超过允许的非劣效边界 |
| 安全 | 越权调用、未编译 Blueprint、重复不可逆副作用均为 0 |
| 可靠性 | P95 延迟和错误率满足任务族 SLO |
| 长期趋势 | 同任务族 30 天移动平均 `cost_per_validated_success` 下降或稳定，不因库规模增长恶化 |

Token 下降不能用降低成功率换取。最终比较必须使用“每个验证成功任务”的成本。

### 5.6 四个目标的最终核验矩阵

| 目标 | 是否已解决 | 解决机制 | 生产验证 |
| --- | --- | --- | --- |
| Q1：60/40 部分匹配组合 | 是，架构层已闭环 | 原子 FSM、缺口分型、Blueprint Compiler、固定 Meta-Executor、Validator | REUSE/HYBRID Golden Set、故障注入、幂等与回退测试 |
| Q2：技能膨胀与长期退化 | 是，治理层已闭环 | Umbrella-First、不可变版本、Patch、质量门禁、Shadow/Canary、Quarantine/Rollback | 版本审计、回放、发布冲突、安全测试、规模增长测试 |
| Q3：粒度错配与精确检索 | 是，检索层已闭环 | Hard Filter、Hybrid/RRF、SAD、Contract Rerank、任务状态图、Plan Coverage | Decomposition、Recall@K、Top-1、Compile Pass、False Reuse |
| 最终目标：Token 逐步降低 | 架构机制已具备，效果需上线度量确认 | 提升 REUSE/HYBRID 覆盖，减少逐步推理，渐进披露，规则替代抽取，治理防膨胀 | Token 账本、同任务族 A/B、30 天移动平均、成本/成功率联合 SLO |

### 5.7 最终判定

**Q1、Q2、Q3 在设计层面均已形成无明显逻辑冲突、可以工程落地的闭环。**

最终 Token 目标不是依赖“经验越多自然越省”这一假设，而是由四个可执行机制共同保证方向：

1. Q1 让已覆盖步骤从逐轮推理变为确定性执行；
2. Q2 只允许有效、可验证的技能进入 Active，避免库增长反而降低复用质量；
3. Q3 让系统能实际找到并正确组合已有能力；
4. Token 账本用真实数据验证成本是否随着复用覆盖率提高而下降。

因此，最终结论为：

- **工程可实现性：成立。**
- **重复任务上的 Token 显著下降：具备直接机制，可在 Phase 1 验证。**
- **60/40 任务上的 Token 下降：具备直接机制，可在 Phase 2 验证。**
- **长期总体成本逐步降低：在任务分布存在重复性、治理门禁有效、检索质量达标时成立；必须通过持续指标确认，不能仅凭论文或架构图宣称已经产生实际数值。**

---

## 6. 建议的下一步工程顺序

1. 冻结 Skill Contract、Blueprint、错误码和 Trace Schema。
2. 建立 20-50 个 Golden Tasks 和旧 Agent Token/成功率基线。
3. 手工选择 5-10 个稳定 FSM，完成 Validator、幂等和权限契约。
4. 实现 Registry MVP、Blueprint Compiler 和固定 LangGraph Meta-Executor。
5. 先上线纯 REUSE Shadow，再开放真实低风险流量。
6. 接入 Hybrid Retrieval、SAD、Contract Rerank 和 HYBRID。
7. 形成 Candidate、Patch、Shadow、Canary 与回滚工作台。
8. 持续看 `cost_per_validated_success`，再决定是否训练专用 Reranker 或 Skill Composer。

这一路径确保先证明“确定性复用是否真的正确和省 Token”，再增加自动演进复杂度。

