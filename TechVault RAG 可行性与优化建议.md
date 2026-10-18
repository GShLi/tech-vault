# TechVault RAG 可行性与优化建议

> 评审日期：2026-10-18  
> 评审对象：[TechVault 典阁 - 团队私有技术知识库 RAG 系统](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md)  
> 评审视角：产品可行性、业务流程、技术风险、市场对标、落地优先级

## 1. 结论摘要

**总体判断：技术路线可行，可以进入 PoC，但不建议直接按当前文档全量开发。**

当前方案的“混合检索 + 重排 + 引用 + 权限过滤”是主流且成熟的 RAG 架构。BGE-M3、Elasticsearch、Qdrant、RRF、Rerank 均有成熟实现；面向中英文技术文档做私有知识库也成立。

真正需要补强的不是模型选型，而是以下五项：

1. **文档质量闭环**：解析、分块、人工检查、启用/停用、重建索引。
2. **多轮问答与查询理解**：当前只描述了单次 Query 检索，未解决追问、指代、版本识别和中英文跨语言检索。
3. **权限与数据主权边界**：文档、Git 仓库、云 LLM、SSO、成员离职后的权限与数据归属都需要明确。
4. **索引一致性与可恢复性**：ES 与 Qdrant 双写不是原子操作，删除也不是“同时删除”。
5. **可评测与可运维**：RAGAS 不能替代业务验收集，必须建立召回、引用、答案正确性、越权和延迟指标。

建议先做一个范围受控的 PoC，用真实问题集证明“检索确实比普通搜索和纯向量检索更好”，再决定是否保留 ES + Qdrant 双引擎。

## 2. 当前产品定义

项目目标是建设面向研发团队的私有知识库，支持文件上传、GitHub 文档导入、私有/团队共享权限隔离，并通过混合检索提供带引用的技术问答。核心用户是 `leader`、`member` 和 `viewer`。

当前业务能力可以归纳为六个域：

| 业务域 | 当前能力 | 文档位置 |
| --- | --- | --- |
| 身份与团队 | 注册登录、JWT、团队、角色、成员管理 | [项目文档第 46 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:46) |
| 知识空间 | 一个团队多个知识库空间 | [项目文档第 56 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:56) |
| 文档接入 | PDF、Markdown、TXT、DOCX、GitHub 仓库、增量同步 | [项目文档第 59 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:59) |
| 异步入库 | 解析、清洗、分块、Embedding、ES/Qdrant 写入 | [项目文档第 67 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:67) |
| RAG 问答 | 混合召回、RRF、Rerank、引用、版本过滤 | [项目文档第 71 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:71) |
| 运维管理 | 任务日志、失败重试、模型与检索参数配置 | [项目文档第 79 行](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md:79) |

产品边界清楚，但当前更接近“RAG 系统设计”，还不是完整的“知识库产品设计”。缺少知识治理、内容生命周期、用户反馈、答案质量运营和成员离职后的资产处理。

## 3. 技术可行性核验

### 3.1 可行性评分

| 维度 | 判断 | 说明 |
| --- | --- | --- |
| 核心 RAG 链路 | 高 | BM25 + Dense Retrieval + RRF + Rerank 是成熟方案 |
| 模型选型 | 高 | BGE-M3 的 1024 维稠密向量和 8192 token 输入满足当前场景 |
| 私有化部署 | 中高 | 文档、向量、模型可本地化，但云 LLM 会破坏“数据不出域” |
| 权限模型 | 中 | 基本文档级隔离可行，但缺少组织级 ACL、审计和源系统权限同步 |
| 数据一致性 | 中 | 双写、增量更新、删除、失败恢复需要状态机，不能依赖同步删除 |
| 运维复杂度 | 中高 | Docker Compose 包含较多基础服务，双检索引擎会放大备份、排障和扩容成本 |
| 检索质量 | 中 | 技术术语、代码、版本、中英文跨语言需要真实语料验证 |

### 3.2 已验证的技术事实

1. **BGE-M3 适合当前语料形态。** 官方模型卡说明其支持 100 多种语言、最长 8192 token，同时支持 dense、sparse 和 multi-vector 检索，稠密向量维度为 1024。当前文档只使用 dense 是可行的，ES BM25 可以承担精确词项检索。
2. **RRF 是有效的融合方式，但不是“自动平衡”。** RRF 只使用排名，不使用原始分数，适合融合不同类型检索结果；默认通常给予各路相同权重，不会自动识别关键词问题或语义问题。技术 API、类名、版本号应提高 BM25 权重，概念性问题可提高向量权重。
3. **Qdrant 的权限与版本过滤需要 payload index。** Qdrant 支持 `must`、`should` 等过滤条件，但官方建议对高频过滤字段建立 payload index。`team_id`、`owner_user_id`、`permission`、`product`、`version` 都应纳入索引设计。
4. **ES 单引擎也能完成混合检索。** Elasticsearch 8.x 支持 RRF retriever，Azure AI Search 等托管产品也采用“关键词 + 向量 + RRF + semantic rank”的组合。双引擎不是错误，但需要证明相对单引擎有可量化收益。
5. **“同时删除 ES 与 Qdrant”需要重新表述。** 两个存储之间没有分布式事务。更可靠的做法是文档进入 `deleting` 状态，先停止检索，再异步清理两个索引，最后确认完成。检索层应通过文档状态过滤掉已删除或构建中的版本。

### 3.3 当前方案的主要技术缺口

#### 缺口一：私有化目标与云 LLM 存在冲突

