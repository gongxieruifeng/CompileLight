# ReduceTokenAgent 全局实现指导与进度快照

> 适用范围：`ReduceTokenAgent/` 目录及其所有子目录  
> 文档角色：后续代码实现的全局约束、设计决策、验收口径和进度唯一快照  
> 当前状态：三个domain的能力闭环、Control Plane、LangGraph和System2已完成；Robot Nexus DM已完成DM-05至DM-14，Gradio/API/CLI支持Direct与Blueprint DM多轮等待、callback和同dialog恢复；UI已提供Robot 353真实能力演示  
> 最后更新：2026-08-14

---

## 1. 文档优先级

后续开发、评审和重构必须按以下顺序理解需求：

1. 用户最新明确要求；
2. 本文件中的 PoC 实现约束和当前进度；
3. `PROJECT_STRUCTURE.md` 中的组件边界与目录设计；
4. 上级目录的 `../DESIGN_MEMORY.md`；
5. 上级目录其他设计和研究文档。

本项目是 `DESIGN_MEMORY.md` 的**本地小规模验证实现**，不是一次性实现完整生产架构。若宏观设计与 PoC 的简化规则冲突，优先保留设计意图，再采用本文件明确记录的简化方式。

---

## 2. 当前目标

在一台本地开发机上，用少量测试任务和少量能力资产验证以下核心假设：

1. 已被 FSM/Tool 覆盖的步骤可以由固定执行器确定性运行，减少逐步决策 LLM 调用；
2. 一个任务只有部分能力覆盖时，只让 System 2 处理未知局部，之后重新接回确定性执行链；
3. 检索、计划提议、计划编译和执行彼此分离，LLM 只能提议，不能批准自己的计划；
4. 成功 Trace 只能生成 Candidate，不能在当前 Run 中自动变成 Active 资产；
5. 在小数据集上，REUSE/HYBRID 相比普通 Agent Loop 能降低 `tokens_per_validated_success` 和 `llm_calls_per_validated_success`。

最终交付形态是一个只依赖 Python 与本地 Ollama、带轻量 Web UI、可运行 Golden Tasks、可观察每阶段 Token/结果的代码 PoC。

### 当前目标纠正

本项目**不部署、不依赖、不调用 Dify**。这里保留的“Dify 控制平面”只表示一种职责划分：入口、任务规范化、检索、SAD、计划提议、编译和模式路由由 Python 控制流显式实现。后续代码中不应出现 Dify SDK、Dify Docker Compose、Dify Workflow DSL 或“先部署 Dify 才能运行”的前置条件。

UI 是当前 PoC 的新增一等能力：它必须能展示控制流和运行结果，并能单独触发组件测试；但 UI 不能复制业务规则或绕过 Compiler/Gateway/Validator。

---

## 3. 明确不做的事情

首版不要实现：

- Dify、Coze、Flowise 等需要单独部署的控制平台；
- React/Vue/Node 等独立前端工程；
- 企业级多租户和完整 RBAC；
- Kubernetes、消息队列、分布式事务和多服务拆分；
- PostgreSQL、Redis、MinIO、OpenSearch、Milvus 等生产基础设施；
- 在线自动修改 Active Skill；
- 自动 Shadow/Canary 流量系统；
- 自动生成并执行任意 Python、SQL、Shell 或 Jinja；
- 开放式无限 Agent Loop；
- 真实支付、删除、审批、邮件群发等不可逆高风险工具；
- 复杂并行 DAG、跨天长事务和大规模技能图搜索；
- 专用 Reranker/Skill Composer 训练；
- 为了“架构完整”而提前编写没有验证用途的模块。

当需求超出以上范围时，先记录为 `Deferred`，不要未经确认扩张 PoC。

---

## 4. 固定技术选型

### 4.1 运行环境

| 项目 | PoC 选择 | 说明 |
| --- | --- | --- |
| 语言 | Python 3.12 | 项目 Conda 环境已安装 `Python 3.12.13` |
| API | FastAPI + Uvicorn | 本地 UI、脚本和测试的统一 HTTP 入口 |
| UI | Gradio Blocks | 挂载在同一 FastAPI 的 `/ui`，用于演示和组件实验 |
| Schema | Pydantic v2 | LLM 输出、Blueprint、Contract、API 输入输出统一校验 |
| 执行器 | LangGraph | 固定 Meta-Executor、Checkpoint、Interrupt |
| Agent 模型 | Ollama `qwen3.5:9b` | 用户指定；所有规划与受控推理走统一模型适配器 |
| Embedding | Ollama `qwen3-embedding:0.6b` | 小体量中文/多语检索；不是 Agent 内核 |
| Registry | SQLite | 资产、版本、Header、Snapshot、Candidate 和 Runtime Ledger |
| Sparse 检索 | SQLite FTS5 | 精确术语、工具名、错误码和业务实体 |
| Dense 检索 | Python + NumPy 余弦排序 | 小数据直接扫描，暂不强依赖向量扩展 |
| Artifact | 本地 JSON/YAML 文件 | FSM Body、Fixture、Golden Task 和报告 |
| Checkpoint | `langgraph-checkpoint-sqlite` | 使用独立 SQLite 文件 |
| 依赖管理 | 项目级 Conda + `pyproject.toml` | 环境固定在根目录 `.conda`，`environment.yml` 负责创建/同步 |
| 测试 | pytest | Unit、Integration、Golden/E2E |

### 4.2 本地运行单元

- **Ollama**：本机模型服务，提供 Chat、Tool Calling、Structured Output 和 Embedding API。
- **ReduceTokenAgent**：单一 Python 进程，同时承载 FastAPI、Gradio UI、代码控制面、LangGraph、System 2 和轻量 Registry。

