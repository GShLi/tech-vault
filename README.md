# TechVault 典阁

面向研发团队的私有技术知识库与 RAG 问答系统。P0 已形成可运行的前后端垂直切片：管理员开户、团队与知识库、文件和 GitHub 文档接入、异步入库、Chunk 管理、混合检索、Rerank、带引用问答、检索 Trace、评测、模型策略和审计。

完整产品与架构设计见 [项目设计文档](<./TechVault 典阁 — 团队私有技术知识库 RAG 系统.md>)，接口基线见 [API 契约](./docs/api/api-contract.md) 和 [OpenAPI](./docs/api/openapi.yaml)。

## 核心能力

- 内置超级管理员，禁止外部注册；用户和团队只能由管理员创建。
- 平台角色为 `admin`，团队成员角色为 `leader | member | viewer`，无租户字段。
- 文件上传与 GitHub 来源同步，原始文件进入 MinIO。
- 文档、版本、Chunk、知识库成员范围和私有文档授权。
- Markdown、TXT、PDF、DOCX 的解析、结构感知分块和索引 generation。
- `dual_engine`（ES + Qdrant + RRF）与 `elastic_single`（ES 混合检索）两种后端检索模式。
- Query Rewrite、Rerank、证据不足拒答、引用定位和可追踪降级状态。
- SSE 问答与任务进度，支持取消、超时和终端状态持久化。
- Trace、黄金集、Recall/MRR/nDCG、模型数据策略和全链路审计。
- 文档软删除保留窗口；过期后由 Celery Beat 巡检清理索引、MinIO、本地文件和缓存。

## 系统架构

```text
Vue 3 + Vite
      |
FastAPI  /api/v1
      |
业务模块 ───────────── RAG 核心
      |                  | 解析 / 分块 / Embedding
      |                  | Retrieval / RRF / Rerank
      |                  | 上下文 / 引用 / 拒答 / Trace
      |
Celery Worker + Beat
      |
PostgreSQL   MinIO   Elasticsearch   Qdrant   Redis
```

开发时自有代码直接运行本地进程，Docker 只承载 PostgreSQL、Redis、MinIO、Elasticsearch 和 Qdrant，便于热更新与调试。

## 仓库结构

```text
tech-vault/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI 路由
│   │   ├── core/            # 配置、认证、授权、密钥和模型策略
│   │   ├── db/              # SQLAlchemy 模型与 PoC schema bridge
│   │   ├── modules/         # 文档、团队、来源、审计、模型策略等业务模块
│   │   ├── rag/             # 解析、分块、索引、检索、重排、生成与评测
│   │   └── workers/         # Celery 任务和 inline/Celery 统一调度
│   └── tests/
├── frontend/                # Vue 3 工作台
├── deploy/                  # 本地依赖 Compose 与容器化部署模板
├── docs/                    # API、页面、ADR 与实施文档
├── scripts/                 # 真实依赖验证脚本
└── pyproject.toml
```

## 本地启动

### 1. 启动依赖服务

```bash
cd deploy
docker compose up -d
```

本地端口：

| 服务 | 地址 |
| --- | --- |
| PostgreSQL | `127.0.0.1:55433` |
| Redis | `127.0.0.1:56379` |
| Elasticsearch | `http://127.0.0.1:59200` |
| Qdrant | `http://127.0.0.1:56333` |
| MinIO API | `http://127.0.0.1:59000` |
| MinIO Console | `http://127.0.0.1:59001` |

### 2. 启动后端

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,api,tasks]"

export TECHVAULT_ENVIRONMENT=development
export TECHVAULT_DATABASE_URL="postgresql+psycopg2://techvault:techvault@127.0.0.1:55433/techvault"
export TECHVAULT_REDIS_URL="redis://127.0.0.1:56379/0"
export TECHVAULT_ES_URL="http://127.0.0.1:59200"
export TECHVAULT_QDRANT_URL="http://127.0.0.1:56333"
export TECHVAULT_MINIO_URL="http://127.0.0.1:59000"
export TECHVAULT_MINIO_PUBLIC_URL="http://127.0.0.1:59000"
export TECHVAULT_MINIO_ACCESS_KEY=minioadmin
export TECHVAULT_MINIO_SECRET_KEY=minioadmin
export TECHVAULT_MINIO_BUCKET=techvault
export TECHVAULT_UPLOAD_DIR="$PWD/data/uploads"
export TECHVAULT_OBJECT_STORAGE_ENABLED=true
export TECHVAULT_ENABLE_INDEXING=true
export TECHVAULT_TASK_EXECUTION_MODE=inline

