# CompileLight 项目主页模板

> 本文件用于个人主页构建 Agent 解析，整合项目 GitHub 地址、README 与项目详细介绍。

---

## 项目基本信息

| 字段 | 值 |
|------|-----|
| **项目名称** | CompileLight |
| **副标题** | 轻量级智能编译守卫 Agent |
| **一句话简介** | 让已知子目标确定性复用，让未知缺口在有界内安全推理 |
| **GitHub 仓库** | [https://github.com/gongxieruifeng/CompileLight](https://github.com/gongxieruifeng/CompileLight) |
| **README 链接** | [https://github.com/gongxieruifeng/CompileLight/blob/main/README.md](https://github.com/gongxieruifeng/CompileLight/blob/main/README.md) |
| **详细介绍链接** | [https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md](https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md) |
| **职位背景** | KN Group · 算法实习生 · 2026.06 — 2026.08 |
| **开源协议** | MIT License |
| **主要语言** | Python 3.12 |
| **可见性** | ✅ 公开仓库 |

---

## 主页卡片展示内容

### 项目卡片（用于主页项目列表）

**CompileLight — 轻量级智能编译守卫 Agent**

针对企业客服 Agent 在高频任务中重复检索、推理与执行不可审计的痛点，设计「Trace → Registry → Retrieval → Control → Execution」五阶段闭环架构。核心理念：**LLM 只提议，代码批准**。已知子目标优先复用确定性资产（0 Token 执行），未知缺口触发有界 System 2 受控推理，全程编译门禁可审计。

🔗 [GitHub 仓库](https://github.com/gongxieruifeng/CompileLight) · 
📖 [完整介绍](https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md) · 
📋 [技术文档](https://github.com/gongxieruifeng/CompileLight/blob/main/README.md)

---

### 核心标签（用于主页技术标签云）

```
LangGraph · FastAPI · Gradio · Ollama · Pydantic v2 · SQLite FTS5
```

---

### 量化亮点（用于主页数据展示区）

| 指标 | 数值 | 说明 |
|------|-----:|------|
| 综合成功率 | **89.4%** | 10,284 次真实流量回放 |
| Token 节省率 | **74.8%** | 对比 ReAct 基线 |
| P95 延迟 | **54.2s** | 端到端 |
| 语义缓存命中率 | **68%** | 命中后 P95 降至 580ms |
| 编译门禁通过率 | **100%** | 全量审计通过 |
| 越权调用 | **0** | 经审计无 |

---

### 五大核心亮点（用于主页特性展示区）

#### 1. LLM 提议 · 代码批准
LLM 产出的每一步计划必须经由确定性 Python 编译器在 Schema / 权限 / 风险 / 预算四道门禁下校验通过后方可执行，杜绝越权调用。

#### 2. 三模式路由 · 确定性优先
基于 LangGraph 固定 Meta-Executor，支持 REUSE（0 Token）/ HYBRID（单缺口推理）/ NEW（受控探索）三种模式自动路由。

#### 3. 资产工程 · 生命周期治理
5 类固定 Kind 资产体系 + Header 召回 + Contract 匹配两级索引 + DRAFT → ACTIVE 生命周期 + Snapshot 视图冻结。

#### 4. 有界 System 2 · 受控推理引擎
硬限制 6 步推理 / 6 次 LLM / 8 次工具调用 / 24k Token，白名单只读工具，超限立即安全中止。

#### 5. 全链路可审计
Runtime Ledger 三表独立落库 + Trace 投影逐层留痕 + Token 统一计量，运行状态完全可回放。

---

### 架构图引用（用于主页架构展示区）

| 图片 | GitHub Raw 链接 | 说明 |
|------|-----------------|------|
| 控制平面 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/Dify.png` | Normalize → 检索 → SAD → 编译 → 路由 → 执行 |
| 执行平面 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/LangGraph.png` | 固定 Meta-Executor Step 调度循环 |
| 受控推理 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/System2.png` | 冻结上下文 → 缺口分类 → 受控推理 → 输出验证 |
| 资产仓储 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/Register.png` | Registry 三层架构 |
| 资产生命周期 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/Evolve_backbone.png` | DRAFT → VALIDATING → SHADOW → CANARY → ACTIVE → RETIRED |
| 双循环驱动 | `https://raw.githubusercontent.com/gongxieruifeng/CompileLight/main/assets/Backbone_dada_Transform.png` | System Backend Driven Loop |

---

### 技术栈表格（用于主页技术栈展示区）

| 层级 | 选型 |
|------|------|
| 语言 | Python 3.12 |
| 执行框架 | LangGraph |
| Web 框架 | FastAPI + Gradio |
| Agent 模型 | Ollama qwen3.5:9b |
| Embedding | Ollama qwen3-embedding:0.6b |
| 检索 | FTS5 + Dense + NumPy + RRF |
| 数据存储 | SQLite |
| Schema 校验 | Pydantic v2 |

---

## 主页模板 HTML 参考

```html
<!-- CompileLight 项目卡片模板 -->
<div class="project-card">
  <h3>CompileLight — 轻量级智能编译守卫 Agent</h3>
  <p class="project-desc">
    针对 Agent 重复推理与执行不可审计痛点，设计「Trace → Registry → Retrieval → Control → Execution」五阶段闭环。
    核心理念：LLM 只提议，代码批准。Token 节省 74.8%，成功率 89.4%。
  </p>
  <div class="project-metrics">
    <span class="metric">成功率 89.4%</span>
    <span class="metric">Token ↓ 74.8%</span>
    <span class="metric">P95 54.2s</span>
  </div>
  <div class="project-tags">
    <span class="tag">LangGraph</span>
    <span class="tag">FastAPI</span>
    <span class="tag">Ollama</span>
    <span class="tag">SQLite FTS5</span>
    <span class="tag">Pydantic v2</span>
  </div>
  <div class="project-links">
    <a href="https://github.com/gongxieruifeng/CompileLight">GitHub</a>
    <a href="https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md">项目介绍</a>
    <a href="https://github.com/gongxieruifeng/CompileLight/blob/main/README.md">技术文档</a>
  </div>
</div>
```

---

## 链接汇总

| 用途 | 链接 |
|------|------|
| **GitHub 仓库首页** | [https://github.com/gongxieruifeng/CompileLight](https://github.com/gongxieruifeng/CompileLight) |
| **项目详细介绍（面试官向）** | [https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md](https://github.com/gongxieruifeng/CompileLight/blob/main/CompileLight.md) |
| **技术 README（开发者向）** | [https://github.com/gongxieruifeng/CompileLight/blob/main/README.md](https://github.com/gongxieruifeng/CompileLight/blob/main/README.md) |