### 4.3 选型边界

- SQLite 适合当前单机小数据验证，不代表生产最终选型。
- `sqlite-vec` 当前是 pre-v1，可作为后续可选加速，不得成为首版正确性依赖。
- Dense 候选规模预期为几十到几百条；超过本地线性扫描能力后再替换向量层。
- Gradio 只负责展示和触发 Application Service；不在 UI 回调里复制业务规则、直接读写数据库或实现控制流。
- FastAPI 与 Gradio 共用同一组 Application Service，不形成两套行为不一致的入口。

---

## 5. 当前环境事实

2026-07-27 本机安装与验证结果：

| 能力 | 状态 |
| --- | --- |
| Conda | 已安装：25.11.1；Base 位于 `/opt/anaconda3` |
| 项目环境 | `DONE`：`ReduceTokenAgent/.conda` |
| Python | 项目环境已安装：3.12.13 |
| Python 依赖 | `DONE`：项目及 `[dev]` 依赖已安装，`pip check` 无冲突 |
| 自动化测试 | `DONE`：215个pytest通过；Mypy通过（110个源码文件）；本次变更文件Ruff通过。214项沙箱内通过，既有1项gRPC回环端口用例在允许本机回环监听后通过 |
| Ollama CLI | 已安装：0.32.4 |
| Ollama Server | 已运行；本机 `127.0.0.1:11434` 可访问 |
| `qwen3.5:9b` 是否已拉取 | 用户已确认本地安装 |
| `qwen3-embedding:0.6b` 是否已拉取 | 已确认本地安装：639 MB |
| `uv` | 当前未检测到 |

环境以 `environment.yml` 和 `pyproject.toml` 为声明源；`.conda` 不提交版本控制。环境状态变化后必须更新此表。

---

## 6. 必须保留的 PoC 设计不变量

### 6.1 LLM 只能提议

- Normalizer、SAD、Plan Proposer、System 2 可以调用 LLM；
- Blueprint Compiler 必须是确定性 Python；
- Tool 调用前由 Action Gateway 再检查 Allowlist、Schema 和预算；
- Result 必须通过独立 Validator；
- 模型不能通过自然语言声明绕过 Compiler、Gateway 或 Validator。

### 6.2 固定 Meta-Executor

- 不为每个请求生成新的 Python 代码或动态编译任意 LangGraph；
- LangGraph 只运行一张固定调度图；
- Registry 中不设置 `BLUEPRINT` Kind；`WORKFLOW_SKELETON` 是唯一持久化的
  DAEF 宏观阶段骨架类型；
- 请求级编译调度数据属于 Runtime，不作为可召回资产，也不与
  `WORKFLOW_SKELETON` 形成两套 Registry 类型；
- Executor 类型来自固定枚举；
- 当前 Run 引用的 `asset_ref=id@version` 不热切换。

### 6.2.1 Registry Kind 固定集合

`Skill` 只作为产品层上位词。Registry 的 `kind` 固定为：

```text
PRIMITIVE_TOOL
FSM_SHARD
WORKFLOW_SKELETON
ADAPTER
VALIDATOR
```

其中 Tool/FSM 普通召回，Skeleton 只作为规划先验，Adapter/Validator 默认由
Capability Graph 一跳扩展加入。不得写入 `SKILL`、`BLUEPRINT` 或
`EXTRACTOR` Kind。

### 6.2.2 DRAFT 资产可用性门槛

后续每个 domain 的资产不允许只停留在“合同定义可校验”。一个 DRAFT 资产若要被
称为当前阶段可用，至少必须同时满足：

- Registry 中存在明确 `asset_ref=id@version` 和 Runtime Binding；
- `PRIMITIVE_TOOL`、`FSM_SHARD`、`ADAPTER`、`VALIDATOR` 有本地受控逻辑体；
- 逻辑体旁边有最小业务元数据，包括 `policy_version`、`business_rules`、
  `policy_document` 和 `audit_flow`；
- 测试固定落在 `tests/assets/<domain>/`，用真实可验证小案例证明精确召回后能执行；
- `WORKFLOW_SKELETON` 只证明可作为规划先验读取，不能直接执行；
- 通过行为测试仍不等于 `ACTIVE`，Snapshot 激活必须后续人工执行。

当前 `corporate_operations`、`customer_service` 和 `financial_report` 都已按该门槛建立
`tests/assets/<domain>/test_*_runtime_execution.py`。

### 6.3 只推理未知局部

- REUSE Step 不调用决策 LLM；
- HYBRID 只允许未知 Step 进入 System 2；
- System 2 输出类型化 Artifact 后立即退出；
- 已存在确定性路径的后续步骤重新由 Meta-Executor 接管。

### 6.4 System 2 必须有界

当前本地验证默认硬限制（仍然是硬门禁）：

```text
max_reason_steps = 6
max_llm_calls = 6
max_tool_calls = 8
max_wall_time_seconds = 180
max_token_budget = 24000
side_effect_policy = READ_ONLY
plan_repair_attempts = 1
```

这些值必须来自配置，并在每次调用前后检查。提高预算是为了覆盖大多数普通
NEW/HYBRID 任务，不代表取消安全停止；仍不得通过创建子任务、递归调用或切换
模型绕过预算。

### 6.4.1 路由覆盖率与轻量缺口

路由计算必需子目标集合 `R`、确定性主步骤覆盖集合 `D` 和轻量缺口集合 `L`。
`L` 仅允许以下固定原因码，且必须无副作用、无人工门禁、最多一次迭代：