.venv/bin/uvicorn backend.app.main:create_app --factory --reload --port 8000
```

`TECHVAULT_TASK_EXECUTION_MODE` 支持 `inline` 和 `celery`：

- `inline`：本地单进程同步执行，便于测试和单模块调试。
- `celery`：API 只入队，由独立 Worker 执行；生产形态使用该模式。

使用 Celery 时另开两个进程：

```bash
.venv/bin/celery -A backend.app.workers.tasks worker --loglevel=info
.venv/bin/celery -A backend.app.workers.tasks beat --loglevel=info
```

`beat` 每小时触发过期文档物理清理。

### 3. 启动前端

```bash
cd frontend
export PATH="$HOME/.nvm/versions/node/v22.15.0/bin:$PATH"
npm install
VITE_DEV_API_TARGET=http://127.0.0.1:8000 npm run dev
```

打开 `http://127.0.0.1:5173/login`。API 文档在 `http://127.0.0.1:8000/docs`。

## 初始管理员

首次启动会创建内置超级管理员：

```text
邮箱：admin@techvault.local
密码：ChangeMe-123!
```

首次登录后请立即修改密码。内置管理员不能被删除、停用或降级，但允许修改自己的密码。可通过 `TECHVAULT_ADMIN_EMAIL`、`TECHVAULT_ADMIN_PASSWORD` 和 `TECHVAULT_ADMIN_DISPLAY_NAME` 覆盖初始值。

## 验证

后端：

```bash
.venv/bin/pytest -q
.venv/bin/python -m compileall -q backend/app backend/tests
```

前端：

```bash
cd frontend
export PATH="$HOME/.nvm/versions/node/v22.15.0/bin:$PATH"
npm test
npm run build
```

真实依赖验证：

```bash
.venv/bin/python scripts/verify_retrieval_stack.py
.venv/bin/python scripts/verify_object_storage.py
.venv/bin/python scripts/verify_rag_e2e.py
```

- `verify_retrieval_stack.py` 校验 ES/Qdrant staging、激活、双引擎和 ES 单引擎对照。
- `verify_object_storage.py` 校验 MinIO 上传、下载、删除和删除后不可下载。
- `verify_rag_e2e.py` 校验上传、入库、检索、生成和引用链路。

前后端联调脚本：

```bash
cd frontend
VITE_DEV_API_TARGET=http://127.0.0.1:8001 npm run integration
```

## 开发约定

- 项目文档和 OpenAPI 是接口事实来源；实现与文档冲突时先修文档或代码，禁止长期双口径。
- API 路径不包含团队或资源路径参数；写操作参数放 JSON body，查询接口只使用有限 query 参数。
- 权限过滤必须进入召回条件；禁止先召回再在应用层剔除无权内容。
- 外部模型调用统一经过 `llm_gateway`，默认 `local_only`。
- 索引写入使用 staging generation，通过校验后激活；失败保留上一个 active generation。
- 文档删除先停止召回，保留期内可恢复，过期后由后台任务幂等清理。
- 任何秘密值只写不读，日志、Trace 和审计不得记录完整密钥或原始文档内容。

## 文档索引

- [项目设计与产品需求](<./TechVault 典阁 — 团队私有技术知识库 RAG 系统.md>)
- [前端页面与路由](./docs/product/page-map.md)
- [API 契约](./docs/api/api-contract.md)
- [OpenAPI](./docs/api/openapi.yaml)
- [部署说明](./deploy/README.md)
- [脚本说明](./scripts/README.md)
- [ADR 目录](./docs/adr/README.md)

## Git 远程

```text
origin  git@github.com:GShLi/tech-vault.git
```
