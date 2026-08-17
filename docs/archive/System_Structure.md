### Agent 编排范式

> **定义**：Agent 编排架构的四种基本范式：线性链（Chain）、有向无环图（DAG）、事件驱动（Event-Driven）、自治协作（Autonomous）。实际系统通常是多种范式的混合。

| 范式 | 特点 | 适用场景 | 代表实现 | 局限 |
| :--- | :--- | :--- | :--- | :--- |
| **线性链 (Chain)** | 固定顺序，简单可靠 | 单任务 Pipeline | LangChain Chain, OpenAI Agents SDK | 不支持分支 |
| **DAG (有向图)** | 并行+依赖，高效 | 多步骤编排 | LangGraph, ControlFlow | 需预定义拓扑 |
| **事件驱动 (EDA)** | 解耦+实时，灵活 | 响应式 Agent | Inngest, Trigger.dev | 调试复杂 |
| **自治协作 (Autonomous)** | Agent自决策，弹性 | 复杂探索任务 | AG2, CrewAI, Google A2A | 可控性弱 |


Q1: 当新任务只有 60% 与历史经验匹配时，如果将之前的整个 FSM（有限状态机）作为一个黑盒直接调用，必然会失败。

解决这个问题的核心在于**从“宏观工作流固化”转向“原子技能的动态编排”**。

* **技能原子化（Micro-Skills）：** 不要将端到端的长流程（如“查政策->创工单->发邮件”）直接存为一个不可拆分的节点。相反，应将其拆分为独立的原子工作流或子图（Sub-graphs）。
* **生成式技能组合（Generative Skill Composition）：** 当新任务到来时，Agent 的 System 2 不应该只做简单的“全文检索”，而应作为一个**编排器（Composer）**。它可以检索到一个 60% 匹配的经验 A（如“创工单”），以及一个 40% 匹配的经验 B（如“日历预约”），并在单次推理中生成一个有向无环图（DAG）式的执行计划，决定哪些原子技能被激活、执行次数以及执行顺序。

---
Q2: 随着经验库的增长，如果不加干预，系统会遭遇“技能灾难”（Skill bloat）——过多的冗余经验反而会导致检索准确率下降、Token 消耗增加，甚至引发模型幻觉。

* **能力树与递归分类（Capability Tree）：** 将技能组织成树状结构，而不是扁平的向量库。将相似的经验通过节点级别的递归分类进行管理，方便 Agent 高效发现和调用。
* **经验合并与泛化（Skill Merging）：** 设立一个定期的后台进程（类似于睡眠时的记忆巩固）。当系统发现某几个 FSM 在执行路径上高度重合，仅仅是具体参数不同时，使用 LLM 将它们合并为一个带有更广泛参数接口的通用 FSM。
* **衰减与淘汰机制：** 引入类似强化学习中的机制，给每条经验附带一个“置信度分数”。每次成功复用加分，执行报错（例如 API 变更导致 FSM 失效）扣分。分数低于阈值的经验自动退回 System 2 进行重新推理或直接淘汰。
---
Q3: 如果不解决**存储结构**和**高效精确匹配**的问题，整个系统就会变成一个检索缓慢、错误率极高的“垃圾堆”。
**附生问题**：现实业务往往非常复杂（例如：“*帮我下载报表，转换格式，然后生成可视化图表发给团队*”），这需要连续调用多个工具协同作战 ，这样LLM的切割粒度可能和向量库中的粒度不一致，导致库中明明有可用的工具，但是匹配不到

> **Example**：比如大模型把“下载文件”这个动作，过度拆解（Over-decomposition）成了“建立网络连接”、“发送 HTTP 请求”、“写入本地硬盘”三步 。可你们的工具库里其实只有一个现成的叫 `http-fetch`（HTTP下载）的封装工具 。由于拆出的步骤太碎，去向量库里检索时，就会完美错过这个真正的工具，导致全盘崩溃 。标准大模型的步长拆解正确率（DA）其实只有 **51.0%** 。

**核心洞察：** “向量检索 + 结构化元数据 + 轻量级重排”的混合架构、 **SKILLWEAVER** 架构，将整个流水线分为三步：**Decompose（拆解）➔ Retrieve（检索）➔ Compose（组装）**

---
协作能力 —— 在你的架构下，**继续深耕“Dify + LangGraph”，无需更换底层框架**。

![ChatGPT Image 2026年7月8日 10_50_32](assets/ChatGPT%20Image%202026%E5%B9%B47%E6%9C%888%E6%97%A5%2010_50_32.png)

