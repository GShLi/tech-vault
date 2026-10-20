# TechVault 典阁 — 团队私有技术知识库 RAG 系统设计

> 文档版本：V2.0  
> 编制日期：2026-10-18  
> 文档状态：PoC 设计基线  
> 建设目标：构建面向研发团队的私有技术知识库，支持文件与 GitHub 文档接入、权限隔离、结构感知分块、混合检索、多轮问答、可验证引用、拒答、反馈和索引回滚。  
> 核心原则：单一产品主链路；权限在召回阶段生效；默认数据不出域；检索质量由离线黄金集和发布门禁验证。

## 目录

1. [项目概述](#1-项目概述)
2. [业务需求与功能模块](#2-业务需求与功能模块)
3. [非功能需求](#3-非功能需求)
4. [整体系统架构](#4-整体系统架构)
5. [技术栈详细选型](#5-技术栈详细选型)
6. [核心数据流转流程](#6-核心数据流转流程)
7. [权限与数据治理](#7-权限与数据治理)
8. [LLM 数据出境策略](#8-llm-数据出境策略)
9. [RAG 检索与生成设计](#9-rag-检索与生成设计)
10. [单引擎与双引擎对照验证](#10-单引擎与双引擎对照验证)
11. [存储设计](#11-存储设计)
12. [API 设计](#12-api-设计)
13. [评测与发布门禁](#13-评测与发布门禁)
14. [部署与运维](#14-部署与运维)
15. [实施阶段与验收](#15-实施阶段与验收)
16. [项目风险与应对](#16-项目风险与应对)
17. [附录：术语说明](#17-附录术语说明)

------

## 1. 项目概述

### 1.1 项目背景

团队内部存在大量技术文档、手册、API 参考资料和私有研发资料，包括 JDK、Spring Boot、OpenAI 官方文档、内部设计文档、部署手册和代码仓库说明。当前资料分散在文件系统、GitHub 和成员个人目录中，查找成本高，答案难以追溯，成员离职后知识资产也缺少明确的转移和治理机制。

TechVault 典阁用于统一管理团队技术知识，支持文件上传和 GitHub 仓库同步，通过关键词与向量混合检索提供带引用的技术问答。系统同时承担知识质量控制职责：不仅展示“能回答什么”，还要能判断解析、分块、召回、重排和生成分别出了什么问题。

### 1.2 项目目标

1. 统一管理团队技术文档，支持 PDF、Markdown、TXT、DOCX 和 GitHub 仓库接入。
2. 实现个人私有、团队共享和受限资料的分级隔离，权限条件进入检索过滤。
3. 支持 BM25 与 Dense Retrieval 混合召回、RRF 融合和 Rerank。
4. 支持中文问题检索英文技术文档、精确 API 名称检索、产品与版本过滤。
5. 支持多轮 Query Rewrite，使追问、指代和省略表达能够正确检索。
6. 返回可定位到文档、页码、标题或代码行的引用，并在证据不足时明确拒答。
7. 将 chunk 作为可治理对象，支持预览、编辑、禁用、重建和人工修改继承。
8. 通过索引 generation 实现原子切换、回滚、软删除和失败恢复。
9. 默认将原始文件、解析文本、chunk、向量和检索 Trace 保存在本地，外部模型默认关闭。
10. 建立业务黄金集、离线评测、线上 Trace 和发布门禁，任何检索链路变更都可回归验证。

### 1.3 适用用户

| 角色 | 主要能力 |
| --- | --- |
| `admin` | 管理系统级模型策略、系统供应商准入和系统健康 |
| `leader` | 管理成员、团队策略、知识库、模型策略、审计和评测配置 |
| `member` | 上传文档、添加 GitHub 仓库、管理自己的私有文档、问答和反馈 |
| `viewer` | 查看有权限的共享文档、问答和查看引用，不能上传或修改资料 |

`admin` 和 `leader` 默认不能查看成员私有文档正文。权限规则详见第 7 章。

### 1.4 建设范围

#### PoC 范围

- 1 个团队，1 至 3 个知识库空间。
- 文件上传和单个 GitHub 仓库接入。
- Markdown 技术文档、PDF 手册和代码片段三类代表性语料。
- 文档解析、结构感知分块、Embedding、双索引写入、混合检索和 Rerank。
- 多轮问答、引用、拒答和基础反馈。
- ES 单引擎与 ES + Qdrant 双引擎的同条件离线对照实验。
- 100 至 300 条黄金查询和基础自动评测脚本。

#### MVP 范围

- 团队、角色和知识库空间管理。
- 文件与 GitHub 增量同步、失败恢复和索引 generation 回滚。
- 文档版本、chunk 管理、权限生命周期和审计日志。
- 多轮问答、版本过滤、流式回答、引用跳转、拒答和反馈。
- 模型出境策略、供应商准入、调用审计和本地模型回退。
- 基础监控、告警、备份和恢复演练。

#### 规模化阶段

- Confluence、Notion、Slack、Google Drive、SharePoint 等连接器。
- 源系统 ACL 同步、知识图谱、摘要和知识编译。
- BGE-M3 sparse、ColBERT 和 Agentic Retrieval 的收益验证。
- 跨区域部署、高可用和大规模容量治理。

上述能力已经纳入路线图，但不作为 PoC 和 MVP 的前置条件。

### 1.5 设计原则

1. **一套主链路。** 解析、分块、Embedding、Rerank、上下文组装、生成、引用和评测共用一套代码，只对索引写入和召回实现做适配。
2. **先证明再复杂化。** 双引擎必须通过质量、性能、一致性和运维成本对照后再成为默认方案。
3. **权限前置。** 授权条件必须进入 ES 和 Qdrant 的召回过滤，不得先召回再在应用层删除。
4. **默认不出域。** 任何 Query Rewrite、Embedding、Rerank 和答案生成的外部调用都必须经过统一策略网关。
5. **证据优先。** 回答只能基于最终上下文，引用必须可定位；证据不足时拒答。
6. **可回滚。** 入库、权限变更和模型切换都通过版本化对象发布，失败时回到上一个可用 generation。
7. **可评测。** 检索参数、分块规则、Embedding、Rerank 和 Prompt 变更都必须可复现、可回归。

------

## 2. 业务需求与功能模块

### 2.1 用户与团队管理

1. 内置超级管理员登录和 JWT 身份认证；禁止外部自助注册，所有普通用户由管理员创建并分配团队角色。
2. 团队只能由管理员创建；团队负责人可邀请、移除成员并变更角色。
3. 团队成员生命周期：离职、禁用、重新启用和私有文档转移。
4. 用户个人信息管理和密码策略。
5. 所有成员、角色和权限变更写入审计日志。

### 2.2 知识库与文档管理

一个团队可以创建多个知识库空间，每个空间有独立的成员范围、默认数据分类和模型策略。

1. 知识库空间支持新建、编辑、归档和删除。
2. 文档接入支持：
   - PDF、Markdown、TXT、DOCX 文件上传。
   - GitHub 仓库地址、分支和路径过滤。
   - Markdown、TXT、HTML 和允许的源码文件。
   - GitHub 增量同步、checkpoint、分支快照和内容指纹。
3. 文档可见性支持：
   - `private`：仅上传者本人和明确授权用户可见。
   - `team_shared`：知识库成员范围内可见。
   数据分类单独使用 `public`、`internal`、`private`、`restricted`；`restricted` 表示禁止进入外部模型，不改变文档的可见性。
4. 文档元数据包括：
   - `source_type`、`source_uri`、`source_revision`。
   - `product`、`version_family`、`version_values`。
   - `valid_from`、`deprecated_at`、`owner_user_id`。
   - `data_classification`、`content_hash`、`doc_status`。
5. 文档管理支持列表、预览、解析状态、版本历史、复制来源链接、删除和保留期内恢复。
6. 删除采用保留窗口软删除：立即停止召回，保留原始对象供恢复；过期后由后台巡检异步清理索引、对象存储和缓存。
7. 同一内容通过内容指纹识别，避免重复入库。

### 2.3 异步入库与任务管理

1. 上传和同步任务进入 Celery 队列。
2. 任务状态包括：`queued`、`fetching`、`parsing`、`chunking`、`embedding`、`indexing`、`validating`、`completed`、`failed`、`deleting`、`cancelled`。
3. 前端展示每个阶段的进度、失败原因、可重试性和最近一次成功时间。
4. 任务日志记录阶段耗时、输入输出数量、错误类型和重试次数。
5. 可恢复失败从阶段边界或 checkpoint 继续，不可恢复失败停止并保留原始文件。
6. 批量重建使用 ingestion run，单文档任务仍可独立追踪。

### 2.4 Chunk 管理

Chunk 是产品对象，不只是索引中间数据。

1. 展示 chunk 内容、所属文档版本、标题路径、页码、代码行号和来源链接。
2. 支持按文档、来源、产品、版本、状态和质量标记过滤。
3. 支持编辑、禁用、启用、重新生成和查看历史版本。
4. 展示解析异常、空文本、超长、低 OCR 质量、表格断裂等质量标记。
5. 人工修改写入 `chunk_override`，与自动生成内容分离。
6. 文档重建时通过 `logical_chunk_key` 继承人工修改；无法匹配时进入待确认队列。
7. 被禁用的 chunk 不进入索引，但保留审计和恢复能力。

### 2.5 RAG 智能问答

1. 支持中文、英文和中英混合问题。
2. 每次问答可选择知识库、产品、版本和数据范围。
3. 多轮对话先执行 Query Rewrite，生成用于检索的独立问题。
4. 检索前识别查询类型、产品、版本、语言和必要的过滤条件。
5. 支持 BM25 与 Dense Retrieval 混合召回、RRF 和 Rerank。
6. 支持流式展示回答和中途停止生成。
7. 引用可跳转到原文页码、标题路径或代码行。
8. 证据不足时返回“知识库中没有足够依据”，不强行生成。
9. 用户可反馈“有用、无用、引用错误、知识缺失”。
10. 失败问题进入知识缺口队列，支持后续补充文档或建立评测样本。

### 2.6 运营与治理

1. 知识缺口队列：聚合无答案、低引用率和用户反馈。
2. 文档生命周期：过期提醒、废弃标记、重复文档和版本清理。
3. 检索调试台：查看 Query Rewrite、过滤条件、候选、RRF、Rerank 和最终上下文。
4. 评测管理：黄金集、开发集、测试集、回归结果和发布记录。
5. 模型治理：供应商准入、模型可用性、数据分类策略和调用成本。
6. 审计中心：登录、权限、文档共享、删除、模型配置和索引切换。

### 2.7 后台基础能力

1. 系统参数、团队策略和知识库策略配置。
2. 检索参数：召回数量、RRF 参数、Rerank 数量和最终 TopN。
3. 模型参数：Embedding、Rerank、本地 LLM 和外部 LLM 配置。
4. 索引管理：generation 列表、构建状态、激活版本和回滚。
5. 系统监控、任务监控、备份状态和存储使用率。

------

## 3. 非功能需求

以下为 PoC 初始目标，PoC 结束后根据真实语料、硬件和业务风险调整。权限泄露不接受百分比豁免。

| 维度 | 要求 |
| --- | --- |
| 权限安全 | 权限过滤在召回阶段执行；Permission Leakage 必须为 0 |
| 检索质量 | Recall@20 初始目标不低于 85%；nDCG@10、MRR 按查询类型分别统计 |
| 答案依据 | Citation Accuracy 不低于 90%；Groundedness 不低于 90% |
| 拒答 | 证据不足问题必须明确拒答，不允许无依据补全 |
| 检索延迟 | 检索与 Rerank p95 初始目标 500ms 级，具体硬件和规模见评测报告 |
| 索引一致性 | active generation 通过完整性校验；删除和权限撤销后不得继续召回 |
| 可用性 | MVP 目标 99.5%；模型或索引故障有明确降级和告警 |
| 可恢复性 | 支持索引 generation 回滚；备份恢复演练至少每季度一次 |
| 数据安全 | 原始文件、文本、chunk、向量和默认 Trace 保存在本地 |
| 可观测性 | 每次问答可追踪 Query、过滤、召回、融合、重排、上下文、模型和成本 |
| 可扩展性 | 解析、Embedding、Rerank、检索和生成服务可独立扩容 |
| 兼容性 | 支持英文技术文档、代码片段、中文文档和中英文混合查询 |

------

## 4. 整体系统架构

### 4.1 逻辑架构

```text
前端层（Vue3）
    |
Nginx / HTTPS
    |
FastAPI 业务后端
├─ 身份、团队、知识库、文档、权限
├─ RAG 编排与 RetrievalRouter
├─ LlmGateway 与数据出境策略
├─ Chunk 管理、反馈、审计、评测
└─ Redis（缓存 + Celery Broker）
    |
Celery 异步任务集群
├─ 文件与 GitHub 接入
├─ 解析、清洗、结构感知分块
├─ BGE-M3 Embedding
├─ IndexWriter 写入与校验
└─ generation 切换与清理

存储层
├─ PostgreSQL：业务数据、权限、版本、任务、Trace、审计
├─ MinIO：原始文件、源快照、可选调试快照
├─ Elasticsearch 8.x：BM25、Dense Vector、RRF
└─ Qdrant：Dense Vector、payload 过滤

模型服务
├─ BGE-M3 Embedding（本地）
├─ bge-reranker-v2-m3（本地）
├─ 本地 LLM：vLLM / Ollama
└─ 经审批的外部 LLM
```

### 4.2 一套主链路，两套索引与召回实现

项目不开发两套完整产品。A/B 方案只替换 `IndexWriter` 和 `Retriever`，其余链路共享。

| 模块 | 是否共享 | 责任 |
| --- | --- | --- |
| 文档接入与解析 | 共享 | 文件、GitHub、源 revision、内容指纹和失败重试 |
| 清洗、分块与 Embedding | 共享 | 稳定 chunk 标识、结构信息、BGE-M3 向量和模型版本 |
| `IndexWriter` | 分别实现 | 双引擎写 ES + Qdrant；单引擎写 ES 混合索引 |
| `Retriever` | 分别实现 | 双路召回 + 应用层 RRF；ES 混合检索 + ES RRF |
| Reranker | 共享 | 接收统一候选结构，模型与参数保持一致 |
| 上下文与 LLM | 共享 | 父子 chunk、相邻上下文、Prompt、拒答、引用和流式输出 |
| Trace 与评测 | 共享 | 相同查询、标注、指标和 ADR 证据输出 |

### 4.3 引擎配置

PoC 默认使用现有双引擎方案，同时必须实现单引擎适配器。MVP 的正式默认值由 ADR 决定。

```text
retrieval.engine_mode=dual_engine|elastic_single
retrieval.bm25_top_k=50
retrieval.dense_top_k=50
retrieval.rrf_k=60
retrieval.rerank_input_size=50
retrieval.final_top_n=10
retrieval.answer_context_top_n=8
```

方案分支只能存在于工厂、配置和适配器中，不能散落在文档、问答、权限和评测代码里。

### 4.4 统一接口契约

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

`SearchRequest` 是后端内部已经解析完成的检索请求。普通业务 API 不暴露 TopK、RRF 和 Rerank 参数；这些值由 `RetrievalConfig` 注入，评测任务通过构造不同的配置做 A/B 实验。

### 4.5 推荐模块边界

```text
backend/app/rag/
  ingestion/              # 文件、GitHub、解析、清洗
  chunking/               # 结构感知分块与稳定标识
  embedding/              # BGE-M3 调用与向量版本
  indexing/
    base.py               # IndexWriter 接口
    dual_engine.py        # ES BM25 + Qdrant Dense
    elastic_single.py     # ES BM25 + Dense
  retrieval/
    base.py               # Retriever 接口
    config.py             # 引擎模式和检索参数
    router.py             # 按后端配置选择 Retriever
    in_memory.py          # 本地验证适配器
    dual_engine.py        # 双路召回 + 应用层 RRF
    elastic_single.py     # ES 混合检索 + ES RRF
  fusion/                 # RRF 与查询感知权重
  rerank/                 # bge-reranker-v2-m3
  context/                # parent-child、相邻 chunk、token 预算
  answer/                 # LLM、拒答、引用和流式输出
  llm_gateway/            # 策略、脱敏、路由、成本和审计
  observability/          # 检索 Trace、耗时、成本和错误
  evaluation/             # 黄金集、离线评测与回归脚本
```

`modules/ingestion` 负责任务编排、状态和重试；`rag/ingestion` 负责解析、清洗等 RAG 数据处理；`rag/parsing` 存放具体解析器适配器。

### 4.6 实验降级与生产降级

- 离线评测中任一引擎失败，实验直接标记失败，不自动切换为 BM25-only。
- 生产环境 A 方案在 Qdrant 故障时可以降级为 ES BM25，但必须返回 `degraded=true` 并告警。
- B 方案的 BM25 与 Dense 同属 ES，ES 故障时整条混合检索不可用。
- 任何降级都记录在回答元数据和 Trace 中，不能静默发生。

------

## 5. 技术栈详细选型

### 5.1 前端

- Vue3 + Vite。
- Pinia 状态管理。
- Arco Design 组件库。
- pdf.js、vue-markdown-preview、代码高亮组件。
- Axios。
- Nginx 托管静态资源。

### 5.2 业务后端

- Python 3.10+。
- FastAPI 异步接口。
- SQLAlchemy 2.0。
- Pydantic v2。
- JWT + OAuth2。
- Unstructured、Trafilatura 分别处理 PDF、DOCX、TXT 和 HTML。
- GitPython + PyGitHub 处理仓库克隆、文件遍历和增量同步。
- 分块优先使用项目自研结构感知策略，可复用 LangChain 的 Markdown 和递归切分工具。
- RAG 编排使用项目内显式检索链路，核心接口由 `Retriever`、`IndexWriter` 和 `LlmGateway` 约束。

### 5.3 异步任务

- Celery Worker。
- Redis 作为 Broker 和短期缓存。
- Flower 查看任务状态。
- ingestion run 和文档任务状态持久化在 PostgreSQL。

### 5.4 存储与检索

1. PostgreSQL：业务数据、权限、版本、chunk 元数据、任务、Trace 和审计。
2. MinIO：原始文件、GitHub 源快照和可选短期调试快照。
3. Elasticsearch 8.x：
   - BM25 关键词检索。
   - `dense_vector` 与 kNN。
   - RRF retriever。
   - 自定义技术英文分析器，支持驼峰、包名、版本号和错误码。
   - 高亮和来源定位。
4. Qdrant：
   - 1024 维 Dense Vector。
   - Cosine 距离。
   - payload 元数据与 payload index。
   - `must` / `should` 权限与版本过滤。

### 5.5 模型服务

1. Embedding：FastAPI + FlagEmbedding，`BAAI/bge-m3`，仅使用 dense 向量，GPU FP16。
2. Rerank：`bge-reranker-v2-m3`，独立部署或低并发时内嵌。
3. 本地 LLM：vLLM 或 Ollama。
4. 外部 LLM：OpenAI、智谱、通义千问等，必须经过供应商准入和 `LlmGateway`。

### 5.6 可观测性

- Prometheus + Grafana：服务、任务、检索、模型和成本指标。
- Elasticsearch 监控：集群健康、分片、查询延迟和 JVM。
- Qdrant 监控：集合规模、查询延迟、内存和 payload index。
- 应用 Trace：`trace_id` 贯穿 Query Rewrite、召回、融合、重排、生成和反馈。

------

## 6. 核心数据流转流程

### 6.1 文档接入与入库

```text
上传文件 / 同步 GitHub
  -> 身份与知识库权限校验
  -> 创建 document_version 和 ingestion_run
  -> 保存原始文件或源快照到 MinIO
  -> 计算内容指纹并检查重复
  -> 解析、清洗、质量检查
  -> 结构感知分块
  -> 注入权限、版本、来源、页码/行号
  -> 生成 BGE-M3 向量
  -> IndexWriter 写入 staging generation
  -> 校验数量、字段、权限和抽样检索
  -> 切换 active generation
  -> 延迟清理旧 generation
  -> 更新文档和任务状态
```

### 6.2 索引 generation 与一致性

1. 每个文档版本和 chunk 生成稳定标识。
2. 新索引写入独立 staging generation，不直接影响线上检索。
3. 校验 chunk 数、向量数、文档版本、权限字段、过滤字段和抽样查询。
4. 校验通过后原子切换 active generation。
5. 旧 generation 延迟清理，保留回滚窗口。
6. 失败任务从阶段边界或 checkpoint 恢复。
7. 双引擎不使用跨存储分布式事务，也不承诺“同时删除”。

### 6.3 更新、删除与权限变更

1. 文档内容变化创建新 `document_version`，旧版本按保留策略处理。
2. 文档进入 `deleting` 状态后立即从召回过滤中排除。
3. 删除完成记录 `deleted_at` 并进入 `deleted`，在默认 7 天保留窗口内允许恢复。
4. 保留窗口过期后拒绝恢复，并由后台巡检异步清理 ES、Qdrant、MinIO、本地工作副本和可选缓存，成功记录 `purged_at`。
5. 权限撤销先生效于授权服务和索引过滤字段，再异步清理历史版本。
6. 权限变更必须写入 `index_generation` 变更记录和审计日志。
7. 重建或模型切换失败时保留上一个 active generation。

### 6.4 问答流程

```text
用户问题
  -> 身份、团队、知识库和文档状态校验
  -> 读取对话状态
  -> Query Rewrite
  -> 意图、产品、版本、语言和过滤条件识别
  -> BGE-M3 编码检索问题
  -> RetrievalRouter 按 engine_mode 召回
  -> 去重、RRF 融合
  -> Reranker 重排
  -> parent-child 与相邻上下文组装
  -> 数据出境策略与 LlmGateway
  -> 流式生成或拒答
  -> 本地映射引用与来源跳转
  -> 保存 Trace、成本、反馈入口
```

### 6.5 引用、拒答与反馈

1. 引用编号由本地生成，外部模型只看到临时编号。
2. 每个引用包含文档版本、chunk、页码、标题路径或代码行号。
3. 生成后校验引用编号和 chunk 映射，禁止引用未进入上下文的片段。
4. 证据不足、引用无法映射或上下文为空时拒答。
5. 用户反馈进入反馈表，并在聚合后进入知识缺口队列。
6. 业务拒答是受控成功结果：消息状态保存为 `refused`，原因码为
   `INSUFFICIENT_EVIDENCE`，流式连接以 `refused` 终止事件结束，不再发送
   `done` 或 `error`。`error` 只表示策略、模型、流处理等系统失败。

---

## 7. 权限与数据治理

### 7.1 核心实体

- 一个用户可加入多个团队。
- 一个团队可创建多个知识库空间。
- 一个知识库包含多个文档版本和 chunk。
- 文档归属于知识库，可见性为 `private` 或 `team_shared`；敏感程度由 `data_classification` 单独控制。

### 7.2 RBAC 与默认拒绝

1. 所有请求必须携带已认证用户、团队和知识库范围。
2. 默认拒绝，任何过滤条件缺失都返回无权限，不执行“无过滤检索”。
3. `member` 只能查看自己私有文档和有权限的共享文档。
4. `viewer` 可以问答，但不能上传、修改 chunk、删除文档或调整模型策略。
5. `admin` 和 `leader` 默认不能查看成员私有文档正文，只能查看文档是否存在、归属和权限状态。
6. `admin` 或 `leader` 需要查看私有内容时，必须由文档所有者显式授权并记录审计。

### 7.3 成员生命周期

- 成员离职或禁用后，立即撤销查询和写入权限。
- 私有文档支持转移给指定成员、团队知识库或归档。
- 账号删除前必须完成私有文档处理，不能留下不可管理的孤儿资料。
- 团队被移除后，成员不能再访问共享文档和对话。
- GitHub Token、模型 Key 和对象存储凭据按团队隔离并支持轮换。

### 7.4 检索过滤条件

ES 和 Qdrant 必须使用同一组过滤语义：

```text
team_id = 当前团队ID
AND knowledge_base_id IN 授权知识库
AND doc_status = active
AND chunk_status = enabled
AND source_revision IN 当前有效版本
AND (
    visibility = team_shared
    OR owner_user_id = 当前用户ID
    OR 用户被显式授权
)
AND (
    product 为空
    OR product = 当前产品
)
AND (
    version_values 为空
    OR 当前版本命中 version_values
)
```

实际实现中，权限负样本必须进入自动测试，不能只依赖代码评审。

### 7.5 元数据字段

ES 和 Qdrant 至少共享以下字段：

`chunk_id`、`document_id`、`document_version_id`、`team_id`、`knowledge_base_id`、`owner_user_id`、`visibility`、`data_classification`、`source_type`、`source_uri`、`source_revision`、`product`、`version_family`、`version_values`、`valid_from`、`deprecated_at`、`doc_status`、`chunk_status`、`index_generation`、`content_hash`。

需要精确过滤的字段在 ES 中使用 `keyword`，在 Qdrant 中建立 payload index。

### 7.6 文档版本模型

版本不能只使用一个字符串。至少拆分为：

- `product`：产品名。
- `version_family`：版本族，如 JDK 17、JDK 21。
- `version_values[]`：文档适用的多个版本。
- `source_revision`：Git commit、文件路径和分支快照。
- `valid_from`、`deprecated_at`：有效期和废弃时间。

### 7.7 审计

以下操作必须审计：

- 登录、账号禁用和成员变更。
- 文档上传、共享、权限变更、转移和删除。
- chunk 编辑、禁用和重建。
- 模型策略、供应商、API Key 和外部模型开关。
- 索引 generation 创建、激活、回滚和清理。
- 评测集、发布门禁和 Prompt 版本变更。

审计日志默认不保存文档正文和模型请求原文。

---

## 8. LLM 数据出境策略

### 8.1 目标

“私有化部署”不能只表示文件和向量保存在本地。Query Rewrite、Embedding、Rerank 和答案生成都可能把用户问题或文档片段发送给外部服务，因此所有模型调用必须经过统一策略。

- 原始文件、解析文本、chunk、向量和默认检索 Trace 保存在本地。
- 外部调用默认关闭，无法确认策略或脱敏结果时失败关闭。
- `leader` 只能收紧系统级策略，不能突破安全上限。
- 用户只能选择比团队或知识库策略更严格的模型范围。
- 每次调用都能追溯调用者、模型、数据类别、策略版本、脱敏、成本和结果。

### 8.2 数据分类

访问权限回答“谁可以看”，数据分类回答“能否发给外部模型”，两者独立判断。

| 分类 | 典型内容 | 默认策略 |
| --- | --- | --- |
| `public` | 已公开的 JDK、Spring、开源项目文档 | 可按团队策略使用外部模型 |
| `internal` | 团队共享但不公开的设计、部署和研发资料 | 默认仅本地，`leader` 可在团队策略内显式允许 |
| `private` | 成员私有文档、个人笔记 | 默认仅本地，不能被团队级开关自动放开 |
| `restricted` | 密钥、Token、客户数据、生产配置和明确禁止出境的资料 | 禁止进入外部模型 |

分类可由上传者指定、知识库默认值继承或扫描器辅助识别，但不能只依赖自动识别。命中密钥、Token、私钥和连接串时，即使分类较低，也必须阻断或脱敏并审计。

### 8.3 策略层级与运行模式

按部署、团队、知识库、文档和用户请求逐层收敛，采用最严格结果。

| 模式 | 行为 |
| --- | --- |
| `local_only` | Query Rewrite、Embedding、Rerank 和生成只能调用本地模型 |
| `external_allowed` | 满足分类和供应商限制时，可以调用经批准的外部模型 |
| `external_required` | 仅用于明确允许的知识库；外部模型不可用则失败，不静默切换 |

请求涉及多个文档分类时，以候选上下文的最高敏感级别为准。无法使用外部模型时优先切换本地模型；本地模型也不可用时返回 `MODEL_UNAVAILABLE`，不能把模型故障伪装成证据不足拒答，也不能悄悄删除敏感片段后继续生成。

### 8.4 统一模型网关

所有模型调用收敛到 `LlmGateway`，业务模块不得直接持有外部 API Key。

```text
业务请求
  -> AuthContext 与知识库范围
  -> PolicyResolver 计算最终策略
  -> DataClassifier 确认最高数据分类
  -> EgressSanitizer 做字段白名单和敏感信息脱敏
  -> ProviderRouter 选择本地或外部模型
  -> ProviderAdapter 调用模型
  -> ResponseInspector 记录结果、成本和异常
  -> AuditWriter 写入不含原文的调用审计
```

```python
class ModelPolicyDecision:
    allow_external: bool
    allowed_provider_ids: list[str]
    max_data_classification: str
    allowed_model_ids: list[str]
    allow_chat_history: bool
    allow_document_metadata: bool
    require_redaction: bool
    fallback_mode: str
    reason_code: str
    policy_version: str
```

`LlmGateway` 至少覆盖 Query Rewrite、远程 Embedding、远程 Rerank 和答案生成。当前本地 BGE-M3 和 bge-reranker-v2-m3 不产生额外出境；未来切换托管服务时自动继承同一策略。

### 8.5 数据最小化

外部请求只允许：

- 当前问题或经过确认的 `rewritten_query`。
- 最终进入上下文的 TopN chunk。
- 必要的格式指令和输出约束。
- 本次调用内有效的临时引用编号。

默认不允许发送：

- 原始文件、完整文档和未进入上下文的候选。
- 用户名、邮箱、成员列表、`team_id`、ACL。
- 文件服务器路径、MinIO 路径、GitHub Token、数据库连接串和模型 Key。
- 完整历史对话、系统日志、审计日志和其他知识库内容。
- 可还原内部数据结构的真实 `chunk_id` 和文档主键。

外部调用前扫描 API Key、Bearer Token、JWT、私钥、密码、数据库连接串、内部 URL、邮箱和 IP。脱敏失败时返回策略拒绝，不能按原文发送并只记录警告。

### 8.6 供应商与凭据

供应商登记至少包括：

- 名称、API 地址、数据区域、网络出口。
- 模型、上下文长度、价格和限流。
- 是否用于训练、保留周期、零保留能力和删除机制。
- 合同或安全评审状态、审批人和有效期。
- 允许的最大数据分类、是否允许历史对话和是否要求脱敏。
- 健康检查、超时、速率限制和熔断参数。

API Key 只保存在服务端密钥管理系统或加密配置中，禁止返回前端、写入普通日志或模型调用参数。生产环境通过固定出口代理访问供应商域名白名单。

### 8.7 审计、失败与界面

每次调用记录：调用类型、本地/外部路由、供应商、模型、数据区域、策略版本、允许或拒绝原因、数据分类、chunk 数量、字符数、token、内容哈希、脱敏命中类型和数量、对话历史开关、耗时、成本、错误、用户、团队、知识库、`trace_id` 和 `degraded` 状态。

`llm_invocation` 默认不记录请求原文。保存完整 Prompt 做调试必须单独开启短期加密快照，并设置保存期限和访问权限。

失败规则：

- 默认 `local_only`，PoC 完成安全评审前不开放外部模型。
- 策略服务、脱敏器或敏感信息扫描器不可用时失败关闭。
- 外部模型超时、限额或不可用时，只有策略允许才回退本地，并显示“已切换本地模型”。
- 禁用静默回退，所有 model 或 route 变化写入回答元数据和审计。

产品界面：

- 团队设置提供默认本地、允许指定外部模型、禁止外部模型。
- 知识库设置只能收紧，不能放宽团队限制。
- 文档页展示和调整数据分类，`restricted` 默认不能被外部模型使用。
- 问答页显示本地或外部模型以及回退状态。
- `admin` 和 `leader` 查看外部调用趋势、拒绝原因、分类分布、成本和供应商可用性。
- `member` 和 `viewer` 不能查看或修改 API Key 和供应商安全配置。

### 8.8 PoC 验收用例

1. 部署策略为 `local_only` 时，即使配置外部 Key，也不发生外部网络请求。
2. 知识库允许云模型，但上下文包含 `private` 或 `restricted` 时，按策略切换本地；无法回退时返回 `MODEL_UNAVAILABLE`，策略本身不允许时返回 `POLICY_DENIED`。
3. 文档出现 API Key、JWT、私钥或连接串时，外部请求阻断或脱敏，审计无原始值。
4. 外部模型不可用时，不突破知识库策略；允许回退时返回 `degraded=true` 和本地模型标识。
5. 外部调用审计不能用于读取无权限文档正文。
6. Query Rewrite、Embedding、Rerank 和答案生成都无法绕过 `LlmGateway`。
7. `admin` 不能放宽系统级禁止项，`member` 和 `viewer` 不能覆盖团队或知识库策略。
8. 关闭外部模型后，新增调用立即停止。

---

## 9. RAG 检索与生成设计

### 9.1 稳定标识

- `chunk_id` 在同一个 document version 内稳定且唯一。
- `logical_chunk_key` 由文档、源路径和结构路径组成，用于跨版本继承人工修改。
- `content_hash` 判断内容是否变化。
- `index_generation` 标识 chunk 所属的索引版本。
- 所有索引写入使用幂等 upsert，重复任务不产生重复 chunk。

### 9.2 结构感知分块

| 内容类型 | 分块策略 |
| --- | --- |
| Markdown | 按标题层级切分，保留标题路径 |
| 代码 | 按语言、文件、类、函数和代码块边界切分 |
| PDF | 保留页码、章节、表格和 OCR 质量标记 |
| API 文档 | 保留接口名、参数表、示例和适用版本 |
| 通用文本 | 在 token 上限内递归切分，尽量保持句子和段落完整 |

默认使用 parent-child 或 small-to-big：

- 子 chunk 负责精确召回。
- 父 chunk 或相邻 chunk 负责补充上下文。
- 组装时按 token 预算截断，不能把截断片段伪装成完整证据。

### 9.3 多轮 Query Rewrite

每次检索前生成“检索用的独立问题”，保留原始问题用于回答和审计。

需要解决：

- “它、这个、上面说的”等指代。
- 省略产品名、版本和比较对象。
- 中英文混合表达。
- 追问中的时间范围、版本范围和历史约束。

Query Rewrite 通过 `LlmGateway` 调用。若使用外部模型，用户问题也必须经过出境策略和敏感信息扫描。

### 9.4 查询意图与过滤

检索前识别：

- `exact_identifier`：类名、方法名、包名、错误码。
- `concept`：概念解释、方案比较。
- `cross_language`：中文问题检索英文文档。
- `versioned`：产品、版本和文档状态过滤。
- `follow_up`：依赖多轮上下文。
- `insufficient_evidence`：可能需要拒答。

识别结果用于生成过滤条件和融合策略。产品、版本和知识库条件必须在召回阶段执行。

### 9.5 混合检索与 RRF

基础链路：

```text
BM25 Top50
+ Dense Top50
-> RRF k=60
-> Rerank Top50
-> 最终 Top10
-> LLM 使用 Top8
```

第一阶段使用等权 RRF，确认混合检索基础收益。第二阶段再验证查询感知权重：

- 精确标识符提高 BM25 权重。
- 概念解释和方案比较提高 Dense 权重。
- 中英文跨语言可增加翻译后检索支路，同时保留原查询向量支路。
- ES 原生 RRF 和 Qdrant/应用层 RRF 的差异必须在实验中单独记录。

如果 ES 原生 RRF 不支持所需的加权能力，A/B 应使用同一种应用层加权 RRF 再比较，避免把“引擎差异”和“融合算法差异”混在一起。

### 9.6 Rerank 与上下文组装

1. RRF 后最多取 50 个候选进入 Reranker。
2. 使用 `bge-reranker-v2-m3` 对候选统一打分。
3. 按分数、权限和版本过滤后取最终 Top10。
4. 按 token 预算组装 parent-child 和相邻 chunk。
5. 剔除重复内容、已删除版本和无法定位来源的片段。
6. 最终送入 LLM 的 chunk 必须保留 `chunk_id` 和引用映射。

### 9.7 引用、拒答与反馈

回答必须满足：

- 流式展示，支持停止生成。
- 引用可跳转到文档、页码、标题或代码行。
- 引用片段确实出现在最终上下文中。
- 证据不足、引用映射失败或答案超出上下文时拒答。
- 用户可标记“有用、无用、引用错误、知识缺失”。
- 失败问题进入知识缺口队列，并可用于补充黄金集。

拒答与错误分开建模：`refused` 表示系统正常执行了证据门禁，HTTP/SSE 链路没有
发生技术失败；`error` 表示策略拒绝、模型不可用或流处理异常。Trace 列表和详情
通过 `feedback` 数组返回关联到该回答消息的用户反馈，只有聊天所有者、团队
`leader` 或平台 `admin` 可以读取。

### 9.8 检索 Trace

每次问答记录：

- `trace_id`、`engine_mode`、用户、团队和知识库。
- Query Rewrite 前后的文本。
- 完整过滤条件。
- BM25、Dense 候选和排名。
- RRF 排名、Rerank 分数和最终上下文。
- 最终 chunk ID、token 数、模型、供应商和成本。
- 各阶段耗时、错误、降级和反馈。

线上 Trace 和离线评测使用同一结构，保证结论可复现。

---

## 10. 单引擎与双引擎对照验证

### 10.1 验证目标

判断双引擎带来的召回质量、过滤性能或规模收益，是否足以覆盖双写、双备份、双监控和一致性成本。实验不是功能演示，而是离线检索实验。

### 10.2 对照方案

- A：ES BM25 + Qdrant Dense，应用层 RRF，再统一 Rerank。
- B：ES 同时承担 BM25、Dense Vector 和 RRF，再统一 Rerank。
- 基线：BM25-only、Dense-only。

PoC 默认 A，B 作为正式候选实现。MVP 默认值由 ADR 决定。

### 10.3 公平性控制

两套方案固定：

- 相同原始文档、解析结果、chunk 边界和 chunk 标识。
- 相同 BGE-M3 模型、向量归一化方式和向量版本。
- 相同 BM25 分析配置、每路 TopK、RRF 参数、Reranker 和最终 TopN。
- 相同权限、团队、产品、版本和文档状态过滤。
- 相同黄金查询集、相关性标注和评测脚本。
- 相同机器规格、分片和副本；如需不同规格，同时报告单位成本。

### 10.4 查询集分层

黄金集至少覆盖：

- 精确 API、类名、方法名、包名和错误码。
- 自然语言概念解释和方案比较。
- 中文问题检索英文文档。
- 产品、版本和文档状态过滤。
- 多轮 Query Rewrite 后的追问和指代。
- 证据不足、应当拒答的问题。
- 私有文档和权限负样本。

黄金集建议 150 至 300 条，标注到稳定 chunk ID，拆分开发集和测试集。参数调整只使用开发集。

### 10.5 指标

| 维度 | 指标 |
| --- | --- |
| 召回质量 | Recall@20、Recall@50、nDCG@10、MRR |
| 生成依据 | Citation Accuracy、Groundedness、无答案识别准确率 |
| 权限安全 | Permission Leakage，必须为 0 |
| 延迟 | 检索 p50/p95、Rerank 前候选数和耗时、过滤查询 p95 |
| 规模 | 入库吞吐、构建时间、存储、内存和 CPU/GPU 占用 |
| 一致性 | 删除、更新、重建失败率和双写不一致检测结果 |
| 运维 | 服务数量、备份恢复时间、告警数量和故障定位步骤 |

### 10.6 执行步骤

1. 冻结语料、解析结果、chunk、Embedding、查询集和相关性标注。
2. 建立统一检索适配层，复用 Rerank、Prompt、引用和评测链路。
3. 运行 BM25-only 和 Dense-only 基线。
4. 运行 A/B，记录每路候选、RRF、Rerank、过滤和最终上下文。
5. 每个条件重复多轮，报告均值和波动。
6. 压测权限过滤、批量删除、文档更新、模型切换和全量重建。
7. 按解析、分块、召回、融合和重排阶段归因失败。
8. 输出实验报告和 ADR。

### 10.7 判定规则

- 任一方案出现权限泄露，直接不通过。
- 单引擎质量不落后时，优先单引擎。
- 质量差异不超过 2% 时优先单引擎；2% 至 5% 结合规模和运维判断；超过 5% 才进入双引擎保留评估。
- 双引擎必须在关键查询类型上有显著收益，且 p95、资源、备份恢复和一致性风险可接受。
- 阈值是项目决策参数，不是行业标准。

### 10.8 索引与实验空间

```text
techvault-a-es-bm25-<generation>
techvault-a-qdrant-dense-<generation>
techvault-b-es-hybrid-<generation>
```

实验数据使用隔离命名空间，但字段结构与生产 generation 一致。

---

## 11. 存储设计

### 11.1 PostgreSQL 核心表

| 表 | 主要字段与用途 |
| --- | --- |
| `users` | 用户、密码哈希、状态和最后登录时间 |
| `teams` | 团队、创建者、状态和默认策略 |
| `team_member` | 团队成员、角色、加入时间、禁用时间 |
| `knowledge_base` | 知识库、团队、默认数据分类和模型策略 |
| `source_connection` | GitHub 等来源、凭据引用、分支、路径和同步游标 |
| `document` | 文档主记录、知识库、所有者、可见性和当前版本 |
| `document_version` | 内容指纹、来源 revision、产品版本、有效性和解析状态 |
| `chunk` | chunk 内容、结构路径、来源定位、质量标记和启用状态 |
| `chunk_override` | 人工编辑、禁用、重建继承记录和修改人 |
| `ingestion_run` | 批次、阶段、耗时、错误、重试和 checkpoint |
| `document_task` | 单文档异步任务状态和重试次数 |
| `index_generation` | ES/Qdrant generation、模型版本、校验状态和激活时间 |
| `chat` / `message` | 多轮对话、原始问题、Rewrite 结果和模型信息 |
| `retrieval_trace` | 候选、排名、上下文、耗时、降级和 `trace_id` |
| `feedback` | 有用、无用、引用错误和知识缺失 |
| `knowledge_gap` | 聚合同类失败问题、状态和补充文档 |
| `llm_provider` | 供应商、区域、保留策略、安全状态和有效期 |
| `llm_model` | 模型、能力、上下文长度、价格和启用状态 |
| `llm_data_policy` | 部署、团队、知识库和文档级数据出境策略 |
| `llm_invocation` | 模型调用元数据、分类、token、成本和审计 |
| `audit_log` | 登录、权限、文档、chunk、模型和索引变更 |

### 11.2 Elasticsearch 索引

使用逻辑别名 `rag_chunks_active` 指向当前 generation。

每个文档至少包含：

- `chunk_id`、`document_id`、`document_version_id`、`index_generation`。
- 文本字段 `content`。
- `dense_vector`，1024 维，Cosine。
- 过滤字段使用 `keyword`。
- `source_locator` 保存页码、标题路径、代码行号或源 URL。

技术英文分析器至少处理驼峰命名、包名、版本号和错误码。BM25 初始参数 `k1=1.2`、`b=0.6`，最终由黄金集调优。

### 11.3 Qdrant 集合

使用逻辑别名或配置指向当前 collection，向量为 1024 维 Cosine。

以下 payload 字段建立索引：

- `team_id`、`knowledge_base_id`。
- `owner_user_id`、`visibility`、`data_classification`。
- `doc_status`、`chunk_status`、`index_generation`。
- `product`、`version_values`、`source_revision`。

### 11.4 MinIO

存储：

- 原始上传文件。
- GitHub 源快照。
- 可选短期 Prompt 调试快照，必须加密并设置期限。

对象路径不能直接返回给普通前端用户，下载使用带权限校验的短期签名。

### 11.5 Redis

- Celery Broker。
- 短期会话缓存、限流计数和幂等键。
- 不作为文档、向量、chunk 或权限的权威存储。

### 11.6 数据保留与备份

- 原始文件和文档版本按团队策略保留。
- Trace 默认保留 30 至 90 天，原文不写入 Trace。
- 审计日志按合规要求保留，普通调试快照默认关闭。
- PostgreSQL、ES、Qdrant 和 MinIO 均配置备份。
- 至少每季度执行一次恢复演练，记录 RTO、RPO 和失败原因。

---

## 12. API 设计

### 12.1 核心接口

完整接口目录、请求字段、SSE 事件和错误码以 [`docs/api/api-contract.md`](./docs/api/api-contract.md) 与 [`docs/api/openapi.yaml`](./docs/api/openapi.yaml) 为准。接口不使用路径参数；团队 ID、资源 ID 和业务参数放在请求体中，GET 查询接口只使用少量 query 参数。Document 响应禁止返回本地路径、对象存储 URI、bucket 或内部存储键；原文下载必须经过权限校验后的 `/api/v1/docs/download` 或短期签名接口。下表只列出主链路入口。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/login` | 登录 |
| `GET` | `/api/v1/teams` | 团队列表 |
| `POST` | `/api/v1/teams/create` | 创建团队 |
| `GET` | `/api/v1/kbs?team_id=` | 知识库列表 |
| `POST` | `/api/v1/docs/upload` | 上传文件 |
| `POST` | `/api/v1/sources/github/create` | 添加 GitHub 来源 |
| `GET` | `/api/v1/docs/versions?team_id=&document_id=` | 查看文档版本 |
| `GET` | `/api/v1/chunks/detail?team_id=&chunk_id=` | 查看 chunk |
| `POST` | `/api/v1/chunks/update` | 编辑 chunk |
| `POST` | `/api/v1/chunks/disable` | 禁用 chunk |
| `POST` | `/api/v1/chunks/regenerate` | 重新生成 chunk |
| `POST` | `/api/v1/chats/ask` | 问答 |
| `POST` | `/api/v1/messages/feedback` | 用户反馈 |
| `GET` | `/api/v1/traces/detail?team_id=&trace_id=` | 检索调试 Trace |
| `GET` | `/api/v1/model-policy?team_id=` | 模型出境策略 |
| `POST` | `/api/v1/model-policy/update` | 更新模型出境策略 |
| `GET` | `/api/v1/evals/datasets?team_id=` | 黄金集管理 |
| `POST` | `/api/v1/generations/activate` | 激活索引 generation |

### 12.2 问答请求示例

```json
{
  "team_id": "01JTEAM000000000000000001",
  "chat_id": "01JCHAT000000000000000001",
  "question": "Spring Boot 3.2 如何配置虚拟线程？",
  "filters": {
    "knowledge_base_ids": ["kb_001"],
    "product": "spring-boot",
    "version_values": ["3.2"]
  },
  "model_policy": "inherit",
  "stream": true
}
```

### 12.3 流式响应事件

`POST /api/v1/chats/ask` 在 `stream=true` 时返回 `text/event-stream`：

- `meta`：`message_id`、初始 `trace_id`、`engine_mode`、`status=generating`。
  流开始时 `trace_id` 为空，最终值由消息详情和 Trace 接口提供。
- `rewrite`：可选，字段为 `original`、`rewritten`，仅在文本发生变化时发送。
- `citation`：字段为 `citation_id`、`chunk_id`、`document_id`、
  `document_version_id`、`document_name`、`page_no`、`heading_path`、
  `source_url`。
- `delta`：字段为 `text`，可以多次出现。
- `done`：字段为 `message_id`、`status`、`citation_ids`、`model_id`、`route`、
  `policy`、`policy_version`、`classification`、`degraded`、`input_tokens`、
  `output_tokens`、`cost_micros`、`latency_ms`。
- `refused`：终止事件，字段为 `message_id`、`status=refused`、`reason_code`、
  `message`。拒答不是系统错误，发送后不再发送 `done` 或 `error`。
- `error`：终止事件，字段为 `code`、`message`、`retryable`、`request_id`；
  允许的流错误码为 `STREAM_ERROR`、`POLICY_DENIED`、`MODEL_UNAVAILABLE`。

`done`、`refused`、`error` 三者互斥。客户端主动断开时，服务端保存已生成内容
并把消息标记为 `cancelled`，不额外发送终止事件。

入库 SSE 的 `progress`、`completed`、`failed`、`cancelled` 事件共享同一组字段：
`run_id`、`status`、`stage`、`percent`、`error_code`、`retryable`。

### 12.4 错误语义

| 错误码 | 含义 |
| --- | --- |
| `PERMISSION_DENIED` | 无知识库或文档权限 |
| `POLICY_DENIED` | 数据出境策略拒绝 |
| `INDEX_NOT_READY` | 索引 generation 未激活 |
| `MODEL_UNAVAILABLE` | 模型不可用且策略不允许回退 |
| `RETRIEVAL_UNAVAILABLE` | 检索链路不可用 |
| `STREAM_ERROR` | SSE 生成或持久化异常 |
| `PROTECTED_ACCOUNT` | 内置管理员不可停用、删除或降级 |
| `RETENTION_EXPIRED` | 文档已超过恢复窗口 |

`INSUFFICIENT_EVIDENCE` 是 SSE `refused.reason_code`，不是 HTTP 错误码；
`degraded` 是 Trace 和 `done` 事件中的布尔状态，不是错误码。完整 HTTP 错误码、
GitHub 来源错误和 SSE 错误语义以 API 契约第 2 节和第 9 节为准。

---

## 13. 评测与发布门禁

### 13.1 黄金集

1. 首批 150 至 300 条真实技术问题。
2. 按精确标识符、概念问题、跨语言、版本过滤、多轮、无答案和权限负样本分层。
3. 标注稳定 chunk、相关性等级和标准引用。
4. 拆分开发集和测试集，测试集不参与参数调优。
5. 每次线上知识缺口和引用错误可补充为候选样本。

### 13.2 发布门禁

以下条件不满足时不得发布：

- Permission Leakage 必须为 0。
- 删除和权限撤销后不得继续召回。
- Recall@20、nDCG@10、Citation Accuracy 和 Groundedness 不得低于冻结基线。
- 检索 p95 不得超出目标或出现不可解释退化。
- 双引擎或单引擎切换必须有 ADR 和实验报告。
- 索引 generation 必须完成抽样校验和回滚演练。

### 13.3 回归范围

以下变更必须运行回归：

- 解析器、分块规则和 Embedding 模型。
- BM25 分析器、RRF 参数和查询感知权重。
- Reranker、上下文组装和 Prompt。
- 权限字段、过滤语义和索引 mapping。
- 索引 generation、删除和重建流程。

### 13.4 评测产物

每次评测输出：

- 数据集版本、代码版本、模型版本和环境配置。
- 每条查询的候选、排名、引用和失败阶段。
- 分类指标、总体指标、延迟和成本。
- 与基线的差异和显著性说明。
- 结论、限制和后续行动。

---

## 14. 部署与运维

### 14.1 开发与测试环境

Docker Compose 服务：

`nginx`、`frontend`、`backend`、`redis`、`postgres`、`minio`、`elasticsearch`、`qdrant`、`celery-worker`、`flower`、`embedding-service`，Rerank 可按资源情况独立部署或内嵌。

### 14.2 生产环境

1. 可迁移至 K8s，服务独立扩缩容。
2. Embedding 和 Rerank 使用独立 GPU 节点或独立推理服务。
3. ES 从单节点起步，按数据量和查询延迟扩容。
4. Qdrant 根据向量规模、内存和过滤性能规划分片与副本。
5. 所有持久化数据配置卷、备份和恢复验证。
6. 开启 HTTPS、接口鉴权、网络隔离和供应商域名白名单。

### 14.3 监控与告警

至少监控：

- API 错误率、p50/p95 延迟和限流。
- Celery 队列长度、任务失败率、重试和阶段耗时。
- ES 集群健康、查询延迟、分片和 JVM。
- Qdrant 查询延迟、内存和 payload index。
- Embedding、Rerank 和 LLM 的成功率、延迟、token 和成本。
- 外部模型调用量、策略拒绝、脱敏命中和供应商异常。
- 索引 generation 状态、双写不一致和删除积压。

### 14.4 容量规划

PoC 使用真实语料测量：

- 每百万 chunk 的索引存储和内存。
- 入库吞吐和全量重建时间。
- 无过滤、权限过滤和版本过滤的 p95。
- 不同 TopK 和 Rerank 数量下的资源占用。

容量结论进入 ADR，不能只依据小样本演示。

---

## 15. 实施阶段与验收

### 15.1 PoC

目标：证明核心价值和架构差异。

交付：

- 单团队、单知识库或少量知识库。
- 文件上传和一个 GitHub 仓库同步。
- 解析、结构感知分块、Embedding、索引和混合检索。
- 多轮 Query Rewrite、引用、拒答和反馈入口。
- 150 至 300 条黄金集和离线评测。
- ES 单引擎与 ES + Qdrant 双引擎对照报告。

退出条件：

- 权限泄露为 0。
- 检索质量优于 BM25-only 和 Dense-only。
- 引用能定位到原文。
- 证据不足问题能拒答。
- 形成引擎选择 ADR。

### 15.2 MVP

目标：形成团队可持续使用的知识库产品。

交付：

- 团队、角色、知识库和成员生命周期。
- GitHub 增量同步、checkpoint 和索引回滚。
- chunk 预览、编辑、禁用和重建继承。
- LLM 数据出境策略、供应商准入和审计。
- 流式回答、停止生成、引用跳转和知识缺口。
- 监控、告警、备份和恢复演练。

退出条件：

- 发布门禁全部通过。
- 备份恢复和索引回滚演练完成。
- 权限负样本、删除和权限撤销测试完成。
- 外部模型默认关闭，开启时有明确审计。

### 15.3 规模化阶段

已采纳但不作为 MVP 前置条件：

1. Confluence、Notion、Slack、Google Drive、SharePoint 连接器。
2. 源系统 ACL 同步。
3. 索引 generation 与 Embedding 模型切换自动化。
4. BGE-M3 sparse、ColBERT 和 Agentic Retrieval 的收益验证。
5. 知识图谱、摘要、Wiki 和时间线。
6. 跨区域和高可用部署。

---

## 16. 项目风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 只验证回答，不验证检索 | 答案流畅但不可信 | 黄金集、Recall、Citation Accuracy、拒答率 |
| 双索引不一致 | 删除后仍召回、引用失效 | generation、幂等、软删除、校验和巡检 |
| 权限漏洞 | 私有文档泄露 | 召回阶段过滤、默认拒绝、负样本测试和审计 |
| 解析质量差 | 召回错误片段 | chunk 预览、OCR、结构感知切分和人工干预 |
| 多轮丢失上下文 | 追问答非所问 | Query Rewrite、实体和版本继承 |
| 云模型泄露内容 | 违反团队数据要求 | 默认本地、统一网关、脱敏、供应商准入和审计 |
| 查询感知权重过拟合 | 开发集提升、测试集退化 | 开发/测试集分离和按查询类型统计 |
| 组件过多难运维 | 故障定位和扩容成本高 | A/B 实验、ADR、统一 Trace 和降级策略 |
| 缺少反馈闭环 | 知识库越来越旧 | 知识缺口、过期策略、定期重建和回归 |
| 人工修改 chunk 丢失 | 重建覆盖运营成果 | `chunk_override` 和 `logical_chunk_key` |

---

## 17. 附录：术语说明

1. **RAG**：检索增强生成，用知识库片段作为上下文指导模型回答。
2. **BM25**：基于倒排索引的关键词检索算法，适合类名、API、术语和版本号。
3. **Dense Retrieval**：使用向量相似度进行语义召回。
4. **Embedding**：将文本转换为向量。
5. **RRF**：Reciprocal Rank Fusion，基于排名的多路召回融合。
6. **Rerank**：对召回候选进行二次精细排序。
7. **Chunk**：文档切分后的检索单元。
8. **Parent-child**：小块召回，大块提供上下文。
9. **Generation**：一次完整、可校验、可切换和可回滚的索引版本。
10. **ADR**：Architecture Decision Record，记录架构决策、证据、取舍和重新评估条件。
11. **BGE-M3**：BAAI 多语言 Embedding 模型，本项目使用 1024 维 dense 向量。
12. **bge-reranker-v2-m3**：同源重排模型。
13. **LlmGateway**：统一模型调用网关，负责策略、脱敏、路由、成本和审计。
14. **Permission Leakage**：用户检索到本无权访问的文档或片段。