```text
LIGHTWEIGHT_FORMAT_NORMALIZATION
LIGHTWEIGHT_INFO_CONFIRMATION
LIGHTWEIGHT_FIELD_DEFAULT
LIGHTWEIGHT_ENUM_COERCION
```

轻量缺口由固定 LangGraph 执行器零 Token 处理，并计入有效确定性覆盖：

```text
effective_covered = |R ∩ (D ∪ L)|
coverage_ratio = effective_covered / |R|
```

路由规则固定为：

- `REUSE`：`coverage_ratio == 1`；
- `HYBRID`：`coverage_ratio > 0.40` 且小于 `1`；
- `NEW`：`coverage_ratio <= 0.40`。如果仍有 FSM/Tool，NEW 仍可同时执行这些
  复用步骤，但整体模式保持 NEW；
- `HUMAN`、非轻量 `EXTRACT/REASON` 不计入确定性覆盖；
- 缺失身份、硬策略失败优先进入 `CLARIFY/REJECT`。

采用严格大于 40% 的条件，避免恰好 40% 的低覆盖任务被误标成 HYBRID。

### 6.5 结构化契约优先

- 所有跨组件输入输出必须是 Pydantic Model；
- LLM 使用 Ollama Structured Outputs 请求 JSON Schema；
- LLM 输出即使是 JSON，也必须再次经过 Pydantic 校验；
- 最多允许一次结构化修复；
- 修复失败进入 CLARIFY、SAFE_STOP 或 REJECT。

### 6.6 Checkpoint 与 Ledger 分离

- LangGraph Checkpoint 保存图状态；
- Runtime Ledger 保存 Step attempt、幂等键、工具结果摘要、Token 和状态转换；
- 两者使用不同 SQLite 文件或至少不同连接/仓储边界；
- 外部副作用不能只依赖 Checkpoint 去重。

### 6.7 当前 Run 与资产演进分离

- Trace 只能创建 `DRAFT` Candidate；
- Candidate 必须经测试和人工 CLI 操作才能 `ACTIVE`；
- 当前 Run 永远使用开始时固定的 Snapshot；
- 不允许执行失败后直接改写 Active JSON。

### 6.8 只记录必要推理证据

允许记录：

- `reason_code`；
- 结构化行动；
- Tool/Asset 固定版本；
- 输入输出安全摘要；
- Validator 和错误码；
- Token、耗时和预算；
- Artifact 引用。

默认不保存模型完整 Chain-of-Thought。

---

## 7. PoC 允许的简化

| 完整设计 | PoC 简化 |
| --- | --- |
| PostgreSQL Registry + 多 schema | 单个 `registry.sqlite3`，用表前缀和 Repository 隔离职责 |
| 对象存储/Git Artifact Store | `data/artifacts/` 下不可变版本文件 |
| 多租户 ACL | 固定 `tenant_id=local` + 简单 Scope 集合 |
| Ready Snapshot 发布事务 | Active 资产集合的递增 ID + Digest |
| Sparse + Dense + Metadata + Graph | FTS5 + NumPy Cosine + SQL Metadata；Graph 只支持显式一跳关系 |
| Contract Reranker | 确定性规则评分；必要时再加一次结构化 LLM 打分 |
| 完整 DAEF 库 | 1-2 个手工 Skeleton，只作为规划提示 |
| 自动治理平台 | CLI 命令：seed、list、activate、quarantine、evaluate |
| Shadow/Canary | Golden Replay 通过 + 人工 activate |
| 多类真实工具 | 本地可验证 Mock Tool/文件 Tool |
| 复杂 DAG | 首版顺序执行；第二阶段支持无环小 DAG |
| 完整 Human Service | LangGraph Interrupt + API resume |

简化不得破坏“LLM 不自批、计划先编译、推理有界、结果有验证、资产不热改”五条底线。

---

## 8. 首个验证域

默认使用“本地故障处理”作为唯一演示域：

```text
读取本地模拟日志
  -> 形成 VerifiedErrorFact
  -> 创建本地 JSON Ticket
  -> 写入本地 Notification Receipt
```

首批资产建议：

- `tool.local_log.search@1.0.0`
- `fsm.local_log.verify_error@1.0.0`
- `tool.local_ticket.create@1.0.0`
- `fsm.local_ticket.create@1.0.0`
- `tool.local_notify.send@1.0.0`
- `fsm.local_notify.send@1.0.0`
- `validator.error_fact@1.0.0`
- `validator.ticket@1.0.0`

选择本地域的原因：

- 结果可以确定验证；
- 写操作可用本地文件实现并安全清理；
- 能构造 REUSE、60/40 HYBRID、NEW、AMBIGUOUS 和错误恢复；
- 不依赖真实企业系统凭据；
- 可以精确计算重复副作用和 Token。

未经用户确认，不要在 PoC 首版换成多个业务域。

---

## 9. 编码约束

### 9.1 分层

- `domain` 不依赖 FastAPI、LangGraph、SQLite 或 Ollama；
- `control_plane` 只能通过接口访问 Registry、LLM 和 Executor；
- `execution` 不重新做语义检索或自由规划；
- `system2` 不直接访问未授权 Tool；
- `registry` 不调用 LLM；
- `api` 只做协议转换、鉴权占位和错误映射；
- `ui` 只调用 Application Service/API，不直接读写 Registry、Ledger 或 Checkpoint；
- API 与 UI 必须复用相同的 Facade，禁止分别实现两套控制流程。

### 9.2 Python 规范