文档目标是“原始文档、向量数据由团队自主保管”，同时支持 OpenAI 等云 API。检索后的文档片段会进入云 LLM 上下文，实际上会离开团队环境。

产品必须增加明确的数据策略：

- 按知识库或团队配置 `仅本地模型`、`允许云模型`。
- 对云模型请求做敏感信息脱敏和审计。
- 在回答界面显示“本次回答是否使用了外部模型”。
- 私有资料与团队共享资料可以有不同的模型策略。

#### 缺口二：只保存当前问答记录，未定义多轮检索

对话历史只能“查看”，并不等于能理解追问。例如用户先问“Spring Boot 3 的自动配置是什么”，再问“它和 2.x 有什么区别”，第二次检索如果只发送“它和 2.x 有什么区别”，会丢失实体和上下文。

需要增加：

- 基于历史的 Query Rewrite。
- 实体、产品、版本、语言等查询意图解析。
- 指代消解与主题延续。
- 回答中标注实际使用的检索范围。

#### 缺口三：文档版本不是单个字符串

`product` 和 `version` 只作为普通元数据字段，无法覆盖以下情况：

- 一篇文档同时适用于 JDK 17、21。
- 同一文档的多个版本需要并存。
- GitHub 仓库的分支、commit、文件路径共同构成版本。
- 旧版本文档过期但用户仍需查询历史问题。

建议拆成 `product`、`version_family`、`version_values[]`、`source_revision`、`valid_from`、`deprecated_at` 等字段，并保留可追溯的来源快照。

#### 缺口四：权限模型只覆盖“文档级”，没有覆盖成员生命周期

当前 `team_shared` / `private` 能实现最基本的隔离，但以下场景未定义：

- 普通成员离职后，私有文档归谁。
- 文档从私有转为团队共享是否需要审批。
- 管理员是否应该看到成员私有文档。
- 只读成员是否能拥有自己的私有文档。
- 团队成员被移除后，其共享文档和私有文档如何处理。
- GitHub 私有仓库的凭据是否按团队隔离和轮换。

建议增加文档所有者转移、离职回收、软删除、共享审批、审计日志和凭据隔离。

#### 缺口五：缺少知识质量运营

当前只有任务失败重试，没有内容失败处理。实际 RAG 常见问题包括：

- PDF 表格和代码块解析错位。
- Markdown 标题层级被切断，检索片段缺少上下文。
- 扫描 PDF 没有 OCR。
- 文档过期但仍被检索。
- 正确召回但答案引用了错误片段。

需要把“解析结果和 chunk”作为产品对象，让管理员可以预览、编辑、禁用、重建和定位原文。

## 4. 主要业务流程

### 4.1 当前业务主流程

```text
团队成员登录
  -> 创建或加入团队
  -> 创建知识库空间
  -> 上传文件或添加 GitHub 仓库
  -> 后端创建文档和异步任务
  -> 解析、清洗、分块
  -> 生成 Embedding
  -> 写入 ES 与 Qdrant
  -> 更新任务状态
  -> 用户选择知识库、产品、版本进行问答
  -> ES 与 Qdrant 并行召回
  -> RRF 融合与 Rerank
  -> LLM 生成回答
  -> 返回答案和引用
```

这条流程可以跑通，但它是“工程流水线”视角。产品视角还缺少内容审核、知识发布、过期治理和效果反馈。

### 4.2 建议的目标流程

```text
接入
  -> 凭据与权限校验
  -> 拉取源快照或上传文件
  -> 暂存并生成内容指纹
  -> 解析与质量检查
  -> 结构感知分块
  -> 注入权限、版本、来源、页码/行号
  -> 构建新索引版本
  -> 抽样验证
  -> 切换为可检索版本

问答
  -> 身份、团队、知识库范围校验
  -> 多轮上下文补全
  -> 意图、产品、版本、语言识别
  -> 过滤条件生成
  -> 关键词与向量并行召回
  -> 去重、RRF、Rerank
  -> 父子 chunk 与相邻上下文组装
  -> LLM 生成或返回“未找到足够证据”
  -> 逐条引用与来源跳转
  -> 用户反馈与失败问题进入知识缺口队列

治理
  -> 文档更新触发差量重建
  -> 文档删除进入软删除与清理队列
  -> 定期质量巡检
  -> 评测集回归
  -> 索引和 Prompt 版本可回滚
```

### 4.3 核心业务对象建议

当前 PG 表设计过于简略，建议至少补充以下对象：

| 对象 | 用途 |
| --- | --- |
| `source_connection` | GitHub 等外部来源的配置、凭据、分支和同步游标 |
| `document_version` | 文档版本、内容指纹、源 revision、处理状态 |
| `chunk` | 分块内容、标题路径、页码/行号、启用状态、质量标记 |
| `ingestion_run` | 一次接入或同步运行的批次、阶段耗时、错误和重试 |
| `index_generation` | 索引版本、Embedding 模型版本、构建状态和切换记录 |
| `conversation` / `message` | 多轮对话、Query Rewrite、检索参数和模型信息 |
| `citation` | 答案与 chunk 的引用关系、原文位置和置信度 |
| `feedback` | 有用/无用、纠错、缺失知识和人工标注 |
| `audit_log` | 权限变更、文档共享、删除、模型配置和访问记录 |

## 5. 市场对标

本次采用代表性产品而非穷举。关注点是可私有化、知识库或企业 RAG 场景。

