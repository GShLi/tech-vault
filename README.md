# TechVault 典阁

面向研发团队的私有技术知识库与 RAG 问答系统。它支持文件与 GitHub 文档接入、团队共享与私有资料隔离、结构感知分块、混合检索、重排、带引用回答、拒答和检索链路追踪。

项目以“权限在召回阶段生效、默认数据不出域、所有检索变更可评测”为基本约束。当前仓库是 PoC 工程骨架，已经包含可测试的领域契约和基础模块；Elasticsearch、Qdrant、FastAPI 路由、Celery Worker、前端页面和模型服务将在后续迭代逐步接入。

完整设计见 [项目设计文档](<./TechVault 典阁 — 团队私有技术知识库 RAG 系统.md>)。

## 核心能力

- 文件上传和 GitHub 仓库文档接入
- 团队、知识库、文档、chunk 的分层权限
- Markdown、代码、PDF 和 API 文档的结构感知分块
- BM25 与 Dense Retrieval 混合召回、RRF 融合和 Rerank
- 多轮 Query Rewrite、版本过滤、引用定位和证据不足拒答
- `dual_engine` 与 `elastic_single` 两种检索模式
- 索引 generation、staging 校验、原子切换、回滚和软删除
- 本地模型优先的 LLM 数据出境策略
- 黄金集、Recall、MRR、nDCG 和全链路检索 Trace

## 系统架构

```text
Vue3 前端
    |
Nginx / FastAPI
    |
业务模块 ────────────── RAG 核心
    |                     |
    |                     ├─ 解析 / 分块 / Embedding
    |                     ├─ Retriever / RRF / Rerank
    |                     ├─ 上下文组装 / 引用 / 拒答
    |                     └─ Trace / 评测
    |
Celery Worker
    |
PostgreSQL   MinIO   Elasticsearch   Qdrant   Redis
                         |
               BGE-M3 / bge-reranker-v2-m3 / LLM
```

## 仓库结构

```text
tech-vault/
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI 路由和应用入口
│   │   │   └── v1/
│   │   ├── core/                 # 配置、认证、授权、模型策略
│   │   ├── db/                   # ORM、仓储和迁移
│   │   ├── modules/              # 业务模块
│   │   │   ├── identity/
│   │   │   ├── teams/
│   │   │   ├── knowledge_bases/
│   │   │   ├── documents/
│   │   │   ├── sources/
│   │   │   ├── ingestion/
│   │   │   ├── chunks/
│   │   │   ├── chats/
│   │   │   ├── feedback/
│   │   │   ├── evaluations/
│   │   │   ├── model_policies/
│   │   │   └── audit/
│   │   ├── rag/                  # RAG 核心接口与适配器
│   │   │   ├── domain/
│   │   │   ├── chunking/
│   │   │   ├── ingestion/
│   │   │   ├── fusion/
│   │   │   ├── indexing/
│   │   │   ├── retrieval/
│   │   │   ├── parsing/
│   │   │   ├── embedding/
│   │   │   ├── rerank/
│   │   │   ├── context/
│   │   │   ├── answer/
│   │   │   ├── llm_gateway/
│   │   │   ├── evaluation/
│   │   │   └── observability/
│   │   └── workers/              # Celery 任务
│   └── tests/                    # 单元和集成测试
├── frontend/                     # Vue3 应用，页面骨架待接入
├── deploy/                       # Docker Compose、Nginx、K8s
├── docs/                         # ADR、API 和工程文档
├── scripts/                      # 初始化、导入和评测脚本
├── pyproject.toml
└── README.md
```

## 当前实现状态

第一个垂直切片已建立并可测试：

- FastAPI 应用工厂，以及健康检查、就绪检查和版本接口
- 注册、登录和当前用户认证 API
- 团队与知识库 API
- SQLAlchemy 核心持久化
- 共享 RAG 领域对象和 `Retriever` / `IndexWriter` 端口
- 默认拒绝的文档授权和检索过滤
- LLM 数据出境策略的基本约束
- Markdown 结构分块与稳定 chunk 标识
- 加权 RRF
- Recall、MRR、nDCG 评测指标
- 黄金集加载和种子样本
- 内存索引 generation 和内存检索适配器

第一个垂直切片尚未接入：

- Elasticsearch 和 Qdrant 生产检索适配器；当前仅支持内存检索
- 文档上传与来源同步 API
- Chunk 管理 API
- 对话、Trace 和评测 API
- 生产数据库迁移
- PDF、DOCX、GitHub 解析链路
- MinIO、Redis 和 Celery Worker
- BGE-M3、bge-reranker-v2-m3 和真实 LLM
- Vue3 管理界面和问答界面
- 生产级鉴权、审计、监控和备份

## 本地开发

目标运行时是 Python 3.10+。当前基础模块保持 Python 3.9 兼容，便于在当前工作环境运行测试。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools
python -m pip install -e ".[test]"
pytest -q
```

当前基线测试：

```text
165 passed
```

### 启动 API

```bash
python -m pip install -e ".[test,api]"
uvicorn backend.app.main:create_app --factory --reload
```

默认地址为 `http://127.0.0.1:8000/api/v1`，交互文档为
`http://127.0.0.1:8000/docs`。当前 API 已覆盖健康检查、注册登录、
当前用户、团队和知识库；文档上传、检索问答、Celery 和前端仍待接入。

测试数据库使用独立的 SQLite 内存库；本地开发默认使用
`data/techvault.db`，可通过 `TECHVAULT_DATABASE_URL` 覆盖。

只验证第一个 RAG 垂直切片：

```bash
pytest backend/tests/smoke/test_vertical_slice.py -q
```

该烟雾测试覆盖 Markdown 分块、权限过滤、内存混合检索、RRF 排序和评测指标，并校验请求结果中的非空 `trace_id`。

后续安装 API 依赖时使用：

```bash
python -m pip install -e ".[test,api,tasks]"
```

## 开发约定

- 业务模块通过应用服务调用 RAG 领域接口，不直接依赖 ES、Qdrant 或模型 SDK。
- 权限过滤必须在召回前执行，不能先召回再在应用层删除。
- `dual_engine` 和 `elastic_single` 通过配置切换，共用 Rerank、上下文、引用和评测代码。
- 任何外部模型调用都必须经过 `llm_gateway`，默认策略为 `local_only`。
- 索引写入使用 staging generation，校验和激活后才能被检索。
- 每次问答 Trace 与离线评测共享同一候选和上下文结构。

## 进一步文档

- [P0 垂直切片实施计划](./docs/superpowers/plans/2026-10-18-techvault-p0-vertical-slice.md)
- [前端页面与路由清单](./docs/product/page-map.md)
- [API 契约](./docs/api/api-contract.md)
- [OpenAPI 骨架](./docs/api/openapi.yaml)
- [ADR 目录](./docs/adr/README.md)
- [API 文档目录](./docs/api/README.md)
- [部署说明](./deploy/README.md)
- [脚本说明](./scripts/README.md)

## Git 远程

```text
origin  git@github.com:GShLi/tech-vault.git
```