- Python 3.12 类型标注；
- Pydantic v2；
- 公共函数和类必须有简短 docstring；
- 避免全局可变状态；
- 时间统一用带时区 UTC；
- ID 使用稳定前缀，如 `run_`、`bp_`、`snap_`、`asset_`；
- 错误使用类型化错误码，不以自由文本驱动控制流；
- 配置通过 Settings 读取，禁止在业务代码硬编码模型名、预算和路径。

### 9.3 数据与安全

- `.env`、模型凭据、真实日志、Checkpoint 和运行数据库不得提交；
- 示例数据必须是合成数据；
- Artifact 文件名包含版本或 Digest，不原地覆盖 Active 内容；
- Tool 参数先校验再调用；
- 路径操作限制在配置的数据目录；
- 不执行来自用户或 LLM 的任意代码。

### 9.4 Token 记录

每次 LLM 调用至少记录：

- stage；
- model；
- prompt/input token count；
- output token count；
- latency；
- structured validation result；
- run/step ID。

若 Ollama 返回的计数字段与预期不同，适配器负责统一，不允许调用方各自解释。

---

## 10. 测试与验收规则

### 10.1 测试层级

1. Unit：Schema、Compiler、Router、Budget、RRF、Validator；
2. Integration：SQLite Repository、Ollama Adapter、LangGraph Checkpoint/Resume；
3. Golden：固定任务、固定资产 Snapshot、固定预期 Blueprint/模式/结果；
4. UI：Gradio 回调、Tab 输出和错误展示；
5. E2E：本地 UI 或直接 API 发起任务，得到验证结果或 Interrupt；
6. Failure Injection：非法 Blueprint、未知 Tool、预算耗尽、Validator 失败、重复提交。

### 10.2 必测场景

- 100% REUSE，执行阶段无决策 LLM；
- 60/40 HYBRID，只有一个 Reason Step 调用 LLM；
- Value Gap 进入 Extract/Human，不进入无限 Reason；
- Adapter 缺失时编译拒绝；
- Policy Denied 不能被 System 2 绕过；
- Tool Allowlist 之外的调用被拒绝；
- 同一 Idempotency Key 不产生两个 Ticket；
- Validator 失败不能推进下游；
- 运行中激活新版本不影响当前 Snapshot；
- Candidate 不会自动 Active；
- 恢复 Interrupt 使用相同 `run_id/thread_id`。

### 10.3 比较基线

必须同时实现一个极小的 Baseline Agent Loop，仅用于评测：

- 使用相同 `qwen3.5:9b`；
- 使用相同 Tool 集；
- 相同测试输入；
- 不使用已编译 FSM；
- 设置与 System 2 相同的总安全边界。

比较：

- Validated Success；
- LLM Calls；
- Input/Output Tokens；
- Tool Calls；
- P50/P95 Latency；
- False Reuse；
- 重复副作用。

不得只报告 Token 下降而隐藏成功率或 Validator 失败。

### 10.4 动态验证执行经济性

- 依赖本地 Ollama 的慢速 E2E、Golden 和真实场景 smoke，普通增量任务默认只运行一个
  最小且有代表性的案例；该案例通过即可作为本阶段的动态执行证据；
- 只有修改 Router/覆盖率阈值、Compiler、Interrupt/Resume、跨模式执行语义，进入里程碑门禁，
  或用户明确要求时，才扩展运行完整的 REUSE/HYBRID/NEW/EXTRACT/HUMAN 场景矩阵；
- 若批量动态验证已经启动，获得所需代表性通过结果后应停止剩余非必要案例；
- 本规则不削弱 Unit、静态检查、目标回归和安全门禁。与本次变更直接相关的快速测试仍须完整运行。

---

## 11. 进度维护规则