| 产品 | 公开实现特征 | 对 TechVault 的启示 |
| --- | --- | --- |
| RAGFlow | DeepDoc 文档理解、模板化分块、chunk 可视化与人工干预、Agentic Retrieval、引用溯源 | 文档解析和分块质量是 RAG 的一等公民，不能只作为后台任务 |
| Dify | 可视化工作流、从文档接入到检索的 RAG Pipeline、模型管理、可观测性和 API | 检索链路需要可配置、可观测、可回归，而不是硬编码 |
| AnythingLLM | 工作区式文档问答、独立 collector 处理文档、多用户权限、多向量库和模型提供方 | 文档采集与业务服务解耦；工作区是自然的知识隔离单位 |
| Open WebUI | 本地 RAG、BM25 + 向量混合、Rerank、多种向量库、RBAC、分析和评估 | 混合检索已经是知识库产品的基础能力，差异化在权限和治理 |
| Onyx | 50 多个连接器、增量索引与 checkpoint、源系统 ACL 同步、混合索引、统一权限约束 | 企业知识库的核心壁垒是连接器和权限同步，不只是聊天界面 |
| Azure AI Search | 全文与向量并行检索、RRF、semantic ranking | 托管产品也采用同一套混合检索范式，单引擎可以减少一致性成本 |
| Amazon Bedrock Knowledge Bases | 托管或客户自管 RAG、文档接入、索引、检索、引用和 rerank | 产品需要明确“托管便利性”和“自主可控”之间的边界 |

### 5.1 行业共识

1. **混合检索成为默认选项。** 关键词负责精确术语、代码标识符和版本号，向量负责语义召回。
2. **Rerank 通常位于召回之后。** 先扩大候选集，再用 cross-encoder 缩小到可送入 LLM 的上下文。
3. **文档解析质量决定上限。** 复杂 PDF、表格、图片、代码块和标题层级是主要质量来源。
4. **权限必须进入检索过滤。** 不能先检索再在应用层丢弃，否则会泄露存在性和片段内容。
5. **增量同步与 checkpoint 是连接器基本能力。** 只做“重新克隆仓库”无法支撑长期运行。
6. **产品需要检索调试和评测入口。** 只靠线上问答无法判断问题出在解析、切分、召回还是生成。

### 5.2 与当前项目的主要差距

当前文档已经覆盖“混合检索 + Rerank + 引用”，但在以下方面落后于成熟产品：

- 没有 chunk 级人工检查与纠错。
- 没有检索测试台和业务评测集。
- 没有多轮 Query Rewrite。
- 没有知识缺口和用户反馈闭环。
- GitHub 同步没有 checkpoint、分支快照和失败恢复设计。
- 权限只有文档级，没有源系统 ACL 和审计。
- 没有索引版本切换与回滚。
- 没有流式回答、取消生成和失败降级设计。

## 6. 优化建议

### P0：MVP 开发前必须确定并纳入范围

#### 1. 建立业务黄金集和验收指标

在编码前收集 100 至 300 个真实问题，覆盖：

- 中文问题检索英文文档。
- JDK、Spring Boot、OpenAI API 的精确类名、方法名和版本。
- 同一产品多个版本并存。
- 多轮追问和指代。
- 权限负样本，即用户不应看到其他成员私有文档。
- 文档不存在或证据不足的问题。

建议首批验收指标：

| 指标 | 建议门槛 |
| --- | --- |
| Recall@20 | 达到团队可接受水平，建议先以 85% 作为 PoC 目标 |
| Citation Accuracy | 引用片段确实支持答案，建议 90% 以上 |
| Groundedness | 回答不超出证据范围，建议 90% 以上 |
| Permission Leakage | 必须为 0，不接受百分比豁免 |
| 无答案识别 | 证据不足时明确拒答，不能强行生成 |
| 检索 p95 | 先以 500ms 级为目标压测，再结合 LLM 首 token 时间调整 |
| 入库成功率 | 区分可恢复失败和永久失败，所有失败可定位 |

这些数字不是行业硬标准，而是建议的产品门槛。真实目标应在 PoC 后按团队数据和风险确定。

#### 2. 做“单引擎 vs 双引擎”技术验证

当前设计使用 ES + Qdrant。该方案可行，但会带来：

- 两套索引、两套备份、两套监控。
- 双写失败和版本漂移。
- RRF 前后的分数与过滤语义差异。
- 运维人员需要掌握两种检索系统。

建议 PoC 同时验证：

- 方案 A：ES 负责 BM25，Qdrant 负责 Dense，应用层执行 RRF，再统一 Rerank。
- 方案 B：ES 同时承担 BM25、Dense Vector 和 RRF，再统一 Rerank。
- 可选基线：BM25-only 和 Dense-only，用于先确认混合检索本身是否优于单路检索。

这不是“用几个固定问题分别试一下”的功能验证，而是一次离线检索实验。目标是用同一批数据、模型、过滤条件和查询，判断双引擎带来的召回质量、过滤性能或规模收益，是否足以覆盖额外的写入复杂度、故障面和运维成本。

**公平性控制**

两套方案必须固定以下条件，只替换检索引擎与融合执行位置：

- 使用相同的原始文档、解析结果、chunk 边界和稳定 chunk ID。
- 使用相同的 BGE-M3 模型、向量归一化方式和向量版本。
- 使用相同的 BM25 分词与分析配置、每路 TopK、RRF 参数、Reranker 和最终 TopN。
- 使用相同的权限、团队、产品、版本、文档状态等过滤条件。
- 使用同一份黄金查询集、标注答案、相关性等级和评测脚本。
- 在相同机器规格、索引分片与副本配置下压测；如需不同规格，必须同时报告单位成本。

**查询集分层**

