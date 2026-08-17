# Experience Base、Skill Registry 与 Capability Retrieval 数据方案

> 文档目标：解释原始方案中的 `Experience Base` 与新版 `Skill Registry/Governance` 的关系，明确 FSM、Tool、Skill、Skeleton、Validator、Adapter、Blueprint、运行证据分别保存在哪里、保存什么，以及 `Capability Retrieval` 在进入 SAD 之前如何完成初步召回。
>
> 本文只把检索链路写到 **SAD 之前的 Header Candidate Set**。Contract 重排、SAD 二次对齐、Blueprint 生成和执行不在最后一个示例的范围内。

---

## 1. 先给结论

原方案中的 **Experience Base 是一个逻辑概念，不应直接等同于某一个向量数据库或 Dify 知识库**。它表示系统从历史成功执行中沉淀、治理并再次复用的全部经验。

在更新后的工程方案中，Experience Base 被实现为三层：

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

更准确地说，**Skill Registry 是 Experience Base 中“已经通过治理、可以被生产系统引用”的核心子集和事实源**。Experience Base 没有消失，只是从“把一条经验当作文档塞进向量库”升级成了“证据、资产、索引彼此分离的生产系统”。

---

## 2. 为什么不能继续只用一个 Dify 知识库保存全部经验

原始 `Token Reduce_Plan.md` 适合 PoC：每条经验是一份文档，文档同时包含任务描述、工具序列和参数模板；Dify 知识库通过向量相似度找到它。

当系统进入生产环境后，这种单库存法会出现以下问题：

| 问题 | 只使用知识库/向量库的后果 | 新方案的处理 |
| --- | --- | --- |
| 版本 | 文档被覆盖后，旧运行无法复现 | `asset_id@version` 不可变，旧版本保留 |
| 发布状态 | 草稿和线上版本容易混在一起 | Draft、Shadow、Canary、Active、Deprecated 分离 |
| 权限 | 可能先召回越权内容，再让 LLM 自觉忽略 | SQL 查询阶段执行 Tenant、ACL、环境和风险硬过滤 |
| 依赖 | 单个文档难以表达 Tool、FSM、Validator、Adapter 的版本关系 | `capability_edge` 保存有向、版本固定的关系 |
| 一致性 | 检索时是旧版本，执行时可能加载新版本 | 一次规划固定 `registry_snapshot_id` |
| 事务 | 向量索引无法可靠承担发布事务和引用完整性 | PostgreSQL 是事实源，索引可以重建 |
| 执行安全 | 检索到全文后可能把代码或未验证模板直接交给 LLM | 先返回 Header；确定选中后才按引用加载 Contract/Body |
| 审计 | 很难回答某个版本为什么上线 | Patch、Evaluation、Release 和证据链单独记录 |

所以推荐保留 Dify 的易用入口，但改变它的职责：

- Dify 知识库继续保存业务文档、操作手册和普通 RAG 内容；
- Dify 工作流通过 HTTP/Tool 节点调用 `Capability Retrieval API`；
- 如果为了兼容必须在 Dify 展示“经验库”，只同步 Route Header 的只读副本；
- 同步方向必须是 **Registry -> Dify**，不能允许知识库文档反向覆盖 Active 执行资产；
- Dify 返回的 `asset_ref` 在后续使用前仍需由 Registry 校验 Snapshot、ACL 和状态。

---

## 3. 推荐的物理存储布局

MVP 不需要同时部署多个专用数据库。推荐先使用：

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

### 3.1 每个存储组件的边界

| 组件 | 是否事实源 | 保存内容 | 不应保存/承担 |
| --- | --- | --- | --- |
| PostgreSQL Registry | 是 | 稳定 ID、不可变版本、Contract、状态、ACL、依赖、Snapshot | 大型二进制包、全文执行日志 |
| PostgreSQL Runtime/Governance | 是 | Blueprint、执行账本、Patch、评测、发布记录、Artifact URI | 大体积 Trace Body 和测试附件 |
| pgvector/FTS | 否，是派生索引 | Header Embedding、`tsvector`、检索模型版本 | 发布状态的唯一副本、执行体 |
| S3/MinIO/Git | Artifact 事实源 | 大型 Body、代码包、FSM 定义、Fixture、报告 | 检索排序、权限决策 |
| Redis | 否 | 可失效缓存 | 任何不可恢复的唯一数据 |
| Dify Knowledge Base | 否 | 业务知识；可选的 Header 只读镜像 | Active 资产唯一副本、版本事务、执行账本 |
| LangGraph Checkpointer | 是，针对运行状态 | 当前图位置、可恢复状态、Interrupt | Skill Registry、外部副作用是否已发生的唯一证据 |

### 3.2 Checkpoint 与 Execution Ledger 不是同一类数据

- Checkpoint 回答：**图执行到哪里、恢复时内存状态是什么**。
- Execution Ledger 回答：**某个外部写操作是否已经发生、使用了哪个幂等键、结果是什么**。

例如 Jira 已成功创建，但进程在写入下一 Checkpoint 前崩溃。仅依赖 Checkpoint 可能重复创建 Jira；`execution_step.idempotency_key` 和工具侧幂等接口才能避免重复副作用。

---

## 4. Registry 中的资产如何分类

`Skill` 只作为产品层上位词。数据库必须使用明确的 `kind`：

| kind | 含义 | 是否作为普通能力被召回 | Body 保存方式 |
| --- | --- | --- | --- |
| `PRIMITIVE_TOOL` | 单个受控 API/函数 | 是 | OpenAPI/JSON Schema/SDK Artifact |
| `FSM_SHARD` | 完成一个稳定子目标的小状态图 | 是，通常优先于内部 Tool | FSM JSON/YAML 或预注册子图 Artifact |
| `WORKFLOW_SKELETON` | DAEF 宏观阶段骨架 | 作为规划先验单独召回，不直接执行 | JSONB 或小型 Artifact |
| `ADAPTER` | 在两个 Contract 之间做确定性类型/字段转换 | 默认不做全库语义召回，由图关系扩展加入 | 映射规则或受控代码 Artifact |
| `VALIDATOR` | 验证某个完成状态或输出约束 | 默认由 `required_validator` 关系扩展加入 | JSON Schema、规则或受控代码 Artifact |
| `BLUEPRINT` | 某次请求的版本固定执行实例 | 不进入通用能力召回 | PostgreSQL JSONB；大附件放对象存储 |