- 每完成一个可验证交付，更新本文件的“当前实现快照”；
- 状态只使用：`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、`DONE`；
- `DONE` 必须带验证证据，如测试名、命令或报告路径；
- 不因文件已创建就把功能标记为完成；
- 新增重大依赖或改变目录边界时，同时更新 `PROJECT_STRUCTURE.md`；
- 发现设计不再适用时先记录决策，再修改代码。

---

## 12. 当前实现快照

### 12.1 总体状态

```text
阶段：Phase B + Phase D Control Plane Vertical Slice + Phase E Bounded System2
可运行代码：Trace 采集、Kind Contract、SQLite Registry/Runtime、三个 domain Runtime、FTS5/Dense/RRF/Graph Retrieval、Control Plane 规范化/粗拆/SAD/Contract Rerank/Blueprint Compile/Mode Route、固定 LangGraph Meta-Executor、有界 System2、Checkpoint/Runtime Ledger、runtime-trace.v1 原始 Trace 投影和审阅报告
可运行本地 UI：FastAPI同进程挂载的Gradio `/ui`，含业务演示、历史运行检查、组件验证和独立人工审批入口；支持一键加载差旅报销案例与Robot 353贷款被拒咨询案例、按Executor Receipt排序的实际执行时间线、逐步输入来源/执行能力/输出验证、独立Blueprint依赖视图和重启后历史Trace恢复（含DM事件投影）
Registry 数据：45 个已测试 ACTIVE 资产、37 条关系边；28 个生产语义索引文档；当前ACTIVE Snapshot为 `snapshot_active_c5da985bcc54bf83`（45成员），旧43成员Snapshot保留
Control Plane 运行数据库：`data/db/runtime.sqlite3`（结构化事件、Blueprint 编译证据；不保存默认 CoT）
Golden Tasks：控制流 E2E Fixture 已覆盖；固定 Meta-Executor 与 System2 已完成真实本地 Ollama 端到端验证
```

### 12.2 组件进度

| 组件 | 状态 | 当前证据/说明 |
| --- | --- | --- |
| PoC 目标与边界 | DONE | 本文件第 2-8 节 |
| 技术可行性核对 | DONE | 2026-07-27 官方能力核对；见 `PROJECT_STRUCTURE.md` |
| 项目目录设计 | DONE | `PROJECT_STRUCTURE.md` |
| 项目级 Conda 环境 | DONE | `.conda`，Python 3.12.13；`pip check` 无冲突 |
| Python 项目骨架 | DONE | `pyproject.toml`、`environment.yml`、`src/`、`tests/`；215个测试通过（214项沙箱内通过，1项gRPC回环端口测试在允许本机回环监听后单独通过） |
| 环境质量检查 | DONE | Mypy 110个源码文件通过；本次变更文件Ruff通过 |
| Synthetic Trace Schema | DONE | `trace_data/models.py`；引用、步骤、Artifact、验证和 DRAFT Candidate 交叉校验 |
| Trace 场景目录 | DONE | 50 条：4 个主领域各 10 条，风险合规/企业运营各 5 条 |
| Ollama Trace 生成脚本 | DONE | 常见 ID/枚举/引用别名会确定性规范化；质量缺口落为 Flag；真实 `qwen3.5:9b` 前 3 条生成、Schema、Manifest、Resume 复测通过 |
| Synthetic Trace 数据集 | DONE | 初始数据集固定采用 43 条 Schema 有效 Trace；`manifest.json` 为 43/43，未生成的 7 条不再作为本轮启动数据 |
| 配置系统 | DONE | `control_plane/config.py` + `config/control_plane.example.yaml`，预算、模型和视图策略均显式配置 |
| Ollama Agent Model Adapter | DONE | `llm/base.py` + `llm/ollama_client.py`；`qwen3.5:9b` Structured Output、Pydantic 二次校验和一次格式修复 |
| Registry Kind/Contract Schema | DONE | 五类 Kind、Contract、Body、Route Header、DAEF/FSM/Adapter/Validator 边界由 Pydantic 校验 |
| SQLite Registry | DONE | `001_registry.sql`、`002_runtime_bindings.sql`、`007_dm_fsm_binding.sql`、Repository、版本/发布/关系/评测/Runtime Binding、ACTIVE Snapshot 已实现；当前45个资产均ACTIVE，Robot 353仅限SIT且保留生产策略门禁 |
| Retrieval | DONE | `003_retrieval.sql`、FTS5 中文 n-gram、Ollama `qwen3-embedding:0.6b`、NumPy Cosine、RRF、SQL Metadata、反向触发惩罚、一跳 Graph 与 Header Budget 已实现；新生产索引为28个Header；DM-09的13文档`dm_test_*`隔离索引继续仅用于能力描述测试 |
| Control Plane 主流程 | DONE | `control_plane/service.py`；Normalize、粗拆、冻结索引视图、Hybrid Retrieval、SAD 一次、Contract Rerank、提议、编译、覆盖率阈值路由、Guard、System2/LangGraph 交接；明确人审语义由代码强制转换为 HUMAN，禁止降级为 REASON |
| Control Plane 本地模型兼容性 | DONE | 显式本地合成数据由代码提升为 `SYNTHETIC`；SAD 漏目标确定性补回；粗拆越界目标确定性合并；模型漏填/越界 Asset ID 或错误绑定 `EXTRACT` 时仅从冻结候选生成修复提案；硬策略拒绝不允许降级绕过。长期基线 `run_3caafd35a1a8f1eb` 已完成 REUSE；其余临时失败、预算超限和兼容性试跑已清理 |
| Runtime Trace 沉淀与审阅 | DONE | `trace_data/runtime_models.py`、`runtime_store.py`、`control_plane/trace_recorder.py`、`scripts/review_runtime_trace.py`；每次运行形成 `trace_run_*` 原始 Trace，支持失败原因、时间线、System2/DM输入输出、Artifact、Token可见性、最终用户回复和抽取资格审查；DM只记录conversation/dialog/turn/message摘要引用，PARTIAL恢复后刷新JSON |
| Blueprint Compiler | DONE | `control_plane/blueprint_compiler.py`；视图、DAG、Schema、Scope、风险、人审、预算、副作用、Validator、Binding 门禁 |
| Mode Router / Output Guard | DONE | `control_plane/mode_router.py`、`output_guard.py`；REUSE/HYBRID/NEW/CLARIFY/REJECT 路由与安全结构化输出 |
| LangGraph Meta-Executor | DONE | `execution/graph.py` 固定父图 + `execution/meta_executor.py` 严格执行已编译 Blueprint；含 Checkpoint、轻量缺口零 Token 执行、同一 `run_id` 的人工恢复、已完成步骤/输出恢复种子（不重复执行）、运行前门禁、步骤级输入/输出/Validator/Artifact/Token Trace |
| System 2 | DONE | `system2/executor.py` 实现 Freeze/Observe/Action Gateway/Verify/预算门禁；只允许白名单只读 Tool，输出类型化 Artifact；Hybrid 缺口回接 LangGraph，New 独立落账；HUMAN 硬暂停、typed answer 同 run 恢复并复用人审前已验证输出；默认 6 次 LLM/6 个 Reason/8 次 Tool/24k Token |
| 最终用户回复 | DONE | `control_plane/final_response.py`；成功任务基于允许的执行证据生成自然回答，结构化输出先转业务语言并去重；样例输入不再作为真实结论，模型失败/机器载荷/越界 Evidence/虚假写入声明均转可读安全回退；能力介绍有确定性用户答复 |
| Runtime Ledger | DONE | `execution/ledger.py` + `005_execution_ledger.sql`；`execution_run`、`execution_step_attempt`、`execution_token_usage` 已落库，执行阶段 token 与状态可审计 |
| 单任务 CLI | DONE | `scripts/run_agent_task.py`；接收真实问题，打印Direct或编译Blueprint流程，分别等待DM真实用户回复或HUMAN审批，并输出最终回复、状态与Trace引用 |
| FastAPI Local API | DONE | `api/app.py`；提供任务执行/查询、DM真实用户输入恢复、独立HUMAN审批和受鉴权Nexus CloudEvents callback；与UI共用Facade |
| Gradio Local UI | DONE | `ui/app.py` + `ui/handlers.py` + `ui/presenters.py`；挂载`/ui`，提供费用预审和Robot 353 DM双演示、历史运行检查、组件验证及独立人工审批；DM案例显示当前进程是否真实开启Robot 353 SIT，Chatbot只接收标准`role/content`消息，提交后清空输入；唯一命中后展示创建/恢复会话、机器人消息、Cursor、Contract验证、0本地Token与等待用户输入；历史Run可从SQLite Trace恢复DM或Blueprint安全视图 |
| Corporate Operations Kind 抽取 | DONE | 仅从 4 条对应 Trace 抽取 13 个 DRAFT：3 Tool、4 FSM、1 Skeleton、1 Adapter、4 Validator；17 tests passed |
| Corporate Operations Runtime 资产可用性 | DONE | 12 个可执行资产具备本地逻辑体、政策元数据和行为测试；1 个 DAEF Skeleton 规划专用且不可执行 |
| Customer Service Kind 抽取 | DONE | 仅从 8 条对应 Trace 抽取 14 个 DRAFT：4 Tool、4 FSM、1 Skeleton、1 Adapter、4 Validator；12 tests passed |
| Customer Service Runtime 资产可用性 | DONE | 13 个可执行资产具备本地逻辑体、政策元数据和行为测试；1 个 DAEF Skeleton 规划专用且不可执行 |
| Financial Report Kind 抽取 | DONE | 仅从 8 条对应 Trace 抽取 16 个 DRAFT：4 Tool、5 FSM、1 Skeleton、1 Adapter、5 Validator；16 tests passed |
| Financial Report Runtime 资产可用性 | DONE | 15 个可执行资产具备本地逻辑体、政策元数据和行为测试；1 个 DAEF Skeleton 规划专用且不可执行 |
| Asset Runtime Verifier | DONE | `scripts/verify_asset_runtime.py`；支持单资产/域内批量执行、validator 链、输入输出状态追踪与 `tested_at` 落库 |
| Seed Assets | DONE | 原有43个合规资产与Robot 353新增2个资产已写入`data/db/registry.sqlite3`，37条Edge与Runtime Binding均可用；经验证后已全量激活 |
| Retrieval Index Builder | DONE | `scripts/build_retrieval_index.py`；当前 ACTIVE 索引为 `retrieval_a2180f6ce4234bf64cd9`，固定到 `snapshot_active_c5da985bcc54bf83`，含28个FTS/Dense文档；旧Index记录保留 |
| Registry 召回/硬过滤审查 | DONE | `scripts/audit_registry_recall.py` + `data/db/REGISTRY_RECALL_AUDIT.md`；45/45按各自Contract的环境/数据级别及ORDINARY/PLANNING_PRIOR/GRAPH_ONLY合法通道命中，临时DRAFT探针被过滤且已恢复ACTIVE |
| Retrieval Detail/Invocation | DONE | Header 与 Contract/Runtime 两层读取；`scripts/verify_retrieval_layer.py` 的 Tool + 三域 FSM + 一个 Skeleton 共 5 个案例全部通过，FSM 均完成 Runtime 与 Validator 链 |
| DM FSM 只读资源锁 | DONE | `Resource_FSMRobot/dm-resource-lock.json` + `scripts/verify_dm_fsm_resources.py`；已锁定8项本地资源（含Robot Nexus手册）、Robot 353配置摘要与`ai-robot@b15ae84...`，44项检查PASS；报告见`data/reports/dm_fsm_resources/DM_FSM_RESOURCE_VERIFICATION.json`，Registry摘要前后一致 |
| DM Domain Contract | DONE | `domain/dm.py`保留直接gRPC诊断语义；`domain/dm_nexus.py`定义正式Nexus Binding/Dialog/Inbound/Reply Observation，平台不持有DST；Nexus边界测试通过 |
| DM gRPC Stub / Client Port / Fake | DONE | proto/stub/Fake继续证明Nexus内部DM流式契约，但已降级为`DIAGNOSTIC_ONLY`，正式平台不得绕过Nexus调用 |
| DM Request Adapter / Response Aggregator | DONE | 原DST Adapter/Aggregator保留为直接协议诊断；正式边界由`nexus_client.py`使用唯一dialogNo/messageNo、HTTP ACK和异步回复观察，凭据与原始输入不落报告 |
| DM Robot Nexus SIT纵向切片 | DONE | Nexus要求`X-Chatbot-App-Id: robot-admin`；加入可配置Header并兼容新会话`messageEvents=null`后，真实运行`run_271780743b0605cf`完成Health、ServiceInfo、Proxy、Dialog Create和西语贷款拒绝解释两轮，第二轮正确进入“已还清但被拒”分支。报告PASS；未接入Control Plane/Registry |
| DM Policy Verification Gate | DONE | `domain/dm_policy.py` + `integrations/dm/policy_gate.py`；支持`SOURCE_CONFIG_ONLY / EFFECTIVE_VERIFIED / MISMATCH`。仅显式SIT允许source-only，staging/production要求真实effective摘要；版本或摘要不一致在网络请求前返回`DM_POLICY_VERSION_MISMATCH`，不伪造effective digest |
| DM Nexus Conversation Store | DONE | `006_dm_conversation.sql` + `domain/dm_conversation.py` + `integrations/dm/conversation_repository.py`；迁移已应用到`data/db/runtime.sqlite3`且原Control/Execution行数不变、外键检查通过；dialog/message稳定ID、local cursor、revision CAS、单活跃Turn、callback/detail去重、乱序增量恢复、终止门禁和同dialog USER_INPUT恢复均通过测试；不含DST字段，不接入路由 |
| DM Robot 353 Registry Seed | DONE | `fsm.customer_service.robot_353_dm@1.0.0`与独立响应Validator按锁定资源先以DRAFT落库；13个子流程仅为不可执行descriptor。DM-08历史证据见`data/db/ROBOT_353_DM_REVIEW.md`，当前激活状态以DM-10报告为准 |
| DM Robot 353 隔离Retrieval / Direct Gate | DONE | `008_dm_test_retrieval.sql`保留13文档隔离测试空间；生产Application使用`dm_discovery.py`对ACTIVE descriptor做精确触发发现，Dense-only不能直通。Gate继续要求唯一能力、单目标及全部治理/策略门禁；见`data/db/ROBOT_353_RETRIEVAL_REVIEW.md` |
| DM Robot 353 SIT 激活 | DONE | `registry/dm_activation.py` + `scripts/activate_robot_353_sit.py`；人工批准后校验DM-05/06/08/09，激活2项SIT资产，创建45成员新Snapshot并重建28文档生产Index；旧Snapshot/Index保留，失败可回滚，`SOURCE_CONFIG_ONLY`在production仍被拒绝；见`data/db/ROBOT_353_ACTIVATION_REVIEW.md` |
| DM_DIRECT Application快速路径 | DONE | `application/task_router.py` + `dm_direct_executor.py` + `ApplicationFacade.execute_task()`；默认关闭，唯一可靠SIT命中才调用Nexus，机器人消息不经本地LLM改写。Direct单目标判定只依据用户业务目标；恢复轮次向Nexus传递历史`messageNo`集合，并再次按Repository归属过滤旧消息，防止旧回复冒充本轮输出或触发Cursor错误；仓储拒绝转换为结构化失败。无命中或门禁失败仍沿同一Trace回退；业务请求发送后失败不回退 |
| DM FSM Blueprint Runtime | DONE | `execution/runtime_dispatcher.py` + `dm_fsm_executor.py`；普通FSM Step严格按`implementation_ref`选择`LOCAL_PYTHON`或`ROBOT_NEXUS_HTTP`。DM Step可进入独立`USER_INPUT_REQUIRED`中断，使用同一run/thread/Blueprint/dialog恢复且不重新规划；恢复完成后运行独立Validator。默认关闭及SIT source-digest门禁保持不变；见`data/db/ROBOT_353_DM_BLUEPRINT_REVIEW.md` |
| DM Trace / Review / Token Visibility | DONE | DM-13统一写入现有`runtime-trace.v1`：DM发现与Direct Gate、Binding Dispatch、安全会话引用、每轮输入摘要、逐条异步消息/Cursor、等待/恢复/失败、Validator、最终用户输出均可审查；Nexus未暴露内部Token时明确为`NOT_EXPOSED`而非0。报告见`data/db/ROBOT_353_DM_TRACE_REVIEW.md` |
| DM CLI/API/UI多轮交互 | DONE | DM-14新增CloudEvents callback Contract/Broker/Service、CALLBACK多消息聚合、dialog/robot/message关联与CAS去重；Direct及Blueprint均可等待真实用户输入并恢复原会话。DM与HUMAN入口隔离；见`data/db/ROBOT_353_DM_INTERACTION_REVIEW.md` |
| Retrieval SOP | DONE | `data/RETRIEVAL_LAYER_SOP.md`；规定可见性、Kind 通道、索引构建、RRF、Graph 扩展、详情解析、真实调用和新 domain 接入验收 |
| Data/召回数据地图 | DONE | `data/DATA_LAYOUT_AND_RETRIEVAL_FLOW.md`；记录 Trace、Artifact、Runtime Metadata、SQLite 表、索引和报告位置，以及资产从 Trace 到检索、详情解析、执行和 Validator 的逐层链路 |
| Control Plane Unit/Integration Tests | DONE | `tests/control_plane/`；缺失身份、REUSE、HYBRID、40% 阈值 NEW+复用、轻量零 Token REUSE、NEW、本地合成分类修正、粗拆越界收敛、越界资产提案修复、EXTRACT、HUMAN 中断/同 run 恢复、Trace 脱敏、成功/失败运行 Trace 投影刷新、固定执行器和审查 |
| Baseline 对照 | NOT_STARTED | 尚未实现 |
| Token 实验报告 | NOT_STARTED | 尚无数据 |

### 12.3 当前前置条件

- Python 开发环境已经完成，后续命令使用 `conda activate ./.conda`；
- 运行模型相关测试前需确认 Ollama 服务已启动；
- `qwen3.5:9b` 已由用户确认安装；
- `qwen3-embedding:0.6b` 已安装，Embedding Adapter 与真实 Dense Retrieval 已完成；
- 当前 ACTIVE Snapshot 为 `snapshot_active_c5da985bcc54bf83`；旧的
  `snapshot_active_2268db04482b62ca`保留；Retrieval 使用
  `ACTIVE_SNAPSHOT`，并继续要求 `PASS + tested_at + READY/PLANNING_ONLY`；
- `qwen3.5:9b` 的实际 Tool Calling/Structured Output 稳定性必须通过本机测试确认，不能仅依据模型说明假定。

### 12.4 合成 Trace 数据约束

- 采集脚本只生成合成原始 Trace，不把 Trace 自动注册为 Active Asset；
- 每条记录包含 `trace`、`provenance` 和 `governance` 三层；
- `trace.steps` 记录操作、输入引用、动作、单个 Artifact、验证、失败码、幂等和副作用；
- `trace.candidate_assets` 保留生成期的 Tool/FSM/Extractor/Adapter/Validator
  候选提示；入 Registry 时必须映射或筛选为五类正式 Kind，其中独立 Extractor
  归入单操作 `PRIMITIVE_TOOL` 或 FSM 内部实现，不创建 `EXTRACTOR` Kind；
- `governance.status` 固定为 `DRAFT`，`human_review_required=true`，`chain_of_thought_stored=false`；
- 数据只允许用于候选挖掘、Schema 实验、检索种子和组件测试，不作为真实执行证据或生产决策依据；
- 脚本使用 `--resume` 和原子 JSON 替换，模型超时、截断或 Schema 失败不会留下半条记录。
- 模型常见格式别名先由采集层确定性规范化并同步引用；内容覆盖不足记录到 `quality_flags`，不因非致命质量缺口反复生成；
- 每次内部重试输出 `trace_retry` 及校验摘要；`Ctrl+C` 会先刷新 Manifest/Report，再以可继续状态退出。
- 当前启动数据集固定为 43 条已生成 Trace；未生成的 7 个场景保留在场景目录中供未来扩展，但不属于当前初始数据集。

---

## 13. 阶段出口

### Milestone 0：工程骨架

完成条件：

- API 可启动；
- `/health` 能报告 Python、SQLite 和 Ollama 状态；
- 配置、日志、错误和测试骨架可用。

### Milestone 1：确定性 REUSE

完成条件：

- 手工 Blueprint 通过 Compiler；
- 固定 Meta-Executor 完成三步本地任务；
- Validator 和 Ledger 有证据；
- 相同幂等键不会重复创建 Ticket；
- 执行 Step 不调用决策 LLM。

### Milestone 2：受控 HYBRID

完成条件：

- 一个缺口进入有界 System 2；
- Tool Allowlist、预算和 Output Schema 生效；
- 验证后的 Artifact 接回确定性 FSM；
- 越权 Tool 和预算扩张被拒绝。

### Milestone 3：检索与模式路由

完成条件：

- FTS + Dense + RRF 返回候选；
- 一次 SAD 后拆解更贴近资产粒度；
- Compiler 决定 REUSE/HYBRID/CLARIFY；
- 被召回资产不能绕过 Contract 检查。

### Milestone 4：最小治理

完成条件：

- Trace 生成 DRAFT Candidate；
- Golden Replay 后可以人工 Activate；
- 当前 Run 不切换新 Snapshot；
- Quarantine 后新规划不再召回资产。

### Milestone 5：本地 UI 与实验报告

完成条件：

- Gradio UI 能发起任务、展示各阶段结果并处理 Interrupt；
- Component Lab 能单独测试 Normalizer、Retrieval、Compiler、System 2、Executor 和 Validator；
- Registry、Run Trace、Token Ledger 和 Golden Benchmark 有可视化页面；
- 10-30 条 Golden Tasks 可重复运行；
- Baseline 与 REUSE/HYBRID 报告包含成功率、Token、LLM Calls、延迟和错误；
- 可以据此对核心假设作出 Go/No-Go 判断。

---

## 14. 已确认的可行性与主要风险

### 可行性结论

当前方案可在本地实现，关键能力已有直接支撑：

- Ollama 提供 `qwen3.5:9b`、Tool Calling、Structured Outputs 和 Embedding API；
- LangGraph 支持 SQLite Checkpointer、持久化和 Interrupt/Resume；
- Gradio Blocks 可以直接挂载 FastAPI，同一进程提供本地交互 UI；
- SQLite FTS5、Python 余弦检索和本地 Artifact 足以承载小数据 Registry；
- 所有关键安全边界都可以先用确定性 Python 和 Pydantic 实现，不依赖额外研究模型。

### 主要风险

1. **9B 模型规划质量**：复杂 Blueprint 可能不稳定。控制手段是候选白名单、短 Prompt、JSON Schema、一次修复和编译拒绝。
2. **本机资源**：`qwen3.5:9b` 默认量化模型约数 GB，模型、UI 和 Core 同时运行可能受内存影响。首版限制上下文和并发。
3. **UI 状态一致性**：Gradio Session 不能成为运行事实源；页面刷新后必须从 Runtime Service 重新读取状态。
4. **SQLite 并发**：只支持单机低并发 PoC；使用 WAL 和短事务，不声称生产吞吐。
5. **小数据统计偏差**：实验只能验证机制和方向，不能从 10-30 条任务外推生产 SLA。
6. **模型版本漂移**：模型 Tag、Ollama、Gradio 和 LangGraph 版本必须在实验报告中固定。

---

## 15. 后续 Agent 开始工作前的检查

每次实现任务开始前必须确认：

1. 当前工作属于哪个 Milestone；
2. 是否能用更小的纵向切片验证；
3. 是否保持 LLM 提议、代码批准；
4. 是否新增了未记录依赖；
5. 是否会造成当前 Run 热修改资产；
6. 是否有对应 Unit/Integration/Golden 测试；
7. 完成后应更新哪些进度项。

若任务要求与本文冲突，先向用户说明冲突和最小调整方式，不要静默扩大系统。