黄金集至少覆盖以下类型，并为每类单独统计指标，避免总体平均值掩盖关键问题：

- 精确 API、类名、方法名、包名和错误码。
- 自然语言概念解释和方案比较。
- 中文问题检索英文技术文档。
- 产品、版本、文档状态等高选择性过滤问题。
- 经过多轮 Query Rewrite 后的追问和指代问题。
- 知识库证据不足、应当拒答的问题。
- 私有文档权限负样本，即当前用户不应召回的内容。

**指标与判定**

| 维度 | 指标 |
| --- | --- |
| 召回质量 | Recall@20、Recall@50、nDCG@10、MRR |
| 生成依据 | Citation Accuracy、Groundedness、无答案识别准确率 |
| 权限安全 | Permission Leakage，必须为 0 |
| 延迟 | 检索 p50/p95、Rerank 前候选数和耗时、高选择性过滤下的 p95 |
| 规模 | 入库吞吐、索引构建时间、索引存储、内存及 CPU/GPU 占用 |
| 同步一致性 | 删除、更新、重建的失败率，以及双写不一致检测结果 |
| 运维成本 | 服务数量、备份恢复时间、告警数量、故障定位步骤和恢复演练耗时 |

建议在实验前冻结判定规则：

- 任一方案出现权限泄露，该方案直接不通过。
- 单引擎在质量指标上不落后时，优先单引擎。
- 双引擎收益处在预设灰区时，优先单引擎。例如可暂定质量差异不超过 2% 选单引擎，2% 至 5% 结合规模和运维成本判断，超过 5% 才进入双引擎保留评估。该阈值是项目决策参数，不是行业标准。
- 双引擎只有在关键查询类型上有显著收益，且 p95、资源成本、备份恢复和一致性风险均可接受时，才保留。

**执行步骤**

1. 冻结语料、解析结果、chunk、Embedding、查询集与相关性标注。
2. 建立统一检索适配层，使 A/B 只替换“召回与 RRF 的执行实现”，复用 Rerank、Prompt、引用和评测链路。
3. 先运行 BM25-only、Dense-only 基线，确认混合检索是否产生真实收益。
4. 分别运行方案 A 和 B，记录每路候选、各路排名、RRF 排名、Rerank 排名、过滤条件和最终上下文。
5. 每个实验条件重复多轮并报告均值与波动，避免用单次结果做架构决策。
6. 单独压测权限过滤、批量删除、文档更新、Embedding 模型切换和全量索引重建。
7. 按解析、分块、召回、融合、重排五个阶段归因失败，不能只比较最终回答。
8. 输出 ADR，记录最终选择、实验证据、未采用方案的原因和触发回滚或重新评估的条件。

**引擎结构设计**

核心原则是“一套主链路，两套检索与索引实现”，不开发两套完整产品。文档解析、分块、Embedding、Rerank、上下文组装、LLM 生成、引用、权限校验和评测只保留一套代码。A/B 通过统一接口和配置切换，避免两套实现逐渐产生不可控差异。

问答链路建议收敛为：

```text
问答请求
  -> 身份、团队、知识库与文档状态校验
  -> Query Rewrite 与查询意图解析
  -> 生成统一 RetrievalRequest
  -> RetrievalRouter 按 engine_mode 选择实现
       A. dual_engine
          -> ES BM25 TopK
          -> Qdrant Dense TopK
          -> 应用层 RRF
       B. elastic_single
          -> ES BM25 + ES Dense
          -> ES RRF
  -> 统一 CanonicalSearchResult
  -> Reranker
  -> 父子 chunk 与相邻上下文组装
  -> LLM 生成、拒答与引用
  -> Trace、评测与成本记录
```

入库链路同样只替换索引写入和校验部分：

```text
统一解析、清洗、分块、Embedding
  -> IndexWriter 按 engine_mode 选择实现
       A. ES BM25 Writer + Qdrant Dense Writer
       B. ES BM25 + Dense 混合 Writer
  -> staging generation 写入
  -> chunk 数、向量数、权限字段和抽样检索校验
  -> 切换 active generation
  -> 延迟清理旧 generation
```

推荐职责边界：

| 模块 | 是否共享 | 责任 |
| --- | --- | --- |
| 文档接入与解析 | 共享 | 文件、GitHub、源 revision、内容指纹和失败重试 |
| 清洗、分块与 Embedding | 共享 | 稳定 `chunk_id`、结构信息、BGE-M3 向量和模型版本 |
| `IndexWriter` | 分别实现 | A 写入 ES + Qdrant；B 写入 ES 混合索引 |
| `Retriever` | 分别实现 | A 双路召回 + 应用层 RRF；B 调用 ES 混合检索 |
| Reranker | 共享 | 接收统一候选结构，模型和参数保持一致 |
| 上下文与 LLM | 共享 | parent-child 组装、Prompt、拒答、引用和流式输出 |
| 评测与 Trace | 共享 | 相同查询、标注、指标采集和 ADR 证据输出 |

建议后端模块按以下边界组织，具体文件名可随现有工程调整：

```text
backend/app/rag/
  ingestion/              # 文件、GitHub、解析、清洗
  chunking/               # 结构感知分块与稳定 ID
  embedding/              # BGE-M3 调用与向量版本
  indexing/
    base.py               # IndexWriter 接口
    dual_engine.py        # ES BM25 + Qdrant Dense
    elastic_single.py     # ES BM25 + Dense
  retrieval/
    base.py               # Retriever 接口
    dual_engine.py        # 双路召回 + 应用层 RRF
    elastic_single.py     # ES 混合检索 + ES RRF
  fusion/                 # RRF 策略与可选的查询感知权重
  rerank/                 # bge-reranker-v2-m3
  context/                # parent-child、相邻 chunk、token 预算
  answer/                 # LLM、拒答、引用与流式输出
  observability/          # 检索 Trace、耗时、成本和错误
  evaluation/             # 黄金集、离线评测与回归脚本
```

