# CompileLight — 轻量级智能编译守卫 Agent

> **职位**：KN Group · 算法实习生 · 2026.06 — 2026.08  
> **GitHub**：[github.com/gongxieruifeng/CompileLight](https://github.com/gongxieruifeng/CompileLight)

---

## 项目概述

针对企业客服 Agent 在高频任务中 **重复检索、推理与执行不可审计** 的痛点，设计并实现了「**Trace → Registry → Retrieval → Control → Execution**」五阶段闭环架构的轻量级智能编译守卫 Agent。核心思想是将 LLM 的角色从"执行者"收窄为"规划提议者"，所有执行决策由确定性编译闸门批准，已知子目标优先复用资产，未知缺口触发有界受控推理，在保证可控性的同时显著降低推理开销。

---

## 核心亮点

### 🔒 LLM 提议 · 代码批准
提出「**LLM 只提议，代码批准**」原则。LLM 产出的每一步计划都必须经由确定性 Python 编译器在 Schema / 权限 / 风险 / 预算四道门禁下校验通过后方可执行，从根本上杜绝了模型越权调用和不可审计行为。

### ⚡ 三模式路由 · 确定性优先
基于 LangGraph 实现固定 Meta-Executor，支持 REUSE / HYBRID / NEW 三种执行模式的自动路由：
- **REUSE**（覆盖率=100%）：全步骤 **0 Token 确定性执行**，轻量缺口（格式/枚举/默认值）内置零 Token 修正
- **HYBRID**（覆盖率 40%~100%）：已知步骤沿用 FSM/Tool，仅单个缺口进入有界 System 2，结果回接原链
- **NEW**（覆盖率<40%）：受控探索模式，严格冻结上下文、限制工具白名单、预算门禁防止无限循环

### 🏗️ 资产工程 · 生命周期治理
设计 5 类固定 Kind（PRIMITIVE_TOOL / FSM_SHARD / WORKFLOW_SKELETON / ADAPTER / VALIDATOR）的资产体系，建立 **Header 召回 + Contract 匹配** 两级索引与 DRAFT → ACTIVE 完整生命周期管理。视图冻结机制确保每次 Run 使用启动时固定的 Snapshot，执行中不热切换版本。

### 🧠 有界 System 2 · 受控推理引擎
严格遵循「冻结上下文 → 缺口分类 → 有限推理 → 输出验证」流程，硬限制 6 步推理 / 6 次 LLM 调用 / 8 次工具调用 / 24k Token 预算，所有非白名单工具调用、预算超限、Schema 非法均立即安全中止。

### 📊 语义缓存 · 历史 Blueprint 复用
引入 Hot Cache 语义缓存层，对相似意图直接复用历史编译通过的 Blueprint，避免重复 LLM 规划。

---

## 量化成果

基于 **10,284 次真实流量回放** 的评测数据：

| 指标 | 数值 | 对比基线 |
|------|-----:|---------|
| **综合成功率** | **89.4%** | — |
| **端到端 P95 延迟** | **54.2s** | — |
| **Token 节省率** | **74.8%** | vs ReAct Baseline |
| **语义缓存命中率** | **68%** | — |
| **命中请求 P95** | **580ms** | vs 8.7s（未命中） |
| **编译门禁通过率** | **100%** | 全量通过 |
| **越权调用 / 重复副作用** | **0** | 经审计无 |

---

## 架构设计

```
用户请求 → Application Facade
    │
    ├── Control Plane（确定性 Python 控制流）
    │   ├── Normalize（身份/实体/风险）
    │   ├── 硬过滤 & 混合召回（FTS5 + Dense + RRF 融合）
    │   ├── SAD 语义对齐
    │   ├── Blueprint 提议（受候选白名单约束）
    │   └── 🔒 确定性编译门禁 → REUSE/HYBRID/NEW/REJECT
    │
    ├── LangGraph Meta-Executor（固定调度图）
    │   ├── Step 调度 + Validator 链 + Checkpoint
    │   └── Runtime Ledger（Token/状态/成本审计）
    │
    ├── Bounded System 2（有界受控推理）
    │   ├── 冻结上下文 → 缺口分类
    │   ├── 白名单工具 + 预算门禁
    │   └── 输出验证 → 安全回接
    │
    └── Registry（SQLite + FTS5）
        ├── 5 类资产 + Snapshot 版本冻结
        └── DRAFT → ACTIVE 生命周期治理
```

---

## 技术栈

| 层级 | 选型 | 说明 |
|-----|------|-----|
| **语言** | Python 3.12 | 主语言 |
| **执行框架** | LangGraph | 固定 Meta-Executor / Checkpoint / Interrupt |
| **Web 框架** | FastAPI + Gradio | API + UI 同进程挂载 |
| **模型** | Ollama qwen3.5:9b | 本地 Agent 内核（结构化输出 + 工具调用） |
| **检索** | FTS5 + Embedding + NumPy | 稀疏 + 稠密混合召回 + RRF 融合 |
| **数据存储** | SQLite | 资产 Registry / Runtime Ledger / Checkpoint |
| **Schema** | Pydantic v2 | 全链路类型校验 |

---

## 项目亮点总结

1. **架构创新**：首次在企业 Agent 场景中系统性实践「编译守卫」模式，将 Agent 的规划与执行解耦，实现确定性执行与有界推理的可控平衡
2. **工程落地**：基于单一 Python 进程 + SQLite 即可运行的轻量 PoC，不依赖微服务或外部基础设施，可在本地桌面环境完整演示
3. **可审计性**：编译门禁全量通过、Runtime Ledger 逐层留痕、运行时状态完全可回放，解决了 Agent 执行"黑盒"问题
4. **量化验证**：在过万次真实流量回放中，综合成功率近 90%，Token 节省超 70%，为同类 Agent 系统提供了可参考的评测基线

---

**GitHub 仓库**：[https://github.com/gongxieruifeng/CompileLight](https://github.com/gongxieruifeng/CompileLight)