* **LangGraph 的绝对优势：** LangGraph 原生支持将状态机持久化（Checkpointer），且极度擅长处理循环和确定性的工具调用序列。对于你构想的“子流程执行器”，LangGraph 可以将拆分后的原子技能定义为不同的 Node，并通过条件边（Conditional Edges）实现动态组装。
* **架构分工：** Dify 继续作为你的大脑（System 2）、统一门户和 RAG 引擎；而 LangGraph 彻底转型为无脑但高度可靠的“肌肉记忆引擎”（System 1）。你可以通过 LangGraph 的 `Command` 或 `StateGraph` 动态加载通过 Dify 组合好的 JSON 经验模板，实现 60/40 技能的动态拼接。


### Q1的解决方案：
1. [SkillFlow](https://github.com/ZhangZi-a/SkillFlow) —— DAEF 骨架、补丁修复、反代码膨胀 武汉大学网络空间安全学院

核心思想：DAEF（领域无关执行流）+ 原子 FSM（Micro Sub-graphs）

![](assets/17836655934633.jpg)
![](assets/17836657243304.jpg)

**解决思路：**
不要把具体的工具调用链作为最小单位，而是将经验切分为两个层级：

1. **宏观骨架（Macro Skeletons / DAEF）：** 沉淀高度抽象的逻辑拓扑。例如 `[信息检索] ➔ [数据规范化] ➔ [系统写入] ➔ [通知分发]`。这个骨架不绑定具体工具，只定义数据流向。
2. **原子 FSM（Micro Sub-graphs）：** 沉淀具体的、高内聚的微型工作流。比如“查询 Jira 并提取核心字段”是一个原子 FSM，“发送并校验内部邮件”是另一个原子 FSM。


#### 动态编排：在 LangGraph 中实现“乐高式”的图拼接

LangGraph 需要具备**子图动态拼接（Dynamic Sub-graph Routing）** 的能力。

* **60% 旧任务：** Agent 将这部分直接映射到 LangGraph 已经固化好的高频 `Sub-graph`（即那个已验证的经验节点），这部分执行是 **0 Token 消耗**的“肌肉记忆”。
* **40% 新任务：** Agent 使用极少量的 Token，规划出这 40% 的执行流。
* **运行态合成：** 将那 60% 的黑盒 FSM 与 40% 的新路径，动态编译成一张临时的 LangGraph 状态图去运行。如果这次拼接运行成功，这个“新拼图”的关联关系会被记录下来，成为下一次的候选经验。

##### 实现运行时 LangGraph 动态拼合

**核心思路：设计一个“元解释器工作流（Meta-Router Graph）”** ，即在 LangGraph 侧，部署一个通用循环图，它接受一个**执行蓝图（Blueprint）**，然后负责按蓝图调度。

**具体拼合流程如下：**

1. **意图解析与检索（极轻量 LLM 消耗）：**
用户输入新任务。Dify 中的 Agent 去检索经验库，发现没有 100% 匹配的长流程，但检索到了一个 60% 匹配的 `FSM_查询 Jira 核心字段`，以及一个可用的 DAEF 骨架。
2. **生成动态蓝图（Blueprint Generation）：**
Agent 的 System Prompt 会引导它基于检索到的 DAEF 骨架和原子 FSM，填补那缺失的 40%。它会输出一个结构化的执行数组（Blueprint）：
```json
[
  {"step": 1, "type": "fsm", "name": "FSM_查询Jira核心字段", "inputs": {"ticket_id": "xxx"}},
  {"step": 2, "type": "tool", "name": "临时推理_调用企业微信发消息", "inputs": {"msg": "{{step_1.output}}"}},
  {"step": 3, "type": "fsm", "name": "FSM_写入本地日志", "inputs": {"status": "success"}}
]

```

3. **LangGraph 元解释器执行（动态组装）：**
Dify 将这份 Blueprint 发给 LangGraph。LangGraph 内部的逻辑非常固定：
* **读取 Step 1：** 发现是 `type: fsm`。LangGraph 的当前节点会动态加载（Load）对应的子图配置，像调用普通函数一样，确定性地执行这个 FSM，全程 **0 LLM Token 消耗**。执行完毕，结果放入全局上下文。
* **读取 Step 2：** 发现是 `type: tool`（那 40% 的未知部分）。此时触发普通的工具调用节点，执行企业微信发消息动作。
* **读取 Step 3：** 再次遇到 FSM，加载执行，直到蓝图跑完。

#### Candidate To Draft —— FSM 的切分与构建

当你的通用 Agent（系统二）成功完成了一次高成本的完全推理任务后，会留下一串长长的执行轨迹（Trace）。这时候不要直接把整串轨迹存下来，而是按以下步骤处理：
* **输入输出边界探测：** 后台脚本分析这串轨迹，寻找“数据形态发生根本改变”的节点。例如，前面 3 步都在查询各类 API 组装上下文（获取信息），第 4 步开始将数据转化为特定格式（处理信息），最后两步调用邮件和 Jira 接口（执行输出）。
* **提取原子 FSM：** 脚本将上述高内聚的步骤（如“查询各类 API 组装上下文”）打包，剥离掉具体的业务参数，生成一个独立的 `Sub_Graph_Template`（JSON 格式）。这就形成了一个“肌肉记忆”模块，比如命名为 `FSM_Data_Gathering`。
* **抽象 DAEF 骨架：** 脚本同时提取出这次任务的宏观拓扑，例如生成一个骨架：`[FSM_Data_Gathering] ➔ [LLM_Decision] ➔ [FSM_System_Write]`。
* **入库注册：** 这些 FSM 模板和 DAEF 骨架被存入向量数据库。每个 FSM 都会带有明确的描述（Description）和所需的入参/出参接口定义。


### Q3的解决方案：
#### Compositional Skill Routing 阿里团队
核心洞察： **大模型组合工具失败，通常不是因为选不对工具，而是因为它的“拆题刀法”不对，导致拆出的步骤跟工具库里的工具完全对不上（粒度不匹配）** 

解决的是“复合技能路由（Compositional Skill Routing）”问题 ，提出的 **SKILLWEAVER** 架构，将整个流水线分为三步：**Decompose（拆解）➔ Retrieve（检索）➔ Compose（组装）** 

```
用户复合请求 ──➔ 【1. Decompose】 ──➔ 拆出原子子任务 JSON 阵列
                             │
                             ▼ （利用 SAD 提示词，注入 Pass-1 的 15 个工具线索进行对齐修正）
                    【2. Retrieve】 ──➔ FAISS 向量检索，锁定具体候选工具
                             │
                             ▼ 
                    【3. Compose】 ──➔ 检查接口兼容性，编织成可并行的 DAG 执行图

```

![](assets/17839273252830.jpg)


#### Skill-Aware Decomposition (SAD, 技能感知拆解)

为了纠正大模型的刀法，提出 **SAD 机制**——一种“先盲猜、调线索、再精准切刀”的输入端反馈循环 ：

1. **Pass 1（盲切）**：大模型先不管三七二十一，用直觉把用户请求粗糙地拆成几步 。
2. **调线索（Hinting）**：系统拿着这几个粗糙的步骤，去向量库（FAISS）里快速拉出前 **15** 个最相关的工具名字和简介，作为“线索集（``\mathcal{H}``）” 。
3. **Pass 2（精准切刀）**：系统把这 15 个工具线索和最初的用户请求重新打包喂给大模型：*“请参考这些我们实际拥有的工具，重新切刀拆解任务！”* 

**预期**：仅需这一次闭环迭代，拆解正确率（DA）直接从 **51.0%** 暴涨到 **67.7%** ，且由于精准路由，帮后面的打工智能体省掉用于规划的 Prompt 上下文消耗


#### 解耦 —— 实施 FSM 状态机切片化（Sharding） —— 由 SkillFlow 完成
将状态机打散，借助 SkillFlow 以 **中等粒度的“原子功能子图（Sub-goal FSM Shards）”** 作为经验沉淀的基本单元 。例如拆成：`【标准 Jira 工单创单子图】`、`【标准设备数据提取子图】`、`【标准团队钉钉通知子图】`

#### 前置的 SAD 工作流拆解层（发生于 Dify 编排层）
> 📥 **用户输入复杂新任务**：“*帮我提取下故障服务器 A 的底层错误码（系统没有这部分的固定 FSM 脚本），然后用 IT 团队标准格式去 Jira 创个单，最后在群里发个邮件通知。*”
> （这个任务里，Jira 创单和发邮件占了 60% 确定性流程，但提取错误码占了 40% 的未知探索）

系统收到请求后，不直接去匹配一整套历史大工作流，而是启动 **SAD 拆解循环** ：

1. **第一标（盲切）**：Dify 让一个速度极快的轻量模型把任务切成三段描述。
2. **拉取线索（Hinting）**：Dify 拿着这三段描述，去你们的 `Agent_Experience_Library`（经验库）里向量拉出前 15 个最接近的原子 FSM 子图名或散装工具描述。
3. **第二刀（对齐对齐）**：大模型看到了库里有躺着现成的 `create_jira_ticket`（创建Jira工单）和 `send_email`（发送邮件）这两个子图名字。它立马修正自己的拆解边界，吐出精准的结构化 JSON 步骤阵列 ：
> * `Step 1`：从自然语言或日志中提取服务器 A 的特征（定义为：全新探索/System 2 慢思考部分）。
> * `Step 2`：调用现成的 `create_jira_ticket` 经验子图（定义为：REUSE 复用部分）。
> * `Step 3`：调用现成的 `send_email` 经验子图（定义为：REUSE 复用部分）。



### Dify Platform Operating Procedure
![Dify](assets/Dify.png)

#### 执行流程
1. **Normalize**：提取租户、身份、时间基准、业务实体、数据级别、风险等级；缺失关键身份信息直接澄清。
2. **粗拆任务状态**：得到最少数量的高层子目标与期望中间状态，不拆到 HTTP 内部动作。
3. **硬过滤**：先按租户、ACL、状态、环境、工具可用性、风险、Schema 版本过滤技能。
4. **混合召回**：稀疏、稠密、元数据和 Capability Graph 分别召回，之后RRF融合之后，Rerank最高的Top N
5. **SAD 一次对齐**：只给模型候选 Header 与 Contract 摘要，重新调整子目标粒度。
6. **蓝图提议**：LLM 只能从候选 ID、允许的 Step 类型与版本快照中选择，输出结构化 JSON。
7. **确定性编译**：执行第 5.3 节的硬门禁。最多允许一次带错误码的修复提议；仍失败则转 NEW/人工。
8. **固定元解释器执行**：根据依赖选择 Ready Step，执行、验证、写账本，再推进下一步。
9. **失败分流**：可重试错误走策略；业务拒绝走显式分支；不可逆步骤失败走补偿/人工；禁止静默让 LLM 改图后继续。
10. **通过 Guard 安全验证之后结构化输出**
11. **Trace 入库**：保存结构化事件，不默认保存完整思维链；敏感输入脱敏或仅存引用。

#### 1. Task Normalizer
它把自然语言请求转为规划所需的结构化上下文，Normalizer 不负责制定工具调用序列。它只把“用户说了什么”转为“系统必须满足什么”。

#### 2. Capability Retrieval
它从 Registry 的 Route Header 中召回候选能力，而不是直接读取所有技能执行体。只有进入最终候选集的资产才加载完整 Contract；只有被 Blueprint 固定引用的资产才加载执行体。

召回信号包括：
- Sparse/BM25：工具名、系统名、错误码、业务术语；
- Dense Vector：语义相似子目标；
- Metadata：租户、环境、风险、领域、状态；
- Capability Graph：前置依赖、兼容、替代、验证器与 Adapter。


#### 3. SAD Alignment
SAD 采用一次反馈式拆解，第一次按任务语义粗拆子目标，用粗拆结果检索实际存在的能力 Header；
将 Header 作为“可用能力词表”；第二次调整边界，避免过度拆解或欠拆解；保留所有未覆盖目标，禁止为了匹配库中能力而删除用户需求。

SAD 默认只迭代一次。再次无法对齐时转 System 2 或人工澄清，不能进入无限拆解循环。

#### 4. Plan Proposer
Plan Proposer 由 LLM 实现，它只能“提议计划”，没有最终执行权
- 从当前 Registry Snapshot 中选择可见的固定版本资产；使用已定义的 Step 类型；输出结构化 Blueprint；
- 对未覆盖目标显式使用 `reason`、`extract` 或 `human`；
- 给出输入绑定、依赖和期望输出 Schema。


#### 5. Blueprint Compiler
Compiler 是普通确定性代码，负责：JSON Schema、Step/Dependency/DAG、、输入输出类型、最大步数、LLM、时间和成本预算、受控循环的最大迭代次数等

Compiler 未通过的 Blueprint 不允许进入 LangGraph。LLM 最多根据结构化错误修复一次，仍然失败则进入 NEW、澄清或拒绝。

#### 6. Mode Router

Router 不再依据单一向量分数决定路径，每个子目标的覆盖不只由语义分数决定：

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

| 模式 | 条件 | 行为 |
| --- | --- | --- |
| `REUSE` | 所有必需子目标都有通过 Contract 的确定性路径 | 执行阶段不逐步调用 LLM 做决策 |
| `HYBRID` | 部分目标可复用，未知部分在风险和预算内可控 | 只对未知 Step 使用抽取、受限 Reason 或 Human |
| `NEW / CLARIFY` | 无安全路径、关键参数歧义、越权或风险过高 | 完整 System 2、询问用户或拒绝执行 |

| 未知类型 | 示例 | 正确处理 |
| --- | --- | --- |
| Value Gap | 用户说“明天下午”，缺少 ISO 时间 | `extract`：规则/NER 优先，结构化 LLM 兜底，Schema 校验；仍歧义则询问 |
| Adapter Gap | 上游输出 `ticket_url`，下游要求 `message.text` | 只调用已注册、已测试的 Adapter；不存在时转 System 2 Candidate，不能线上生成任意代码 |
| Capability/Logic Gap | 需要从一个新日志系统读取并判断故障 | `reason`：受限工具集合、最大步数、输出 Schema、Validator、权限与审计；高风险则人工 |








### LangGraph Platform Operating Procedure
![LangGraph](assets/LangGraph.png)

#### LangGraph 执行平面

LangGraph 不为每次请求重新编译一张临时图，而是运行固定 Meta-Executor：

```text
SELECT READY STEP
  -> DISPATCH
  -> VALIDATE OUTPUT
  -> LEDGER + CHECKPOINT
  -> NEXT / COMPENSATE
  -> SELECT READY STEP
```

支持的执行器类型：`FSM`：版本固定的原子状态机子图；`TOOL`：单一注册工具；`EXTRACT`：规则/NER/结构化 LLM 参数抽取；`ADAPTER`：已注册、已测试的 Schema 转换；`REASON`：受限工具、受限步数、受限 Token 的 System 2；`HUMAN`：审批、补充输入或高风险确认。

每个 Step 的执行策略：
1. 读取版本固定的 Contract；
2. 校验前置条件；
4. 执行；
5. 校验 Output Schema 和业务 Validator；
6. 写入 Step 状态、成本、错误和 必要引用；
7. 推进、重试、补偿或暂停。

注意⚠️：Checkpoint 解决“恢复到哪里”，Compensate 解决“外部写操作是否已经发生”








### System2 Platform Operating Procedure
![System2](assets/System2.png)


**System 2 不是一个拥有无限工具权限、可以无限循环的通用 Agent，而是被 Blueprint、Compiler、ACL、预算、Schema 和 Validator 包围的受控推理执行单元。**

#### System 2 在本项目中的职责

System 2 只处理三类无法由现有确定性资产直接完成的问题：

1. **Unknown**：Registry 中没有能够覆盖某个必需子目标的 FSM 或 Tool 组合
2. **Ambiguous**：当前输入存在业务歧义
3. **Exceptional**：执行过程中出现了不能由既有重试、补偿或确定性错误分支处理的异常


#### 两种调用形态

| 形态 | 发生时机 | System 2 做什么 | 不做什么 |
| --- | --- | --- | --- |
| Planning-time System 2 | HYBRID/NEW 计划生成或 Compiler 返回结构化错误时 | 在候选资产白名单和固定 Snapshot 内提议 Blueprint；最多进行一次受限修订 | 不自我批准计划，不绕过 Compiler |
| Runtime System 2 | Meta-Executor 调度到 `reason` Step 时 | 在单个未知子目标内执行有界 Observe/Act 循环，产生类型化 Artifact | 不改动其他 Blueprint Step，不扩展 Tool Allowlist |

NEW 并不表示把整条请求交给一个无限 Agent Loop。NEW 表示现有资产无法安全覆盖任务，因此需要 System 2 提议新的受控计划；这个计划仍然必须经过 Blueprint Compiler，运行时仍由固定 Meta-Executor 执行。


#### 执行流程
#### 触发时机
`HYBRID — CAPABILITY GAP`：部分目标已经由 Active FSM 覆盖，但至少一个目标缺少能力或逻辑。
`NEW — NO SAFE COVERAGE`：比如Blueprint 无法通过编译、任务属于从未覆盖的新业务族。
`CLARIFY — AMBIGUOUS INPUT`：危险操作模糊：金额、支付账户、退款范围；删除对象和批量操作范围；
`RUNTIME EXCEPTION`：不可修复的运行错误都会重新触发 System 2

#### Freeze Context

进入 System 2 时先冻结当前运行上下文

* Task State：只提供完成当前未知子目标所需的最小状态，不应把完整会话、所有历史 Trace 或无关 Skill Body 全部塞入 Prompt。
* Snapshot：System 2 固定使用 Blueprint 中的 `registry_snapshot_id`，回放时能够恢复相同的可见资产集合。
* Caller ACL：ACL 来自已认证身份和服务身份，不由 LLM 生成，System 2 只能缩小权限，不能扩大权限
* Evidence：Evidence 是结构化事实，比如 LangGraph 携带的 Context 信息

#### Classify Gap
在调用 Reason Model 前，系统必须先判断缺口类型

* 前面介绍的三种，即：Value、Adapter、Logic Gap
* Policy Denied：Policy Denied 是终止条件，不是推理问题
> 例如当前用户没有 `jira:issue:create` 权限时，即使模型可以写出正确参数，也不得调用 Jira。System 2 只能返回结构化拒绝原因或请求合法授权，不能寻找其他账号、其他工具或旁路 API。



#### Build Constraints

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


#### Bounded Reason Loop

图中的循环为：

```text
OBSERVE
  -> SELECT ALLOWED TOOL
  -> ACT
  -> UPDATE STATE
  -> BUDGET CHECK
  -> OBSERVE / FINISH / HUMAN / ABORT
```

注意⚠️：该过程不允许LLM创建临时的工具Tools来跳过缺口Gap

#### Verify Output
System 2 返回的候选结果按固定顺序验证，比如：Schema 验证类型、必填字段、枚举、格式和版本； Business Validator 确认业务状态已经达到；Policy Guard 检查

#### Outcome Router

* PASS -> Typed Artifact：只有所有 Validator 和 Policy Guard 通过后，System 2 才产生已验证的类型化 Artifact。
* NEED INPUT / HIGH RISK -> Human Interrupt
* FAIL / BUDGET EXHAUSTED



#### One Plan Repair Only
修订后只允许重新编译一次。仍然无效时进入 CLARIFY/REJECT，不能形成无限“提议—编译—修改”循环

#### Token 的可观测性

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

> #### 一个完整的 HYBRID System 2 运行示例
> 
> 任务：
> 
> ```text
> 从尚未沉淀 FSM 的 NewLog 系统读取 app-pay-01 最近 15 分钟日志，
> 确认 DB_CONN_TIMEOUT 后创建 Jira P1 并通知 payment-oncall。
> ```
> 
> 已有能力：
> 
> - `fsm.jira.p1.create@1.3.2`；
> - `fsm.wecom.notify_oncall@2.1.0`。
> 
> 缺口：NewLog 只有两个受控只读 Tool，没有 FSM。
> 
> 运行过程：
> 
> 1. Mode Router 选择 `HYBRID`；
> 2. Blueprint 包含一个 `reason` Step 和两个版本固定 FSM；
> 3. Compiler 校验 Tool Allowlist、Scope、预算、Output Schema、Validator 和下游类型；
> 4. Meta-Executor 调度 `reason_read_new_log_source`；
> 5. System 2 冻结 Snapshot、Caller ACL 和当前 Task State；
> 6. Gap Classifier 判定为 `Capability/Logic Gap`；
> 7. Constraint Builder 设置 3 个 Reason Steps、2 次 LLM、3 次 Tool Call、15 秒、只读副作用；
> 8. 第一次 Observe 后选择 `tool.newlog.search@1.0.0`；
> 9. Action Gateway 验证白名单、Scope 和参数 Schema 后调用；
> 10. Tool 返回 18 条匹配日志，完整内容写对象存储；
> 11. Reason State 保存错误码、连接池利用率摘要和 Artifact URI；
> 12. System 2 输出 `VerifiedErrorFact` 候选；
> 13. Schema、Evidence、Business Validator 和 Policy Guard 通过；
> 14. Ledger 写入 Token、Tool Call、版本和验证结果；
> 15. Outcome Router 输出 PASS；
> 16. `VerifiedErrorFact` 重新接入确定性 Jira FSM；
> 17. Jira FSM 完成后进入确定性企业微信 FSM；
> 18. Reason Trace 异步进入 Candidate Distiller，但当前 Run 不修改 Active Registry。








### Database In Register Backbone
![Register](assets/Register.png)

原方案中的 Experience Base 被实现为三层：

1. **Experience Evidence Layer：原始经验与证据层**  
   保存 Execution Trace、结构化错误、Validator 结果、人工反馈、回放数据和 Token 成本。这里的数据说明“过去发生过什么”，但不能因为一次成功就直接在线执行。
2. **Versioned Skill Registry：经过治理的可复用资产层**  
   保存不可变版本的 Tool Contract、FSM Shard、Workflow Skeleton、Adapter、Validator 及其发布状态、ACL、依赖关系和证据链。这里的数据说明“当前允许复用什么”。
3. **Retrieval Projection：可重建的检索投影层**  
   保存 Route Header、全文检索向量、Embedding 和图扩展所需的轻量数据。这里的数据只负责“快速找到候选”，不是资产事实源。

因此二者关系是：

```text
原始 Experience Base 概念
  ├── 原始运行经验：Execution Trace / Feedback / Evaluation
  ├── 已验证经验：Versioned Skill Registry
  └── 经验检索入口：Route Header + FTS + pgvector + Capability Graph
```


#### 系统实现设想

```text
PostgreSQL
  ├── registry schema       # 资产、版本、Contract、ACL、关系、Snapshot
  ├── retrieval schema      # Route Header、FTS、Embedding 检索投影
  ├── runtime schema        # Blueprint、Run、Step、幂等与成本账本
  └── governance schema     # Trace 索引、Patch、Evaluation、Release

S3 / MinIO / Git Artifact Store
  ├── tool-openapi/         # OpenAPI、JSON Schema、SDK 包
  ├── fsm/                  # FSM JSON/YAML、预编译子图包
  ├── fixtures/             # 测试输入、Golden Set、Mock 响应
  ├── replay/               # 脱敏后的回放数据
  └── reports/              # 评测报告、发布报告、不可变审计制品

Redis（可选）
  ├── READY Snapshot 的短期 Route Header 缓存
  └── 查询结果缓存；Key 必须包含 tenant、ACL digest、snapshot、query digest

LangGraph Checkpointer
  └── 可使用同一 PostgreSQL 实例的独立 schema/database，不能与 Registry 表混写
```

PostgreSQL 是事实源；向量、全文检索和缓存是可重建索引

#### 存储组件内容
| 组件 | 是否事实源 | 保存内容 | 不应保存/承担 |
| --- | --- | --- | --- |
| PostgreSQL Registry | 是 | 稳定 ID、不可变版本、Contract、状态、ACL、依赖、Snapshot | 大型二进制包、全文执行日志 |
| PostgreSQL Runtime/Governance | 是 | Blueprint、执行账本、Patch、评测、发布记录、Artifact URI | 大体积 Trace Body 和测试附件 |
| pgvector/FTS | 否，是派生索引 | Header Embedding、`tsvector`、检索模型版本 | 发布状态的唯一副本、执行体 |
| S3/MinIO/Git | Artifact 事实源 | 大型 Body、代码包、FSM 定义、Fixture、报告 | 检索排序、权限决策 |
| Redis | 否 | 可失效缓存 | 任何不可恢复的唯一数据 |

`Skill` 只作为产品层上位词。数据库必须使用明确的 `kind`：

| kind | 含义 | 是否作为普通能力被召回 | Body 保存方式 |
| --- | --- | --- | --- |
| `PRIMITIVE_TOOL` | 单个受控 API/函数 | 是 | OpenAPI/JSON Schema/SDK Artifact |
| `FSM_SHARD` | 完成一个稳定子目标的小状态图 | 是，通常优先于内部 Tool | FSM JSON/YAML 或预注册子图 Artifact |
| `WORKFLOW_SKELETON` | DAEF 宏观阶段骨架 | 作为规划先验单独召回，不直接执行 | JSONB 或小型 Artifact |
| `ADAPTER` | 在两个 Contract 之间做确定性类型/字段转换 | 默认不做全库语义召回，由图关系扩展加入 | 映射规则或受控代码 Artifact |
| `VALIDATOR` | 验证某个完成状态或输出约束 | 默认由 `required_validator` 关系扩展加入 | JSON Schema、规则或受控代码 Artifact |
| `BLUEPRINT` | 某次请求的版本固定执行实例 | 不进入通用能力召回 | PostgreSQL JSONB；大附件放对象存储 |

#### Route Header 保存什么，为什么与执行 Body 分离

Capability Retrieval 读取的是 Route Header，而不是完整 Tool/FSM Body。

推荐 Header 控制在几十到数百 Token，包含：

```json
{
  "asset_ref": "fsm.jira.p1.create@1.3.2",
  "kind": "FSM_SHARD",
  "name": "创建标准 Jira P1 故障工单",
  "summary": "根据已验证的生产故障事实创建符合支付团队模板的 Jira P1 工单",
  "domain": ["it-support", "payment-ops"],
  "positive_triggers": [
    "生产故障已确认，需要创建 Jira P1",
    "把结构化错误事实提交给支付值班团队"
  ],
  "anti_triggers": [
    "仅查询已有工单",
    "故障事实尚未验证",
    "非生产环境普通缺陷"
  ],
  "input_type_summary": "VerifiedErrorFact + ReporterIdentity",
  "output_type_summary": "JiraTicketRef",
  "precondition_summary": "error_fact.validated=true；调用者具有 jira:issue:create",
  "effect_summary": "恰好创建一个带幂等键的 P1 工单",
  "required_scopes": ["jira:issue:create"],
  "environment": ["prod"],
  "risk_level": "WRITE_MEDIUM",
  "reliability_lower_bound": 0.97,
  "last_evaluated_at": "2026-07-12T08:00:00Z"
}
```

完整 Contract 和 Body 不进入第一次检索 Prompt。例如 FSM Body 中的具体状态、工具 endpoint、重试和补偿规则，只在候选进入后续 Contract Rerank 或被 Blueprint 固定引用后加载。





### Skills Evolution Process 
![Evolve_backbone](assets/Evolve_backbone.png)

#### 生命周期状态

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

#### Patch Protocol
Patch 必须指定 `base_version`、证据 Trace 和变更类型：

| Patch 类型 | 允许修改 |
| --- | --- |
| Workflow | 节点、边、显式分支、循环、审批和补偿 |
| Semantics | 前置/后置、Predicate、本地 Retry、接受/拒绝条件 |
| Attachment | 工具绑定、配置、模板、资源、Secret Ref |
| Contract | 输入输出 Schema、权限、风险、数据分类和效果 |
| Test | Validator、Golden、Replay、Property 和 Security Test |

Patch 永远产生新版本。`base_version` 使用乐观锁：如果目标已经被其他 Patch 升级，当前 Patch 必须 Rebase 后重新执行全部测试。生成 Patch 的模型不能单独担任最终 Judge。高风险变更必须由不同评测过程和人工审批决定。

#### Umbrella-First 判定顺序
新增 Candidate 时按图中五类处理：

1. **Exact Duplicate**：执行图、Contract 和 Digest 相同，拒绝新增，仅关联新证据。
2. **Parameter Variant**：逻辑相同、常量不同，扩展已有参数并生成新版本。
3. **Alternative**：目标相同但工具、地区、成本或可靠性不同，保留两个实现并建立替代边。
4. **Composition**：Candidate 只是多个现有技能的固定组合，新增 Skeleton/Blueprint Template，不复制执行体。
5. **New Capability**：具有新的可验证效果或必要控制结构，才创建新 `skill_id`。

语义相似但权限、风险、数据分类或补偿语义不同的技能不能强制合并。

#### Healthy State

每个技能至少记录：成功、Validator 失败、超时、补偿和人工纠正；路由命中后采用率；Validator 覆盖率；
* 排序使用 Wilson Lower Bound 或 Beta-Binomial 后验下界，不让两次成功的技能以 100% 成功率压过运行数百次的稳定技能。
* 时效衰减用于降权和触发复测，不直接删除。低频技能可能是低频但关键的应急能力。

#### Skill优化：[SkillOps](https://github.com/Hik289/SkillOps)
#### 1. 给工具贴上“标准说明书”（Skill Contract）

以前的技能往往只是一段简单的文字描述，AI用起来容易出错 。SkillOps 为每个技能制定了严格的契约公式：``s=(P,O,A,V,F)``。
* **P (前提)**：调用这个工具需要什么条件 。
* **O (操作)**：具体的执行动作 。
* **A (产出)**：会生成什么结果 。
* **V (验证)**：怎么检查结果对不对 。
* **F (故障)**：已知会报什么错 。

这种标准化的定义，让AI能在动手前就清楚地知道工具到底能不能拼在一起用 。

#### 2. 编织“工具关系网”（HSEG）

系统将所有技能连成一张巨大的图谱，并标记出四种关系 ：
* **依赖**：工具A的产出正是工具B需要的前提 。
* **兼容**：工具A的输出格式，工具B刚好能无缝接收 。
* **冗余**：两个工具的功能完全一模一样（发现克隆体） 。
* **替代**：目标相同但实现手法不同的两个工具（备胎方案） 。

#### 3. 技能库的“五维体检”

有了关系网后，SkillOps 会通过五个维度给整个技能库做健康体检：

| 诊断维度 | 关注重点 | 解决的债务问题 |
| --- | --- | --- |
| <br>**实用性 (Utility)**  | 技能在最近调用中成功的概率 | 清理占据检索空间的低价值技能|
| <br>**冗余度 (Redundancy)** | 具有相同功能的“克隆”技能数量 | 减少重复项，提高检索精度|
| <br>**兼容性 (Compatibility)** | 前后关联的技能接口是否吻合 | 修复接口不匹配的错误 |
| <br>**失败风险 (Failure-Risk)** | 技能运行时的实际报错率 | 找出坏掉的技能进行维修 |
| <br>**验证缺口 (Validation-Gap)** | 技能是否缺少检查机制 | 防止错误的结果传递给下一步|

#### 4. 自动执行“保洁与维修”

针对体检发现的问题，系统会自动采取相应的维护动作，例如：
* **合并 (merge)**：把冗余重复的技能合而为一 。
* **淘汰 (retire)**：删掉没用或总是报错的技能 。
* **加转接头 (add_adapter)**：如果两个技能需要连用但接口不匹配，系统会插入一个类型转换的节点 。
* **加质检员 (add_validator)**：给没有检查机制的技能补上验证逻辑 。

#### 5. 双循环工作模式
SkillOps 依靠两个完全分离的循环来运转 ：
* **任务时循环 (Task-Time Loop)**：这是AI在“前台打工”。它负责根据当前任务挑选技能、检查接口、拼装计划并执行，遇到小错误会尝试直接修复 。
* **库时循环 (Library-Time Loop)**：这是“后台后勤”。在任务执行完后，系统会收集执行日志，默默地在后台做体检，并更新和清理技能库 。


### System Backend Driven Loop
![Backbone_dada_Transform](assets/Backbone_dada_Transform.png)