统一接口至少固定以下契约，防止下游代码依赖某个检索引擎的私有分数或返回结构：

```python
class SearchRequest:
    query: str
    rewritten_query: str | None
    query_vector: list[float]
    filters: RetrievalFilters
    bm25_top_k: int = 50
    dense_top_k: int = 50
    rrf_k: int = 60
    rerank_input_size: int = 50
    final_top_n: int = 10


class RetrievedChunk:
    chunk_id: str
    document_version_id: str
    content: str
    bm25_rank: int | None
    dense_rank: int | None
    fused_rank: int
    rerank_score: float | None
    source_locator: dict


class SearchResult:
    chunks: list[RetrievedChunk]
    stage_latency: dict[str, float]
    degraded: bool
    trace_id: str


class Retriever:
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class IndexWriter:
    async def stage(self, generation_id: str, chunks: list[Chunk]) -> None:
        ...

    async def validate(self, generation_id: str) -> ValidationResult:
        ...

    async def activate(self, generation_id: str) -> None:
        ...

    async def cleanup(self, generation_id: str) -> None:
        ...
```

索引可以使用隔离命名空间保存实验数据，但结构应与生产 generation 一致：

```text
techvault-a-es-bm25-<generation>
techvault-a-qdrant-dense-<generation>
techvault-b-es-hybrid-<generation>
```

两套方案必须写入同一组关键字段：`tenant_id`、`team_id`、`knowledge_base_id`、`visibility`、`owner_user_id`、`product`、`version_values`、`source_revision`、`doc_status`、`chunk_status` 和 `index_generation`。ES 中需要作为精确过滤条件的字段使用 `keyword`，Qdrant 对应 payload 字段建立 payload index。权限判断必须在召回阶段执行，不能召回后再由应用层删除。

运行参数使用配置或 feature flag 切换，不把方案分支散落在接口和业务代码中：

```text
retrieval.engine_mode=dual_engine|elastic_single
retrieval.bm25_top_k=50
retrieval.dense_top_k=50
retrieval.rrf_k=60
retrieval.rerank_input_size=50
retrieval.final_top_n=10
```

需要特别区分“实验降级”和“生产降级”。离线评测时任一引擎失败都应直接标记实验失败，不能偷偷切换为 BM25-only，否则指标不可解释。生产环境可以另行定义降级策略，例如 A 方案在 Qdrant 故障时临时只用 ES BM25，但必须返回 `degraded=true` 并记录告警；B 方案的 BM25 与 Dense 同属 ES，单引擎减少依赖数量，但 ES 故障时整条混合检索不可用。这个可用性差异也是 A/B 决策的一部分。

每一条问答 Trace 至少记录：`trace_id`、`engine_mode`、Query Rewrite 前后文本、完整过滤条件、每路候选及排名、RRF 排名、Rerank 排名和分数、最终 chunk ID、各阶段耗时、是否降级、模型与 token 成本。离线评测和线上排障使用同一份 Trace 结构，避免实验结论无法复现。

#### 3. 重写索引一致性方案

不要使用“写完 ES 再写 Qdrant，删除时两边一起删”的同步逻辑。建议改为：

1. 文档版本和 chunk 生成稳定 ID。
2. 新索引写入 staging generation。
3. 校验 chunk 数、向量数、权限字段和抽样检索。
4. 原子切换 active generation。
5. 旧 generation 延迟清理。
6. 失败任务从 checkpoint 或阶段边界恢复。

这比“双写 + 定时巡检”更适合知识库这种持续更新的数据。

#### 4. 明确权限和成员生命周期

至少补齐以下规则：

- 默认拒绝，所有查询带 `tenant_id/team_id`。
- 文档权限变更后，检索索引同步更新。
- 成员离职时支持私有文档转移或回收。
- 团队移除成员后立即撤销查询权限。
- 管理员看不到成员私有文档，除非产品明确授权。
- 文档共享、删除、下载、模型配置变更进入审计日志。
- GitHub Token、LLM Key、MinIO 路径不得返回前端。

#### 5. 明确 LLM 数据策略

“私有化部署”不能只描述为“文件和向量保存在本地”。Query Rewrite、Embedding、Rerank 和答案生成都可能把用户问题或文档片段发送给外部服务，因此需要把“数据是否离开部署环境”设计成统一、可审计、默认关闭的模型出境策略。

**设计目标**

- 原始文件、解析文本、chunk、向量和默认检索 Trace 必须保存在本地。
- 任何外部模型调用都必须先经过统一策略判断，不能由业务代码直接调用供应商 SDK。
- `leader` 只能收紧部署级策略，不能突破部署级安全上限。
- 用户只能选择比团队或知识库策略更严格的模型范围。
- 外部调用默认只发送当前问题所需的最少上下文，不发送整篇文档、完整对话历史或内部权限元数据。
- 无法确认策略、数据分类、脱敏结果或供应商配置时，采用失败关闭策略。
- 每次外部模型调用都能回答：谁发起、使用了哪个模型、发送了哪些数据类别、命中了什么策略、是否脱敏、结果和成本是什么。

**数据分类与权限分离**

访问权限回答“谁可以看”，数据分类回答“能否发送给外部模型”，两者不能混为一谈。团队共享文档也可能包含密钥或客户数据，因此必须独立设置敏感级别。

