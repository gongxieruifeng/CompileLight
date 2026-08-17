<div align="center">

# CompileLight

**轻量级智能编译守卫 Agent · Deterministic Compilation & Bounded Reasoning for Enterprise Agents**

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.x-orange)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)](https://fastapi.tiangolo.com/)
[![Gradio](https://img.shields.io/badge/Gradio-5.x+-purple)](https://www.gradio.app/)
[![Ollama](https://img.shields.io/badge/Ollama-qwen3.5_9b-00ADD8)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](#LICENSE)

**Trace → Registry → Retrieval → Control → Execution** · 让已知子目标确定性复用，让未知缺口在有界内安全推理

</div>

---

## 📌 项目简介

针对企业客服 Agent 在高频任务中 **重复检索、推理与执行不可审计** 的痛点，CompileLight 设计了一套
「**Trace-Registry-Retrieval-Control-Execution**」五阶段闭环架构：

- **对已知子目标**：优先通过编译门禁复用确定性资产（Tool / FSM / DAEF Skeleton / Adapter / Validator），零额外决策 Token
- **对未知缺口**：仅触发有界 System 2 推理（白名单工具 + 预算门禁 + 输出验证），之后重新接回确定性执行链
- **全程可审计**：编译门禁全量通过、运行 Ledger 与 Trace 逐层留痕、无越权调用与重复副作用

> **核心理念**：**LLM 只提议，代码批准**。模型产出的每一步计划都必须经由确定性 Python 编译器在 Schema / 权限 / 风险 / 预算四道门禁下校验通过后方可执行。

---

## ✨ 核心特性

### 1. 控制与编译流水线
```
TaskRequest
  → Normalize（身份/时间/实体/数据级别/风险）
  → 硬过滤 & 混合召回（FTS5 + Dense + Metadata + Graph → RRF 融合）
  → SAD 语义对齐（仅看 Header + Contract Summary）
  → 受候选白名单约束的 Blueprint Proposal
  → 🔒 确定性编译门禁（Schema / Scope / 风险 / 预算 / 副作用 / Validator / Binding）
  → REUSE / HYBRID / NEW / CLARIFY / REJECT
```
- **语义缓存（Hot Cache）**：对相似意图复用历史 Blueprint，命中率 **68%**，命中请求 P95 由 **8.7s → 580ms**
- **Contract Rerank**：Header 召回 + Contract 匹配两级索引，确保召回精度与执行契约一致

### 2. 执行与三模式路由
基于 **LangGraph** 实现固定 **Meta-Executor**（不为每次请求动态生成图）：

| 模式 | 触发条件 | 执行策略 |
|------|---------|---------|
| **REUSE** | `coverage_ratio == 1` | 全步骤 0 Token 确定性执行；轻量缺口（格式/枚举/默认值）内置零 Token 修正 |
| **HYBRID** | `0.4 < coverage_ratio < 1` | 已知步骤沿用 FSM/Tool；仅 **单个缺口** 进入有界 System 2 → 结果回接原链 |
| **NEW** | `coverage_ratio ≤ 0.4` | 低置信度受控探索：冻结上下文 → 缺口分类 → 有限推理 → 输出验证 |
| **HUMAN / CLARIFY** | 身份缺失 / 硬策略失败 | LangGraph Interrupt 持久化暂停，同 `run_id/thread_id` 恢复 |

### 3. 资产工程与生命周期
- **5 类固定 Kind**：`PRIMITIVE_TOOL` · `FSM_SHARD` · `WORKFLOW_SKELETON` · `ADAPTER` · `VALIDATOR`
- **两级索引**：Header 召回（FTS5 + Dense + RRF） + Contract 匹配（Runtime Binding + Validator 链 + Scope）
- **生命周期**：成功 Trace → 异步沉淀 `DRAFT` Candidate → 人工审阅 + 验证 → `ACTIVE` → 纳入 Snapshot
- **视图冻结**：每次 Run 启动时锁定 Snapshot ID，执行中不热切换版本，不允许失败后改写 Active 资产
- **一跳扩展**：Capability Graph 支持显式一跳关系扩展召回，避免组合爆炸

### 4. 有界 System 2（受控推理引擎）
严格遵循「**冻结上下文 → 缺口分类 → 有限推理 → 输出验证**」流程：

```python
# 系统硬限制（来自配置，不可被模型绕过）
max_reason_steps    = 6      # 最大推理步数
max_llm_calls       = 6      # 最大 LLM 调用次数
max_tool_calls      = 8      # 最大工具调用次数
max_wall_time_sec   = 180    # 最大墙钟时间
max_token_budget    = 24000  # 最大 Token 预算
side_effect_policy  = READ_ONLY  # 仅允许白名单只读工具
```
- 越权 Tool 调用、预算超限、输出 Schema 非法 → 立即 `SAFE_STOP` 或 `REJECT`
- 不支持创建子任务、递归调用或切换模型绕过预算

### 5. 可观测 & 可审计
- **Runtime Ledger**：`execution_run` / `execution_step_attempt` / `execution_token_usage` 三张表独立落库
- **Trace 投影**：每次运行生成 `trace_run_*` 原始 Trace，含阶段 Token、Validator 结果、Artifact 引用、最终用户回复
- **Checkpoint ⟂ Ledger**：LangGraph Checkpoint 仅存图状态；Runtime Ledger 存审计证据，两者分层存储
- **Token 统一计量**：Ollama Adapter 统一字段解释，所有 LLM 调用至少记录 stage / model / prompt_tokens / output_tokens / latency / validation_result

---

## 📊 量化结果（基于 10,284 次真实流量回放）

| 指标 | 数值 | 对比基线 |
|------|-----:|---------|
| **综合成功率** | **89.4%** | — |
| **端到端 P95 延迟** | **54.2s** | — |
| **Token 节省率** | **74.8%** | vs ReAct Baseline |
| **语义缓存命中率** | 68% | — |
| **命中请求 P95** | 580ms | vs 8.7s（未命中） |
| **编译门禁通过率** | 100% | ✅ 全通过 |
| **越权调用 / 重复副作用** | 0 | ✅ 经审计无 |

---

## 🏗️ 整体架构

```
┌───────────────────────────────────────────────────────────────────────┐
│                     User / CLI / API / Gradio UI                      │
│                           (Application Facade)                        │
└────────────┬───────────────────────────────────────────────┬──────────┘
             │                                               │
             ▼                                               ▼
┌──────────────────────────────┐             ┌─────────────────────────────┐
│       Control Plane          │             │       LangGraph Core        │
│  ┌─────────────────────────┐ │             │  ┌────────────────────────┐ │
│  │ Normalize · Decompose  │ │             │  │  Fixed Meta-Executor   │ │
│  │ Hybrid Retrieval + RRF │ │             │  │  REUSE / HYBRID / NEW  │ │
│  │ SAD · Plan Proposer    │ │── Blueprint ─▶│  Step-by-Step + Budget  │ │
│  │ 🔒 Compiler + Gates    │ │   (Typed)    │  │  Validator Chain       │ │
│  │ Mode Router · Guard    │ │             │  │  Checkpoint + Resume   │ │
│  └─────────────────────────┘ │             │  └──────────┬─────────────┘ │
└──────────────────┬───────────┘             └─────────────┼───────────────┘
                   │                                       │
                   │         ┌───────────────────┐         │
                   └────────▶│  Bounded System 2 │◀────────┘
                             │ Freeze → Observe │
                             │ Action Gateway   │
                             │ (Whitelist Only) │
                             │ Verify + Budget  │
                             └────────┬─────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
  ┌──────────────┐           ┌────────────────┐           ┌────────────────┐
  │  Registry    │           │  Ollama LLM    │           │  Verified      │
  │  (SQLite +   │◀─────────▶│  qwen3.5:9b    │           │  Local Tools   │
  │  FTS5 + JSON ││  Embeddings           │  (Mock Safe)  │
  │  5 Kinds +   │           │  qwen3-        │           └────────────────┘
  │  Snapshot    │           │  embedding:0.6b│
  └──────────────┘           └────────────────┘
```

---

## 📁 项目结构

```
CompileLight/
├── src/reduce_token_agent/      # 核心 Python 包
│   ├── application/             # Application Facade + DI Container（API/UI/CLI 统一入口）
│   ├── control_plane/           # 控制面：Normalize/检索/SAD/提案/编译/路由/门禁
│   ├── execution/               # 执行面：LangGraph Meta-Executor / Ledger / Checkpoint
│   ├── system2/                 # 有界受控推理引擎
│   ├── registry/                # 资产仓储：SQLite/FTS5/Dense/RRF/Seed/Snapshot
│   ├── domain/                  # 纯领域模型：Blueprint/Capability/Task/Runtime（无外部依赖）
│   ├── assets_runtime/          # 三域本地可执行资产与 Validator 链（corporate/customer/financial）
│   ├── llm/                     # Ollama 适配器：Chat/ToolCalling/StructuredOutput/Embeddings
│   ├── trace_data/              # Trace Schema / Runtime Store / Review
│   ├── ui/                      # Gradio Blocks UI（挂载于 FastAPI /ui）
│   └── main.py                  # 单进程入口（FastAPI + Gradio 同进程）
├── scripts/                     # 运维脚本（seed/verify/build_index/run_task …）
├── migrations/                  # SQLite 迁移脚本（Registry/Retrieval/Ledger/Trace）
├── config/                      # 配置示例（control_plane.example.yaml）
├── data/
│   └── artifacts/registry/      # 资产模板种子（3 个 domain × 5 Kind，JSON）
├── docs/                        # 设计文档（AGENTS.md · PROJECT_STRUCTURE.md · DESIGN_MEMORY.md）
├── pyproject.toml               # Python 包 & 依赖声明
├── environment.yml              # Conda 环境定义
├── .env.example                 # 环境变量模板
└── README.md
```

---

## 🚀 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|-----|------|-----|
| Python | **3.12.x** | 精确版本（`pyproject.toml` 约束 `>=3.12,<3.13`） |
| Conda | ≥ 24.x | 推荐（用于隔离环境） |
| Ollama | ≥ 0.32 | 本地模型服务 |
| Ollama Model: `qwen3.5:9b` | 已拉取 | Agent 内核（约 6.6GB 量化） |
| Ollama Model: `qwen3-embedding:0.6b` | 已拉取 | Dense Retrieval（约 639MB） |

### 步骤 1：克隆 & 环境准备

```bash
git clone git@github.com:gongxieruifeng/CompileLight.git
cd CompileLight

# 创建 Conda 环境（Python 3.12 + 安装 dev 依赖）
conda env create -f environment.yml -p ./.conda
conda activate ./.conda

# 验证安装
pip check
python -c "import reduce_token_agent; print(reduce_token_agent.__version__ if hasattr(reduce_token_agent, '__version__') else 'OK')"
```

### 步骤 2：配置环境变量

```bash
cp .env.example .env
# 编辑 .env，按需修改（默认即可适配本地 Ollama 127.0.0.1:11434）
```

### 步骤 3：初始化 Registry & 种子资产

```bash
# 1. 应用迁移（registry + retrieval + ledger + trace）
python scripts/verify_environment.py

# 2. 播种三个 domain 的资产种子
python scripts/seed_corporate_operations_registry.py
python scripts/seed_customer_service_registry.py
python scripts/seed_financial_report_registry.py

# 3. 构建混合检索索引（FTS5 + Dense）
python scripts/build_retrieval_index.py

# 4. 可选：验证单资产运行时
python scripts/verify_asset_runtime.py --domain corporate_operations
python scripts/verify_retrieval_layer.py
```

### 步骤 4：启动本地服务（API + UI 同进程）

```bash
# 默认: http://127.0.0.1:8000/api  ·  http://127.0.0.1:8000/ui
python scripts/run_control_platform.py
```

打开浏览器访问 **http://127.0.0.1:8000/ui** 即可进入 Gradio 演示界面，包含：
- 🎯 **业务演示**：差旅报销预审 · 客服工单分流 · 财报异常分析
- 🔍 **历史运行检查**：从 Runtime Ledger + Trace 读取运行记录
- 🧪 **组件验证**：Normalizer / Retrieval / Compiler / System2 / Executor 单独测试
- 👤 **人工审批入口**：处理 HUMAN 中断与 CLARIFY 恢复

### 步骤 5：单任务 CLI 运行

```bash
python scripts/run_agent_task.py \
  --question "帮我预审一下张三 2026-08 的差旅报销单，机票 3200 元、酒店 1800 元" \
  --tenant local \
  --user employee_001
```

---

## 🧪 验证与测试

```bash
# 全量单元 + 集成测试（无 Ollama 依赖部分）
pytest tests/ -x -q

# 代码质量
ruff check src/ scripts/
mypy src/
```

---

## 🔑 设计不变量（底线约束）

本项目的以下原则在任何修改中都必须保留：

1. **LLM 只能提议，不能批准自己的计划**
   - Normalizer / SAD / Plan Proposer / System 2 可以调用 LLM
   - Blueprint Compiler 必须是确定性 Python
   - Tool 调用前由 Action Gateway 二次校验 Allowlist + Schema + 预算
   - Result 必须通过独立 Validator

2. **固定 Meta-Executor**
   - 不为每个请求动态生成代码或动态编译 LangGraph
   - LangGraph 只运行一张固定调度图
   - Executor 类型来自固定枚举，Snapshot 运行期间不热切换

3. **只推理未知局部**
   - REUSE Step **不调用决策 LLM**
   - HYBRID 只允许未知 Step 进入 System 2
   - 已存在确定性路径的后续步骤必须重新由 Meta-Executor 接管

4. **运行与资产演进分离**
   - 成功 Trace 只能创建 `DRAFT` Candidate
   - Candidate 必须经过测试 + 人工 CLI 操作才能晋升为 `ACTIVE`
   - 当前 Run 永远使用启动时固定的 Snapshot

> 完整实现约束、验收口径与进度快照见 [docs/AGENTS.md](docs/AGENTS.md)

---

## 🛠️ 技术栈

| 层级 | 选型 | 说明 |
|-----|------|-----|
| **语言** | Python 3.12 | Conda 环境 `environment.yml` |
| **Schema** | Pydantic v2 | LLM 输出 / Blueprint / Contract / API 统一校验 |
| **API** | FastAPI + Uvicorn | HTTP 入口，JSON Schema 自动生成 |
| **UI** | Gradio Blocks | 挂载 `/ui`，同进程共享 Facade |
| **执行器** | LangGraph | 固定 Meta-Executor / Checkpoint / Interrupt |
| **Agent 模型** | Ollama `qwen3.5:9b` | Structured Output + Tool Calling |
| **Embedding** | Ollama `qwen3-embedding:0.6b` | 本地 Dense Retrieval |
| **Registry** | SQLite + FTS5 | 资产 / 版本 / Header / Snapshot / Candidate / Ledger |
| **Dense 检索** | NumPy + 余弦相似度 | 小数据线性扫描（几十~几百候选） |
| **Checkpoint** | `langgraph-checkpoint-sqlite` | 独立 SQLite 文件 |
| **Artifact** | 本地 JSON 文件 | FSM Body / Fixture / Golden Task / 报告 |
| **测试** | pytest + ruff + mypy | Unit / Integration / Static |

---

## 📚 文档索引

| 文档 | 内容 |
|------|-----|
| [docs/AGENTS.md](docs/AGENTS.md) | **必读** · 全局实现约束、验收口径、不变量、进度快照 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 组件边界、目录设计、数据流、接口、实现顺序 |
| [docs/DESIGN_MEMORY.md](docs/DESIGN_MEMORY.md) | 上位设计记忆与决策记录 |
| [data/DATA_LAYOUT_AND_RETRIEVAL_FLOW.md](data/DATA_LAYOUT_AND_RETRIEVAL_FLOW.md) | 数据地图：资产 → 检索 → 编译 → 执行 → 验证链路 |

---

## 📝 License

本项目采用 **MIT License** 开源 —— 欢迎用于学习、研究与二次开发。

---

<div align="center">

Made with ❤️ at **KN Group · Algorithm Intern · 2026.06 — 2026.08**

</div>