这与 `diff_Fregment.md` 的“四类资产”不冲突：Primitive Tool、FSM Shard、Workflow Skeleton 和 Blueprint 是主规划语义；Adapter、Validator 是受治理的支持资产，也必须有明确版本和 Contract，但通常不靠自然语言全库搜索决定是否使用。

### 4.1 原始 Experience 如何变成 Registry Asset

```text
Execution Run
  -> Trace + Validator + Human Feedback
  -> Experience Candidate（候选经验）
  -> 类型化 Patch 或新资产 Draft
  -> Contract Lint + Unit Test + Replay
  -> Shadow
  -> Canary
  -> Active
  -> 出现在新的 READY Registry Snapshot
  -> Capability Retrieval 可见
```

一次成功运行只生成候选证据，**不会直接向 Active 集合写入一个新 Skill**。这是 Experience Consolidation 在新方案中的工程化含义。

---

## 5. PostgreSQL 最小逻辑数据模型

下面是推荐的逻辑表。字段可按现有技术栈调整，但职责不要合并。

| schema.table | 关键字段 | 保存什么 |
| --- | --- | --- |
| `registry.asset` | `asset_id`, `kind`, `tenant_scope`, `owner` | 资产稳定身份；不包含可变执行内容 |
| `registry.asset_version` | `asset_id`, `version`, `contract_json`, `artifact_uri`, `artifact_digest` | 不可变版本、完整 Contract 和 Body 引用 |
| `registry.asset_release` | `asset_ref`, `environment`, `status`, `risk_level` | Draft/Canary/Active 等发布状态 |
| `registry.asset_acl` | `asset_ref`, `tenant_id`, `principal`, `required_scopes` | 资产可见性和调用权限 |
| `registry.capability_edge` | `from_ref`, `to_ref`, `edge_type`, `adapter_ref` | 依赖、替代、兼容、Validator、Adapter 关系 |
| `registry.registry_snapshot` | `snapshot_id`, `status`, `active_set_digest` | 可供规划固定的一致视图 |
| `registry.snapshot_member` | `snapshot_id`, `asset_ref` | 该 Snapshot 包含的精确版本集合 |
| `registry.registry_head` | `tenant_id`, `environment`, `snapshot_id` | 新规划应固定的最新 READY Snapshot 指针 |
| `retrieval.route_header` | `asset_ref`, `locale`, `header_json`, `retrieval_text` | 小而稳定的检索 Header 源数据 |
| `retrieval.route_index` | `asset_ref`, `index_revision`, `search_tsv`, `embedding` | 可重建 FTS/Vector 投影 |
| `runtime.blueprint` | `blueprint_id`, `snapshot_id`, `body`, `compile_result` | 一次任务的计划和编译证据 |
| `runtime.execution_run` | `run_id`, `blueprint_id`, `status`, `token_cost` | 运行级账本 |
| `runtime.execution_step` | `run_id`, `step_id`, `asset_ref`, `attempt`, `idempotency_key` | 步骤、副作用去重和结果摘要 |
| `governance.experience_candidate` | `candidate_id`, `source_run_ids`, `proposal` | 从 Trace 提取但尚未发布的经验候选 |
| `governance.patch_proposal` | `base_ref`, `patch_type`, `evidence`, `status` | 类型化变更提案 |
| `governance.evaluation_run` | `asset_ref`, `suite_ref`, `metrics`, `verdict` | 测试、回放、Shadow/Canary 证据 |
| `governance.release_event` | `asset_ref`, `from_status`, `to_status`, `approver` | 发布状态转换审计 |
| `governance.artifact_manifest` | `artifact_uri`, `digest`, `media_type`, `size_bytes` | 对象存储/Git 制品索引 |

### 5.1 为什么版本内容与发布状态分表

`asset_version` 必须不可变。修正一个参数、Schema 或 FSM 边都要产生新版本和新 Digest。

发布状态会发生变化，例如：

```text
Draft -> Validating -> Shadow -> Canary -> Active -> Deprecated -> Retired
```

因此状态应写在 `asset_release` 和 `release_event` 中，而不是通过覆盖 `asset_version` 的内容实现“更新”。这样旧 Blueprint 引用的 `asset_id@version` 始终可复现。

### 5.2 推荐的关键约束