| 分类 | 典型内容 | 默认模型策略 |
| --- | --- | --- |
| `public` | 已公开的 JDK、Spring、开源项目文档 | 允许按团队策略使用外部模型 |
| `internal` | 团队共享但不公开的设计、部署和研发资料 | 默认仅本地，`leader` 可显式允许外部模型 |
| `private` | 成员私有文档、个人笔记 | 默认仅本地，不能被团队级“允许云模型”自动放开 |
| `restricted` | 密钥、Token、客户数据、生产配置和明确禁止出境的资料 | 禁止发送外部模型，优先阻止召回进入外部上下文或直接拒答 |

分类可以由上传者手工指定、按知识库默认值继承或由敏感信息扫描器辅助识别，但不能只依赖自动识别。命中密钥、Token、私钥和连接串时，即使数据分类较低，也必须阻断或强制脱敏并记录审计。

**策略层级**

模型策略按作用域逐层收敛，最终采用最严格的一组约束：

1. 部署级策略：允许的供应商、数据区域、网络出口和绝对禁止出境的分类。
2. 团队策略：团队允许使用的本地与云模型、默认模式和可用供应商。
3. 知识库策略：不同知识库可分别设置 `local_only`、`external_allowed`。
4. 文档策略：文档自身的数据分类可以进一步收紧知识库策略。
5. 用户请求：用户只能选择本地模型或更小范围，不能覆盖上层拒绝。

建议支持三种运行模式：

| 模式 | 行为 |
| --- | --- |
| `local_only` | 所有 Query Rewrite、Embedding、Rerank 和生成只能调用本地模型 |
| `external_allowed` | 满足分类和供应商限制时，可以调用经批准的外部模型 |
| `external_required` | 仅用于明确允许的知识库；若外部模型不可用则失败，不静默切换 |

当请求涉及多个文档分类时，以候选上下文中最高敏感级别为准。外部模型不允许处理该级别时，优先切换到本地模型；本地模型也不可用时明确拒答，不能悄悄删除高敏感片段后继续生成，否则用户会误以为答案基于完整证据。

**统一模型网关**

所有模型调用收敛到 `LlmGateway`，业务模块不得直接持有外部模型 API Key。网关负责策略判断、数据最小化、脱敏、供应商调用、超时、重试、成本和审计。

```text
业务请求
  -> AuthContext 与知识库范围
  -> PolicyResolver 计算最终策略
  -> DataClassifier 确认上下文最高敏感级别
  -> EgressSanitizer 做字段白名单与敏感信息脱敏
  -> ProviderRouter 选择本地或外部模型
  -> ProviderAdapter 调用模型
  -> ResponseInspector 记录结果、成本与异常
  -> AuditWriter 写入不含原文的调用审计
```

策略判断使用统一决策对象，避免每个业务模块各自解释规则：

```python
class ModelPolicyDecision:
    allow_external: bool
    allowed_provider_ids: list[str]
    max_data_classification: str
    allowed_model_ids: list[str]
    allow_conversation_history: bool
    allow_document_metadata: bool
    require_redaction: bool
    fallback_mode: str
    reason_code: str
    policy_version: str
```

`LlmGateway` 至少要覆盖以下模型调用，任何绕过网关的实现都不允许进入发布版本：

- Query Rewrite：会把用户原始问题发送给模型。
- Embedding：如果使用远程接口，会把文档和查询文本发送给模型。
- Rerank：如果使用远程接口，会把候选 chunk 发送给模型。
- 答案生成：会把 Query 和最终上下文发送给模型。

当前 BGE-M3 和 bge-reranker-v2-m3 按本地服务设计，不产生额外出境。未来切换为托管 Embedding 或 Rerank 时，必须自动继承同一套策略，不能把“LLM 数据策略”只应用在答案生成阶段。

**外部请求最小化**

发送给外部模型的数据使用字段白名单，只允许：

- 当前需要回答的用户问题或经过确认的 `rewritten_query`。
- 最终进入上下文的 TopN chunk 内容。
- 必要的格式指令和输出约束。
- 不含业务含义的临时引用编号。

默认不允许发送：

- 原始文件和完整文档。
- 未进入最终上下文的召回候选。
- 用户名、邮箱、成员列表、`tenant_id`、`team_id` 和 ACL。
- 文件服务器路径、MinIO 路径、GitHub Token、数据库连接串和模型 API Key。
- 完整历史对话、系统日志、审计日志和其他知识库内容。
- 可还原内部数据结构的真实 `chunk_id` 和文档主键；外部请求使用本次调用内有效的临时编号，返回后再在本地映射回真实引用。

`allow_conversation_history` 默认关闭。确需多轮上下文时，只发送经过 Query Rewrite 的必要对话摘要，不发送整个会话。除非管理员显式开启 `allow_document_metadata`，否则文档名称、产品、版本和来源路径不进入外部请求；引用展示在本地使用检索结果重建。

外部调用前必须执行敏感信息扫描和脱敏，至少覆盖常见 API Key、Bearer Token、JWT、私钥、密码、数据库连接串、内部 URL、邮箱和 IP。脱敏不能只做正则替换，还应拒绝命中 `restricted` 分类的内容。脱敏失败时返回策略拒绝，不允许“按原文发送并记录警告”。

**供应商与凭据管理**

外部供应商需要独立登记和审批，至少记录：