```sql
-- 逻辑示例，不代替正式 migration。
CREATE UNIQUE INDEX uq_asset_version
  ON registry.asset_version(asset_id, version);

CREATE UNIQUE INDEX uq_snapshot_member
  ON registry.snapshot_member(snapshot_id, asset_ref);

CREATE UNIQUE INDEX uq_route_header_locale
  ON retrieval.route_header(asset_ref, locale);

CREATE UNIQUE INDEX uq_step_attempt
  ON runtime.execution_step(run_id, step_id, attempt);

CREATE UNIQUE INDEX uq_side_effect_idempotency
  ON runtime.execution_step(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

还应实现：

- `artifact_digest` 与 Artifact 实际内容校验；
- Blueprint 中每个 `asset_ref` 必须存在于其 `snapshot_id`；
- `asset_ref` 使用完整的 `asset_id@version`，不能只写名称；
- `Active`/`Canary` 状态转换必须关联通过的 `evaluation_run`；
- Registry 查询必须携带 `tenant_id`、调用者身份和 Scope；
- 对象存储使用不可变路径或版本化 Bucket，禁止原地覆盖 Active Artifact。

---

## 6. Route Header 保存什么，为什么与执行 Body 分离

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

### 6.1 `retrieval_text` 如何生成

不要让每次检索临时用 LLM 总结 Header。发布时使用确定性模板生成：

```text
name
+ summary
+ domain
+ positive_triggers
+ input_type_summary
+ output_type_summary
+ precondition_summary
+ effect_summary
+ 受控 keywords / tool aliases / error codes
```

`anti_triggers` 可以加入 Sparse 特征或在候选后做负向规则扣分，但不能只依赖 Embedding 理解否定语义。

### 6.2 FTS 与 Embedding 的可重建信息

`route_index` 至少记录：

```json
{
  "asset_ref": "fsm.jira.p1.create@1.3.2",
  "index_revision": "route-index-20260715-01",
  "embedding_model": "approved-embedding-model@revision",
  "embedding_dimension": 1536,
  "retrieval_text_digest": "sha256:...",
  "search_tsv": "jira p1 payment incident create DB_CONN_TIMEOUT ...",
  "embedding": "[0.012, -0.031, ...]"
}
```

Embedding 模型升级只需重建 `route_index`，不修改 `asset_version`。索引损坏时也能从 `route_header` 重建。

### 6.3 中文全文检索注意事项

PostgreSQL 默认分词不能直接保证中文 BM25/FTS 效果。MVP 可采用以下任一种可测试方案：

1. 应用层使用固定版本的中文分词器，将分词结果写入 `retrieval_text_tokens`，再用 `to_tsvector('simple', ...)`；
2. 使用 PGroonga 等 PostgreSQL 扩展；
3. 数据量和吞吐增长后，将 OpenSearch 作为派生 Sparse Index。

错误码、Tool 名、系统名、产品名和对象 ID 应保留原始 Token，不能被中文分词器拆坏。

---

## 7. Registry Snapshot 如何保证一次规划一致

Snapshot 不是复制所有 Body，而是保存当时可用资产的精确版本集合：

```json
{
  "snapshot_id": "rs_20260715_00042",
  "status": "READY",
  "created_at": "2026-07-15T02:10:00Z",
  "active_set_digest": "sha256:9b3c...",
  "index_revision": "route-index-20260715-01",
  "members": [
    "tool.log.search@4.0.0",
    "fsm.log.verify_error@2.0.1",
    "fsm.jira.p1.create@1.3.2",
    "fsm.wecom.notify_oncall@2.1.0",
    "validator.error_fact@1.2.0",
    "adapter.errorfact_to_jira@1.0.0"
  ]
}
```

推荐发布流程：

1. 新建 `BUILDING` Snapshot；
2. 在事务中写入本次 Active/Canary 可见的 `snapshot_member`；
3. 确认每个成员都有匹配的 Route Index Revision；
4. 计算 `active_set_digest`；
5. 将 Snapshot 标记为 `READY`；
6. 原子更新 `registry_head` 指向新的 READY Snapshot；
7. 已开始的规划继续使用旧 Snapshot，新请求使用新 Snapshot。

不允许规划过程中使用“当前最新版本”进行二次解析，否则 Retrieval、SAD、Compiler 和 Executor 可能看到不同资产集合。

---

## 8. Capability Retrieval 的服务接口

建议把检索封装成独立 API，而不是让 Dify 直接拼接多张数据库表。

```text
POST /v1/capabilities/retrieve
```

请求：

```json
{
  "request_id": "req_01J2...",
  "caller": {
    "tenant_id": "tenant_acme",
    "principal_id": "user_1042",
    "roles": ["payment_oncall"],
    "scopes": ["logs:read", "jira:issue:create", "wecom:message:send"]
  },
  "task_context": {
    "normalized_query": "读取支付服务生产日志，确认 DB_CONN_TIMEOUT，创建 Jira P1 并通知支付值班组",
    "entities": {
      "service": "app-pay-01",
      "error_code": "DB_CONN_TIMEOUT",
      "time_range": "PT15M",
      "ticket_priority": "P1",
      "notify_target": "payment-oncall"
    },
    "environment": "prod",
    "domain": "payment-ops",
    "max_risk": "WRITE_MEDIUM",
    "locale": "zh-CN"
  },
  "snapshot_id": null,
  "candidate_budget": {
    "sparse_k": 40,
    "dense_k": 40,
    "fused_k": 12,
    "graph_hops": 1,
    "max_total": 20
  }
}
```

当 `snapshot_id=null` 时，服务在请求开始时解析一次 `registry_head`，把得到的 ID 写入响应和后续规划状态。调用方不能在同一次规划中重新获取最新 Snapshot。

响应只包含 Header：

```json
{
  "request_id": "req_01J2...",
  "registry_snapshot_id": "rs_20260715_00042",
  "stage": "HEADER_RETRIEVAL_COMPLETE",
  "next_stage": "SAD_ALIGNMENT",
  "candidates": [
    {
      "asset_ref": "fsm.log.verify_error@2.0.1",
      "kind": "FSM_SHARD",
      "header": {},
      "retrieval_provenance": {
        "channels": ["sparse", "dense"],
        "rrf_score": 0.032786,
        "sparse_rank": 1,
        "dense_rank": 1
      }
    }
  ]
}
```

响应中不能出现 Tool 密钥、完整 OpenAPI 凭据、可执行代码或 FSM 全文。

---

## 9. SAD 之前的初步召回如何实现

### 9.1 Step 0：Task Normalizer 生成检索上下文

Normalizer 从用户输入和会话元数据中产生结构化 `task_context`：

- 规范化目标文本；
- 租户、用户、角色、Scope；
- 环境、地域和数据分类；
- 明确实体：系统名、错误码、对象 ID、时间、金额；
- 当前允许的最大风险；
- 可用 Tool Runtime 列表。

此时不决定步骤顺序，也不生成 Blueprint。

### 9.2 Step 1：固定 Snapshot

```sql
SELECT snapshot_id, index_revision
FROM registry.registry_head
WHERE tenant_id = :tenant_id
  AND environment = :environment;
```

获得 `registry_snapshot_id` 后，本次 Retrieval、SAD、Contract Rerank 和 Blueprint Compiler 均复用该值。

### 9.3 Step 2：数据库硬过滤

先得到调用者可以看到的候选集合：

```sql
WITH visible AS MATERIALIZED (
  SELECT
    sm.asset_ref,
    rh.header_json,
    ri.search_tsv,
    ri.embedding
  FROM registry.snapshot_member sm
  JOIN registry.asset_release ar
    ON ar.asset_ref = sm.asset_ref
  JOIN retrieval.route_header rh
    ON rh.asset_ref = sm.asset_ref
   AND rh.locale = :locale
  JOIN retrieval.route_index ri
    ON ri.asset_ref = sm.asset_ref
   AND ri.index_revision = :index_revision
  WHERE sm.snapshot_id = :snapshot_id
    AND ar.status IN ('ACTIVE', 'CANARY')
    AND ar.environment IN (:environment, 'ANY')
    AND ar.risk_rank <= :max_risk_rank
    AND ar.runtime_schema_version = :runtime_schema_version
    AND EXISTS (
      SELECT 1
      FROM registry.asset_acl acl
      WHERE acl.asset_ref = sm.asset_ref
        AND acl.tenant_id IN (:tenant_id, 'GLOBAL')
        AND acl.required_scopes <@ :caller_scopes
    )
)
SELECT * FROM visible;
```

这里的关键不是具体 SQL 写法，而是以下硬规则：

- Tenant/ACL 必须在数据库候选集合中生效；
- Draft、Quarantined、Retired 不进入普通召回；
- 当前 Runtime 不兼容的版本不可见；
- 当前用户没有写权限时，即使语义高度相似，也不能返回写操作能力；
- Tool 当前不可用时，依赖该 Tool 且没有替代路径的 FSM 应过滤或降为不可执行提示。

生产环境可再加 PostgreSQL RLS 作为纵深防御，但业务查询仍应显式带 Tenant 和 Scope。

### 9.4 Step 3：Sparse/FTS 召回

Sparse 通道适合错误码、Tool 名、系统名、工单字段和业务专有词：

```sql
WITH visible AS MATERIALIZED (...与上一步相同...)
SELECT
  asset_ref,
  header_json,
  ts_rank_cd(search_tsv, query) AS sparse_score
FROM visible,
     websearch_to_tsquery('simple', :tokenized_query) AS query
WHERE search_tsv @@ query
ORDER BY sparse_score DESC, asset_ref
LIMIT :sparse_k;
```

`tokenized_query` 示例：

```text
app-pay-01 payment prod DB_CONN_TIMEOUT log verify jira P1 wecom payment-oncall
```

严格来说，PostgreSQL 内置 `ts_rank`/`ts_rank_cd` 是全文检索相关度排序，并不是标准 BM25。若项目要求明确使用 BM25，可将 OpenSearch/Elasticsearch 或经过验证的 PostgreSQL 扩展作为 Sparse 派生索引；接口层仍统一称为 Sparse Channel，Registry Snapshot 与 ACL 仍由 PostgreSQL 约束。

### 9.5 Step 4：Dense/Vector 召回

Dense 通道解决同义表达，例如“通知值班组”和“发送企业微信告警”：

```sql
WITH visible AS MATERIALIZED (...与上一步相同...)
SELECT
  asset_ref,
  header_json,
  1 - (embedding <=> :query_embedding) AS cosine_similarity
FROM visible
ORDER BY embedding <=> :query_embedding, asset_ref
LIMIT :dense_k;
```

Query Embedding 只计算一次，输入为规范化目标、关键实体和期望结果，不包含密钥、无关会话全文或完整 Chain-of-Thought。

数据规模增大后，应按 Tenant/领域/环境合理分区或使用派生向量服务，防止 ANN 先取全局近邻再过滤导致小租户 Recall 下降。无论使用 pgvector、Qdrant 还是 Milvus，最终可见性仍以 Registry 的 Snapshot/ACL 为准。

### 9.6 Step 5：RRF 合并两个排名

BM25/FTS 分数与 Cosine 分数尺度不同，不能直接相加。服务层使用 Reciprocal Rank Fusion：

```text
RRF(asset) = Σ_channel 1 / (k + rank_channel(asset))
```

推荐先以 `k=60` 作为初始值，再通过真实标注集调参。缺席某个通道的资产不获得该通道分数。

伪代码：

```python
scores = {}
for ranked_list in [sparse_results, dense_results]:
    for rank, item in enumerate(ranked_list, start=1):
        scores[item.asset_ref] = scores.get(item.asset_ref, 0.0) + 1.0 / (60 + rank)

fused = sort_by_score_desc_then_asset_ref(scores)
fused = fused[:fused_k]
```

稳定的二级排序键非常重要，否则同分候选会使回放结果不确定。

### 9.7 Step 6：Capability Graph 一跳扩展

对融合后的 Top Candidates 只扩展一跳：

```sql
SELECT
  e.from_ref,
  e.to_ref,
  e.edge_type,
  e.adapter_ref,
  e.confidence
FROM registry.capability_edge e
JOIN registry.snapshot_member sm
  ON sm.asset_ref = e.to_ref
WHERE sm.snapshot_id = :snapshot_id
  AND e.from_ref = ANY(:fused_asset_refs)
  AND e.edge_type IN (
    'DEPENDS_ON',
    'REQUIRES_VALIDATOR',
    'ALTERNATIVE_TO',
    'COMPATIBLE_VIA_ADAPTER'
  );