- 供应商名称、API 地址、允许的数据区域和网络出口。
- 支持的模型列表、上下文长度和价格。
- 是否用于训练、数据保留周期、零保留能力和删除机制。
- 合同或安全评审状态、审批人和有效期。
- 允许的最大数据分类、是否允许对话历史和是否要求脱敏。
- 健康检查、超时、速率限制和熔断参数。

API Key 只保存在服务端密钥管理系统或加密配置中，禁止返回前端，禁止写入普通日志和模型调用参数。生产环境通过固定出口代理访问供应商域名白名单，不允许前端直接调用模型，也不允许普通管理员填写未经审批的任意 URL。

建议新增以下配置对象：

| 对象 | 关键字段 |
| --- | --- |
| `llm_provider` | `provider_type`、`endpoint`、`data_region`、`retention_mode`、`security_status`、`expires_at` |
| `llm_model` | `provider_id`、`model_name`、`capability`、`context_limit`、`input_price`、`output_price`、`enabled` |
| `llm_data_policy` | `scope_type`、`scope_id`、`default_mode`、`allowed_providers`、`max_classification`、`allow_history`、`require_redaction` |
| `llm_invocation` | `trace_id`、`user_id`、`knowledge_base_id`、`policy_version`、`provider_id`、`model_id`、`data_classification`、`redaction_hits`、`token_count`、`cost`、`latency`、`status` |

`llm_invocation` 默认只记录元数据、数据分类、内容哈希和脱敏命中数量，不记录请求原文。需要保存完整 Prompt 做调试时，必须单独开启短期加密快照，设置保存期限和访问权限，并允许团队随时关闭。

**审计与可观测性**

每次模型调用记录以下信息：

- 调用类型：`query_rewrite`、`embedding`、`rerank` 或 `answer`。
- 本地或外部路由、供应商、模型和数据区域。
- 最终命中的策略版本与拒绝或允许原因。
- 发送的数据分类、chunk 数量、字符数、token 数和内容哈希。
- 脱敏命中类型与数量，不记录命中的原始值。
- 是否包含对话历史、是否包含文档元数据。
- 请求耗时、首 token 时间、总耗时、token 成本、重试和错误。
- 用户、团队、知识库、问答 Trace ID 和 `degraded` 状态。

策略变更、供应商启用、API Key 轮换、云模型调用开关和调试快照开启必须进入审计日志。管理员查看审计时只能看到数据类别和调用元数据，不能通过审计系统绕过文档权限读取 chunk 原文。

**失败与降级**

- 默认 `local_only`，PoC 未完成安全评审前不开放外部模型。
- 策略服务不可用时失败关闭，只有本地模型可选，不允许直接调用外部供应商。
- 外部模型超时、限额或不可用时，如果策略允许本地回退，回答中明确显示“已切换本地模型”；否则返回可解释错误。
- 本地模型不可用且策略不允许外部调用时明确拒答，不跨数据边界自动重试。
- 脱敏器、敏感信息扫描器或策略版本读取失败时，停止外部调用。
- 禁用静默回退。任何 model 或 route 变化都写入回答元数据和调用审计。

**产品界面**

- 团队设置中提供“默认本地”“允许指定外部模型”“禁止外部模型”三种选项。
- 知识库设置中可以进一步收紧，不能放宽团队限制。
- 文档上传和预览页支持查看和调整数据分类，`restricted` 分类默认不可被外部模型使用。
- 问答页显示本次回答使用的本地或外部模型；发生回退时显示明确状态。
- 管理员可以查看外部调用趋势、拒绝原因、数据分类分布、成本和供应商可用性。
- 普通用户不能查看或修改 API Key、供应商地址和安全评审信息。

**PoC 验收用例**

1. 部署策略为 `local_only` 时，即使配置了外部 API Key，也不发生任何外部网络请求。
2. 知识库允许云模型，但候选上下文包含 `private` 或 `restricted` 文档时，按策略切换本地或拒答。
3. 文档中出现 API Key、JWT、私钥或数据库连接串时，外部请求被阻断或脱敏，审计中有命中类型但没有原始值。
4. 外部模型不可用时，不自动突破知识库策略；允许回退时返回 `degraded=true` 和本地模型标识。
5. 查询外部调用审计时，无法通过审计记录读取无权限文档的正文。
6. Query Rewrite、Embedding、Rerank 和答案生成都无法绕过 `LlmGateway`。
7. `leader` 不能放宽部署级禁止项，`member` 不能覆盖团队或知识库策略。
8. 关闭外部模型后，所有新增调用立即停止，不依赖缓存或长时间连接继续发送数据。

#### 6. 增加多轮 Query Rewrite

每次检索前生成“检索用的独立问题”，保留原始问题用于回答和审计。重点解决：

- “它、这个、上面说的”等指代。
- 用户省略产品名和版本。
- 中英文混合表达。
- 追问中的时间范围、版本范围和比较对象。

#### 7. 采用查询感知的混合检索

不要固定一套 RRF 权重覆盖所有问题。建议：

- 精确标识符问题提高 BM25 权重。
- 概念解释、方案比较提高向量权重。
- 检测产品/版本后自动增加过滤条件。
- 中文问题检索英文文档时，可以增加“翻译后检索”支路，保留原查询向量支路。
- 建立每次检索的调试信息，包括召回来源、排名、重排分数和最终上下文。

#### 8. 做结构感知分块和上下文组装

不同内容使用不同策略：

- Markdown 按标题层级切分，保留标题路径。
- 代码按语言、函数、类、代码块边界切分，避免截断。
- PDF 保留页码、章节和表格结构。
- API 文档保留接口名、参数表、示例和版本。
- 采用 parent-child 或 small-to-big 检索，小块负责召回，大块负责给 LLM 足够上下文。

#### 9. 增加 chunk 预览、编辑和启停

这是知识库产品的高价值能力，建议优先于 Agent 能力：

- 展示 chunk 内容和原文定位。
- 支持编辑、禁用、重新生成。
- 展示解析失败或低质量片段。
- 支持按文档、来源、版本、状态过滤。
- 定时重建索引时保留人工修改记录。

#### 10. 增加引用、拒答和反馈体验

- 回答必须流式展示，支持停止生成。
- 每条引用可跳转到文档、页码、标题或代码行。
- 证据不足时明确返回“知识库中没有足够依据”。
- 用户可标记“有用/无用/引用错误/知识缺失”。
- 失败问题进入知识缺口队列，反向驱动文档补充。

#### 11. 增加可观测性和成本记录

每次问答记录：

- Query Rewrite 前后文本。
- 检索过滤条件。
- 各路召回候选、RRF 排名、Rerank 排名。
- 最终送入 LLM 的 chunk ID 和 token 数。
- 模型、耗时、错误和成本。
- 用户反馈和引用点击。

没有这些记录，后续无法判断是检索、排序还是生成出了问题。

### P2：规模化和差异化

1. 增加 Confluence、Notion、Slack、Google Drive、SharePoint 等连接器。
2. 对支持的来源同步 ACL，而不是只做文档级手工权限。
3. 引入索引 generation 和 Embedding 模型切换。
4. 评估 BGE-M3 sparse 或 ColBERT，但先用业务黄金集证明收益。
5. 增加 Agentic Retrieval，用于复杂比较、多跳问题和跨文档研究。
6. 增加知识图谱、摘要、Wiki、时间线等知识编译能力，但不要作为 MVP 前置条件。
7. 建立离线评测和发布门禁，任何分块、Embedding、Rerank、Prompt 变更都跑回归。

## 7. 推荐产品范围

### 阶段一：PoC

目标不是做完整知识库，而是验证核心价值：

- 1 个团队。
- 文件上传和单个 GitHub 仓库接入。
- 3 类代表性文档：Markdown 技术文档、PDF 手册、代码片段。
- 完成 ES 单引擎与 ES + Qdrant 双引擎的同条件离线对照验证。
- 完成解析、分块、检索、Rerank、引用和多轮问答的最小闭环。
- 用黄金集证明比“只用向量检索”和“只用关键词检索”更好。

### 阶段二：MVP

- 团队、角色、知识库空间。
- 文件与 GitHub 增量同步。
- 文档版本、任务、chunk 管理和索引重建。
- 多轮问答、版本过滤、引用、拒答、反馈。
- 权限负样本测试和审计日志。
- 基础监控、备份和恢复。

### 阶段三：团队规模化

- 更多连接器和 ACL 同步。
- 索引 generation 与模型切换。
- 知识治理、评测平台和运营看板。
- Agentic Retrieval、复杂研究和知识编译。

## 8. 关键风险与控制

| 风险 | 影响 | 控制措施 |
| --- | --- | --- |
| 只验证“能回答”，不验证“检索是否正确” | 上线后答案看似流畅但不可信 | 黄金集、Recall、Citation Accuracy、拒答率 |
| 双索引长期不一致 | 删除后仍被召回、引用失效 | generation、幂等、软删除、巡检和重建 |
| 权限漏洞 | 私有文档泄露 | 默认拒绝、检索过滤、接口二次校验、权限负样本 |
| 解析质量差 | 召回不到正确片段 | 分块预览、OCR、结构感知切分、人工干预 |
| 多轮问题丢失上下文 | 追问答非所问 | Query Rewrite 和对话状态 |
| 云 LLM 泄露私有内容 | 违反团队数据要求 | 模型策略、脱敏、审计、本地模型选项 |
| 组件过多导致难运维 | 故障定位和扩容成本高 | PoC 验证双引擎必要性，核心链路先收敛 |
| 缺少反馈闭环 | 知识库越用越旧 | 知识缺口队列、过期策略、定期重建 |

## 9. 最终建议

**建议继续推进，但先把项目从“功能清单”收敛为一个可验证的产品闭环。**

最重要的三个决策是：

1. 先证明混合检索在真实技术问题上优于单路检索，并决定是否保留 ES + Qdrant 双引擎。
2. 把文档解析、chunk 质量和权限治理提升为 MVP 核心能力，而不是后台实现细节。
3. 在多轮问答、引用、拒答和反馈上建立产品体验，不要过早投入 Agent 和复杂知识编译。

如果 PoC 能达到权限零泄露、技术问题召回稳定、引用可验证、证据不足可拒答，当前架构具备进入 MVP 的条件。

## 10. 参考资料

- [RAGFlow GitHub](https://github.com/infiniflow/ragflow)
- [Dify GitHub](https://github.com/langgenius/dify)
- [AnythingLLM GitHub](https://github.com/Mintplex-Labs/anything-llm)
- [Open WebUI GitHub](https://github.com/open-webui/open-webui)
- [Onyx GitHub](https://github.com/onyx-dot-app/onyx)
- [Onyx indexing pipeline](https://github.com/onyx-dot-app/onyx/blob/main/.agents/feature-map/components/indexing-pipeline.md)
- [Onyx permission sync](https://github.com/onyx-dot-app/onyx/blob/main/.agents/feature-map/components/permission-sync.md)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [Qdrant filtering](https://qdrant.tech/documentation/concepts/filtering/)
- [Elasticsearch reciprocal rank fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
- [Azure AI Search hybrid search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
- [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