```

扩展出的资产仍要执行相同 ACL、状态、环境和风险过滤。它们必须携带来源，例如：

```json
{
  "asset_ref": "validator.error_fact@1.2.0",
  "retrieval_provenance": {
    "channels": ["graph"],
    "expanded_from": "fsm.log.verify_error@2.0.1",
    "edge_type": "REQUIRES_VALIDATOR",
    "graph_hop": 1
  }
}
```

禁止无界扩图；否则一个通用 Tool 可能把整个 Registry 拉入上下文。

### 9.8 Step 7：去重、裁剪并返回 Header Candidate Set

最后执行：

1. 按 `asset_ref` 去重；
2. 保留 RRF 候选及其一跳必需关系；
3. 执行 `anti_trigger` 硬规则或确定性扣分；
4. 按 `max_total` 和 Header Token Budget 裁剪；
5. 返回 `registry_snapshot_id`、Header、排名和 Provenance；
6. 标记下一阶段为 `SAD_ALIGNMENT`。

到这里初步召回完成。此时系统**还没有断言哪个候选一定可执行，也没有生成步骤顺序**。

---

## 10. 每种存放数据类型的示例

以下示例使用同一个“读取生产日志 -> 验证错误 -> 创建 Jira -> 企业微信通知”任务族，便于观察各数据之间如何引用。

### 10.1 `skill / asset`：稳定身份示例

```json
{
  "asset_id": "fsm.jira.p1.create",
  "kind": "FSM_SHARD",
  "logical_name": "创建标准 Jira P1 故障工单",
  "tenant_scope": "tenant_acme",
  "owner": "team-payment-platform",
  "created_at": "2026-06-20T03:00:00Z"
}
```

稳定身份不包含执行细节；执行细节属于版本。

### 10.2 `skill_version / asset_version`：不可变版本示例

```json
{
  "asset_ref": "fsm.jira.p1.create@1.3.2",
  "schema_version": "skill-contract/1.0",
  "contract_json": {
    "goal": "创建符合支付团队模板的 P1 故障工单",
    "preconditions": ["input.error_fact.validated == true"],
    "inputs": {
      "error_fact": "VerifiedErrorFact",
      "reporter": "ReporterIdentity"
    },
    "outputs": {"ticket": "JiraTicketRef"},
    "effects": ["jira_issue_created"],
    "required_scopes": ["jira:issue:create"],
    "idempotency": "required",
    "validator_refs": ["validator.jira.ticket@1.1.0"]
  },
  "artifact_uri": "s3://agent-artifacts/fsm/fsm.jira.p1.create/1.3.2/fsm.json",
  "artifact_digest": "sha256:41f5..."
}
```

### 10.3 `Primitive Tool`：Tool Contract 示例

```json
{
  "asset_ref": "tool.jira.issue.create@3.4.0",
  "kind": "PRIMITIVE_TOOL",
  "contract": {
    "operation_id": "createJiraIssue",
    "input_schema": {
      "project": "string",
      "priority": "enum[P1,P2,P3]",
      "summary": "string",
      "description": "string",
      "idempotency_key": "string"
    },
    "output_schema": {
      "issue_key": "string",
      "issue_url": "uri"
    },
    "side_effect": "EXTERNAL_WRITE",
    "required_scopes": ["jira:issue:create"],
    "timeout_ms": 5000,
    "retry_policy": "retry only on transport/5xx with same idempotency key"
  },
  "artifact_uri": "s3://agent-artifacts/tool-openapi/jira/3.4.0/openapi.json",
  "artifact_digest": "sha256:8a01..."
}
```

密钥不写入 Contract，而由运行环境的 Secret Manager 按 `credential_binding_ref` 注入。

### 10.4 `FSM Shard`：执行 Body 示例

```json
{
  "asset_ref": "fsm.jira.p1.create@1.3.2",
  "entry_state": "VALIDATE_INPUT",
  "states": {
    "VALIDATE_INPUT": {
      "type": "validator",
      "asset_ref": "validator.error_fact@1.2.0",
      "on_pass": "CREATE_TICKET",
      "on_fail": "FAILED"
    },
    "CREATE_TICKET": {
      "type": "tool",
      "asset_ref": "tool.jira.issue.create@3.4.0",
      "idempotency_key": "{{run_id}}:jira-p1",
      "on_success": "VERIFY_TICKET",
      "on_error": "COMPENSATE_OR_FAIL"
    },
    "VERIFY_TICKET": {
      "type": "validator",
      "asset_ref": "validator.jira.ticket@1.1.0",
      "on_pass": "SUCCEEDED",
      "on_fail": "FAILED"
    }
  }
}
```

此 Body 存在对象存储，Route Header 不包含这些内部节点。

### 10.5 `Workflow Skeleton / DAEF` 示例

```json
{
  "asset_ref": "skeleton.incident.response@2.0.0",
  "kind": "WORKFLOW_SKELETON",
  "stages": [
    {"stage": "INFORMATION", "expected_state": "故障事实已收集"},
    {"stage": "TRANSFORM", "expected_state": "错误信息已结构化和验证"},
    {"stage": "DECISION", "expected_state": "严重度和处置路径已确定"},
    {"stage": "ACTION", "expected_state": "工单和通知已完成"}
  ],
  "directly_executable": false
}
```

Skeleton 只提供任务宏观结构，不绑定 Jira 或企业微信的具体版本。

### 10.6 `Validator` 示例

```json
{
  "asset_ref": "validator.error_fact@1.2.0",
  "kind": "VALIDATOR",
  "input_type": "ErrorFact",
  "output_type": "ValidationResult<VerifiedErrorFact>",
  "rules": [
    "service is not empty",
    "environment == 'prod'",
    "error_code is not empty",
    "evidence.log_lines >= 1",
    "observed_at is within requested time range"
  ],
  "executor_ref": "ruleset://error-fact/1.2.0",
  "artifact_digest": "sha256:2f07..."
}
```

### 10.7 `Adapter` 示例

```json
{
  "asset_ref": "adapter.errorfact_to_jira@1.0.0",
  "kind": "ADAPTER",
  "from_type": "VerifiedErrorFact@1",
  "to_type": "JiraP1CreateInput@3",
  "mapping": {
    "project": "PAY",
    "priority": "P1",
    "summary": "[{{source.environment}}] {{source.service}}: {{source.error_code}}",
    "description": "{{source.summary}}\nEvidence: {{source.evidence_uri}}"
  },
  "side_effect": "NONE",
  "artifact_digest": "sha256:a83c..."
}
```

Adapter 只能转换数据，不能偷偷执行 Jira 写操作。

### 10.8 `route_header + tsvector + embedding` 示例

```json
{
  "asset_ref": "fsm.log.verify_error@2.0.1",
  "header_json": {
    "name": "读取日志并形成已验证错误事实",
    "summary": "查询指定服务和时间窗的生产日志，抽取错误码并通过 Validator 形成 VerifiedErrorFact",
    "positive_triggers": ["检查生产报错", "根据错误码确认故障事实"],
    "anti_triggers": ["修改日志", "只查询历史 Jira"],
    "input_type_summary": "ServiceRef + TimeRange + ErrorHint",
    "output_type_summary": "VerifiedErrorFact",
    "risk_level": "READ_LOW"
  },
  "index": {
    "index_revision": "route-index-20260715-01",
    "search_tsv": "log production error DB_CONN_TIMEOUT verify service time range",
    "embedding_model": "approved-embedding-model@revision",
    "embedding": "[0.021, -0.113, ...]"
  }
}
```

### 10.9 `capability_edge` 示例

```json
[
  {
    "from_ref": "fsm.log.verify_error@2.0.1",
    "to_ref": "validator.error_fact@1.2.0",
    "edge_type": "REQUIRES_VALIDATOR",
    "confidence": 1.0
  },
  {
    "from_ref": "fsm.log.verify_error@2.0.1",
    "to_ref": "fsm.jira.p1.create@1.3.2",
    "edge_type": "COMPATIBLE_VIA_ADAPTER",
    "adapter_ref": "adapter.errorfact_to_jira@1.0.0",
    "confidence": 1.0
  },
  {
    "from_ref": "fsm.jira.p1.create@1.3.2",
    "to_ref": "tool.jira.issue.create@3.4.0",
    "edge_type": "DEPENDS_ON",
    "confidence": 1.0
  }
]
```

关系边同样引用固定版本；升级依赖必须产生新的 FSM 版本或新的兼容证据。

### 10.10 `blueprint` 示例

Blueprint 通常在 SAD 和 Plan Proposer 之后产生，此处只说明数据库保存格式：

```json
{
  "blueprint_id": "bp_20260715_00128",
  "registry_snapshot_id": "rs_20260715_00042",
  "mode": "REUSE",
  "steps": [
    {"step_id": "s1", "type": "fsm", "asset_ref": "fsm.log.verify_error@2.0.1"},
    {"step_id": "s2", "type": "adapter", "asset_ref": "adapter.errorfact_to_jira@1.0.0", "depends_on": ["s1"]},
    {"step_id": "s3", "type": "fsm", "asset_ref": "fsm.jira.p1.create@1.3.2", "depends_on": ["s2"]},
    {"step_id": "s4", "type": "fsm", "asset_ref": "fsm.wecom.notify_oncall@2.1.0", "depends_on": ["s3"]}
  ],
  "compile_result": {
    "status": "PASSED",
    "compiler_version": "blueprint-compiler@1.0.0",
    "compiled_digest": "sha256:c92d..."
  }
}
```

Blueprint 是任务实例，不应因为执行成功就直接作为新的全局 Skill 参与检索。需要先经过治理流程提炼成 FSM、Skeleton 或 Blueprint Template Draft。

### 10.11 `execution_run / execution_step` 示例

```json
{
  "execution_run": {
    "run_id": "run_01J2ABC",
    "thread_id": "thread_8821",
    "blueprint_id": "bp_20260715_00128",
    "status": "SUCCEEDED",
    "prompt_tokens": 1240,
    "completion_tokens": 182,
    "tool_cost": 0.006,
    "started_at": "2026-07-15T03:01:00Z",
    "ended_at": "2026-07-15T03:01:07Z"
  },
  "execution_steps": [
    {
      "step_id": "s3",
      "attempt": 1,
      "asset_ref": "fsm.jira.p1.create@1.3.2",
      "idempotency_key": "run_01J2ABC:jira-p1",
      "status": "SUCCEEDED",
      "safe_output_summary": {"issue_key": "PAY-4821"},
      "artifact_uri": "s3://agent-traces/run_01J2ABC/s3/result.enc.json"
    }
  ]
}
```

数据库只保存安全摘要和 URI；敏感完整输入输出应脱敏、加密并设置生命周期。

### 10.12 `patch / evaluation / release` 示例

```json
{
  "patch_proposal": {
    "patch_id": "patch_0091",
    "base_ref": "fsm.log.verify_error@2.0.0",
    "patch_type": "CONTRACT_FIX",
    "proposal": "增加 DB_CONN_TIMEOUT 的连接池证据字段映射",
    "source_run_ids": ["run_01J29AA", "run_01J29BB"],
    "status": "VALIDATING"
  },
  "evaluation_run": {
    "asset_ref": "fsm.log.verify_error@2.0.1",
    "suite_ref": "suite.payment-log-errors@3.0",
    "metrics": {"passed": 148, "failed": 0, "validated_success_rate": 0.986},
    "verdict": "PASS"
  },
  "release_event": {
    "asset_ref": "fsm.log.verify_error@2.0.1",
    "from_status": "CANARY",
    "to_status": "ACTIVE",
    "evidence_refs": ["evaluation:suite.payment-log-errors@3.0"],
    "approver": "team-payment-platform"
  }
}
```

### 10.13 `Object Storage / Git Artifact` 示例

```json
{
  "artifact_uri": "s3://agent-artifacts/fsm/fsm.log.verify_error/2.0.1/fsm.json",
  "artifact_digest": "sha256:73af...",
  "media_type": "application/vnd.company.fsm+json",
  "size_bytes": 18422,
  "encryption": "SSE-KMS",
  "retention_class": "AUDIT_365D",
  "created_by_release": "release_01882"
}
```

对象存储路径中的版本和 Digest 不变。若内容变化，必须产生新版本和新 URI。

### 10.14 `Experience Candidate` 示例

```json
{
  "candidate_id": "expc_20260715_0019",
  "source_run_ids": ["run_01J2ABC", "run_01J2ABD", "run_01J2ABE"],
  "detected_pattern": "支付生产故障确认后创建 P1 并通知值班组",
  "suggested_action": "COMPOSE_EXISTING",
  "suggested_refs": [
    "fsm.log.verify_error@2.0.1",
    "fsm.jira.p1.create@1.3.2",
    "fsm.wecom.notify_oncall@2.1.0"
  ],
  "status": "DRAFT",
  "reason": "已有资产可以组合，不创建重复 FSM"
}
```

这就是原始 Experience Consolidation 的落库结果之一：先成为候选和证据，而不是直接成为 Active Skill。

---

## 11. 完整示例：从用户问题到 SAD 之前的初步召回

### 11.1 用户输入

```text
请检查生产环境 app-pay-01 最近 15 分钟的日志。
如果确认 DB_CONN_TIMEOUT 是数据库连接池耗尽造成的，创建一个 Jira P1 工单，
并通过企业微信通知 payment-oncall 值班组。
```

会话身份：

```json
{
  "tenant_id": "tenant_acme",
  "principal_id": "user_1042",
  "roles": ["payment_oncall"],
  "scopes": ["logs:read", "jira:issue:create", "wecom:message:send"],
  "environment": "prod"
}
```

### 11.2 Task Normalizer 输出

```json
{
  "normalized_query": "读取 app-pay-01 生产日志并验证 DB_CONN_TIMEOUT；验证通过后创建 Jira P1，并通知 payment-oncall",
  "entities": {
    "service": "app-pay-01",
    "environment": "prod",
    "time_range": "PT15M",
    "error_code": "DB_CONN_TIMEOUT",
    "suspected_cause": "database_connection_pool_exhausted",
    "ticket_system": "jira",
    "ticket_priority": "P1",
    "notification_channel": "wecom",
    "notification_target": "payment-oncall"
  },
  "requested_outcomes": [
    "verified_error_fact",
    "jira_p1_ticket_created",
    "oncall_team_notified"
  ],
  "domain": "payment-ops",
  "max_risk": "WRITE_MEDIUM",
  "locale": "zh-CN"
}
```

注意：`requested_outcomes` 是从明确用户目标中提取的粗粒度结果，不是 SAD 的最终子目标拆解。

### 11.3 固定 Registry Snapshot

Registry Head 返回：

```json
{
  "registry_snapshot_id": "rs_20260715_00042",
  "index_revision": "route-index-20260715-01"
}
```

从这一刻起，本次规划不会热切换到新发布的资产版本。

### 11.4 Hard Filter 结果

过滤前共有 8,420 个 Route Header。数据库按 Snapshot、Tenant、ACL、状态、环境、风险和 Runtime 兼容性过滤后，剩余 286 个可见 Header。

被硬过滤的示例：

| asset_ref | 被过滤原因 |
| --- | --- |
| `fsm.jira.p1.create@1.4.0-draft` | `DRAFT`，不在 Snapshot Active/Canary 集合 |
| `fsm.prod.db.restart@3.0.0` | 风险为 `WRITE_HIGH`，超过当前 `max_risk` |
| `fsm.othercorp.notify@1.0.0` | 属于其他 Tenant |
| `tool.slack.notify@2.2.0` | 当前 Tenant 未配置 Tool，且用户明确要求企业微信 |
| `fsm.jira.p1.create@1.2.0` | 不属于当前 Snapshot 的精确版本集合 |

这些资产不会进入 LLM 上下文。

### 11.5 Sparse 召回 Top-4

查询 Token：

```text
app-pay-01 prod DB_CONN_TIMEOUT database pool log verify jira P1 wecom payment-oncall
```

结果：

| Sparse Rank | asset_ref | 命中原因 |
| ---: | --- | --- |
| 1 | `fsm.log.verify_error@2.0.1` | 精确命中 `DB_CONN_TIMEOUT`、prod、log、verify |
| 2 | `fsm.jira.p1.create@1.3.2` | 精确命中 Jira、P1、payment |
| 3 | `fsm.wecom.notify_oncall@2.1.0` | 精确命中 WeCom、payment-oncall |
| 4 | `tool.log.search@4.0.0` | 精确命中 service log 与时间窗查询 |

### 11.6 Dense 召回 Top-4

| Dense Rank | asset_ref | 语义命中原因 |
| ---: | --- | --- |
| 1 | `fsm.log.verify_error@2.0.1` | “检查日志并确认原因”与“形成已验证错误事实”一致 |
| 2 | `fsm.jira.p1.create@1.3.2` | “建立高优先级故障单”与 Jira P1 语义一致 |
| 3 | `tool.log.search@4.0.0` | “查看最近 15 分钟日志”与时间窗日志查询一致 |
| 4 | `fsm.wecom.notify_oncall@2.1.0` | “提醒值班组”与企业消息通知一致 |

### 11.7 RRF 融合

使用 `k=60`：

| Fused Rank | asset_ref | 计算 | RRF Score |
| ---: | --- | --- | ---: |
| 1 | `fsm.log.verify_error@2.0.1` | `1/61 + 1/61` | 0.032787 |
| 2 | `fsm.jira.p1.create@1.3.2` | `1/62 + 1/62` | 0.032258 |
| 3 | `fsm.wecom.notify_oncall@2.1.0` | `1/63 + 1/64` | 0.031498 |
| 4 | `tool.log.search@4.0.0` | `1/64 + 1/63` | 0.031498 |

第三、第四名分数相同，使用稳定二级排序策略决定顺序。本示例优先 `FSM_SHARD`，因为一个已验证 FSM 可以隐藏内部 Tool 细节；实际偏好规则必须通过离线评测配置，不能写死为跨领域真理。

### 11.8 Capability Graph 一跳扩展

从上述候选扩展得到：

| 新增 asset_ref | 来源 | Edge |
| --- | --- | --- |
| `validator.error_fact@1.2.0` | `fsm.log.verify_error@2.0.1` | `REQUIRES_VALIDATOR` |
| `adapter.errorfact_to_jira@1.0.0` | 日志 FSM -> Jira FSM | `COMPATIBLE_VIA_ADAPTER` |
| `tool.jira.issue.create@3.4.0` | `fsm.jira.p1.create@1.3.2` | `DEPENDS_ON` |
| `validator.jira.ticket@1.1.0` | `fsm.jira.p1.create@1.3.2` | `REQUIRES_VALIDATOR` |
| `tool.wecom.message.send@2.5.0` | `fsm.wecom.notify_oncall@2.1.0` | `DEPENDS_ON` |

所有扩展项再次通过当前 Snapshot 和 ACL 检查。

### 11.9 返回给 SAD 的最终初步候选

```json
{
  "request_id": "req_01J2PAY001",
  "registry_snapshot_id": "rs_20260715_00042",
  "index_revision": "route-index-20260715-01",
  "stage": "HEADER_RETRIEVAL_COMPLETE",
  "next_stage": "SAD_ALIGNMENT",
  "candidates": [
    {
      "asset_ref": "fsm.log.verify_error@2.0.1",
      "kind": "FSM_SHARD",
      "summary": "读取服务时间窗日志并形成 VerifiedErrorFact",
      "input_type_summary": "ServiceRef + TimeRange + ErrorHint",
      "output_type_summary": "VerifiedErrorFact",
      "provenance": {"channels": ["sparse", "dense"], "rrf_score": 0.032787}
    },
    {
      "asset_ref": "fsm.jira.p1.create@1.3.2",
      "kind": "FSM_SHARD",
      "summary": "由已验证错误事实创建标准 Jira P1",
      "input_type_summary": "VerifiedErrorFact + ReporterIdentity",
      "output_type_summary": "JiraTicketRef",
      "provenance": {"channels": ["sparse", "dense"], "rrf_score": 0.032258}
    },
    {
      "asset_ref": "fsm.wecom.notify_oncall@2.1.0",
      "kind": "FSM_SHARD",
      "summary": "向授权值班组发送带工单链接的企业微信通知",
      "input_type_summary": "JiraTicketRef + OncallGroupRef",
      "output_type_summary": "NotificationReceipt",
      "provenance": {"channels": ["sparse", "dense"], "rrf_score": 0.031498}
    },
    {
      "asset_ref": "tool.log.search@4.0.0",
      "kind": "PRIMITIVE_TOOL",
      "summary": "按服务、环境和时间窗读取受控日志",
      "provenance": {"channels": ["sparse", "dense"], "rrf_score": 0.031498}
    },
    {
      "asset_ref": "validator.error_fact@1.2.0",
      "kind": "VALIDATOR",
      "summary": "验证错误事实是否具有服务、错误码、时间和日志证据",
      "provenance": {
        "channels": ["graph"],
        "expanded_from": "fsm.log.verify_error@2.0.1",
        "edge_type": "REQUIRES_VALIDATOR"
      }
    },
    {
      "asset_ref": "adapter.errorfact_to_jira@1.0.0",
      "kind": "ADAPTER",
      "summary": "将 VerifiedErrorFact 映射为 Jira P1 输入",
      "provenance": {
        "channels": ["graph"],
        "expanded_from": "fsm.log.verify_error@2.0.1",
        "edge_type": "COMPATIBLE_VIA_ADAPTER"
      }
    }
  ],
  "excluded_body_fields": [
    "fsm.states",
    "tool.credentials",
    "tool.full_openapi",
    "validator.executor_code"
  ]
}
```

### 11.10 本例在这里停止

这份结果仅表示：

- 候选在当前 Snapshot 中存在；
- 调用者有权看到它们；
- Sparse、Dense 或 Capability Graph 认为它们可能相关；
- Header 类型摘要表明它们可能形成可连接路径。

它尚未证明：

- 子目标粒度已经正确；
- 前置条件在当前任务状态中一定满足；
- 每个 Effect 都完全覆盖用户目标；
- Adapter、Validator 和步骤顺序最终可编译；
- 应选择 REUSE、HYBRID 还是 NEW。

这些判断从下一步 SAD Alignment 开始，随后还需 Contract Rerank 和 Blueprint Compiler。将“被召回”直接等同于“可以执行”是必须禁止的实现错误。

---

## 12. 推荐的最小实现顺序

### Phase 0：先固定数据契约

1. 定义 `asset_ref = asset_id@version`；
2. 定义 `kind`、Skill Contract、Route Header、Edge 和 Snapshot Schema；
3. 定义 Tenant、Scope、风险和环境枚举；
4. 定义 Artifact Digest 与不可变发布规则；
5. 准备 100～300 条人工审核的种子资产和检索标注集。

### Phase 1：实现 Registry MVP

1. PostgreSQL 建立 `registry/retrieval/runtime/governance` schema；
2. 对象存储保存 FSM、OpenAPI、Fixture 与报告；
3. 实现 Draft -> Evaluation -> Active 发布事务；
4. 实现 READY Snapshot 和 `registry_head`；
5. 实现按 Snapshot 查询资产及 Contract 的 API。

### Phase 2：实现 Header Retrieval

1. 发布时确定性生成 Route Header；
2. 构建中文 Sparse Index 和 pgvector Dense Index；
3. 实现 Hard Filter、Sparse、Dense、RRF 和一跳 Graph Expansion；
4. Dify 使用 HTTP/Tool 节点调用 Retrieval API；
5. 响应只返回 Header、Provenance 和 Snapshot ID。

### Phase 3：接入后续规划链

1. 将 Header Candidate Set 交给 SAD；
2. 对 SAD 修正后的子目标做 Per-Subgoal Retrieval；
3. 只为 Top-N 加载完整 Contract；
4. Contract Rerank 后再生成 Blueprint；
5. Compiler 通过后才能由 LangGraph Meta-Executor 加载 Body。

---

## 13. 必须通过的验收项

| 验收项 | 通过标准 |
| --- | --- |
| Snapshot 可复现 | 相同请求、身份、Snapshot、索引版本产生相同可见集合和稳定排序 |
| ACL 不泄漏 | 越权资产在数据库候选阶段即为 0 条，不进入日志和 LLM Prompt |
| Header/Body 分离 | 初步召回响应不包含 FSM Body、工具凭据或可执行代码 |
| 索引可重建 | 删除 FTS/Embedding 派生数据后，可由 Registry Header 完整重建 |
| 版本不可变 | Active Artifact 内容变化必须产生新版本和新 Digest |
| Snapshot 固定 | 一次规划从 Retrieval 到 Compiler 始终使用同一 Snapshot |
| Graph 有界 | 初步召回最多扩展一跳，并有 Candidate/Token 上限 |
| 召回质量可测 | 分任务族统计 Recall@K、MRR/NDCG、ACL Filter Error、P95 延迟 |
| 治理闭环 | Trace 只能进入 Candidate/Draft，未经 Evaluation 不得进入 Active Snapshot |
| Dify 职责正确 | Dify 可管理入口和展示，但不能直接覆盖 Active Registry Asset |

---

## 14. 最终回答

1. **Experience Base 与 Registry 的关系**：Experience Base 是“系统经验”的逻辑总称；Registry 是其中经过验证、版本化、可以生产复用的资产事实源；Trace/Evaluation 是它的证据层；Route Header/向量/FTS 是它的检索投影。
2. **FSM、Tools、Skills 保存在哪里**：稳定身份、版本、Contract、ACL、关系和 Snapshot 存 PostgreSQL；大型 FSM Body、OpenAPI、测试与回放制品存 S3/MinIO/Git Artifact Store；FTS/Embedding 是 PostgreSQL 或外部检索引擎中的可重建索引。
3. **具体保存什么**：不仅保存描述和工具序列，还保存输入输出类型、前置条件、效果、副作用、Validator、Adapter、风险、权限、发布状态、版本 Digest、依赖图、执行账本和评测证据。
4. **Capability Retrieval 如何召回**：Task Normalizer 产生结构化上下文；固定 Snapshot；数据库执行 ACL/状态/环境/风险硬过滤；Sparse 和 Dense 并行召回；RRF 融合；Capability Graph 一跳补入依赖、Validator 和 Adapter；最后只返回 Header Candidate Set 给 SAD。
5. **最重要的边界**：相似度只表示“值得进入候选集”，不表示“允许直接执行”。是否可执行必须在 SAD、Contract Rerank 和 Blueprint Compiler 之后决定。
