# TechVault 前端页面与路由清单

本文档定义 P0 前端页面、路由、主要组件和依赖 API。P2 页面单独标记，不进入当前开发排期。

## 1. 全局约定

### 1.1 路由前缀

除公开页面外，所有业务页面统一使用：

```text
/teams/:teamId/...
```

`teamId` 是当前团队上下文，不得从 URL 参数之外隐式切换团队。前端切换团队时必须重新加载团队成员权限和知识库范围。

前端路由参数使用 `:teamId`、`:documentId` 形式；后端 API 路径参数统一使用 `{team_id}`、`{document_id}`。两者表达同一含义，但不要在前端代码中混用。

### 1.2 角色

| 角色 | 标识 | 权限摘要 |
| --- | --- | --- |
| `admin` | `admin` | 供应商、全局模型策略、系统健康 |
| `leader` | `leader` | 团队、成员、知识库、审计、评测、模型策略 |
| 普通成员 | `member` | 上传文档、添加来源、管理自己的私有文档、问答 |
| 只读成员 | `viewer` | 查看有权限文档、问答、查看引用，不可修改资料 |

管理员默认不能查看成员私有文档正文。

### 1.3 页面状态

所有页面必须实现以下状态：

- `loading`：骨架屏或局部加载。
- `empty`：无数据及引导动作。
- `error`：可重试错误和 `request_id`。
- `forbidden`：无权限说明，不泄露资源是否存在。
- `conflict`：并发编辑冲突，提示刷新后重试。
- `degraded`：检索或模型降级状态。

### 1.4 前端数据约定

- API 字段使用 `snake_case`，前端不自行转换字段名。
- ID 统一为 ULID 字符串，前端不得解析其结构。
- 时间统一为 UTC ISO 8601，例如 `2026-10-18T12:00:00Z`，展示时转本地时区。
- 列表统一使用游标分页，不在前端做全量拉取。
- 可编辑资源使用 `version` 做乐观锁；提交时发送 `If-Match`。

## 2. 公开页面

| 页面 | 路由 | 主要组件 | 依赖 API |
| --- | --- | --- | --- |
| 登录 | `/login` | 账号密码表单、登录状态 | `POST /auth/login` |
| 注册 | `/register` | 注册表单、密码规则 | `POST /auth/register` |
| 接受邀请 | `/invite/:token` | 邀请信息、加入团队 | `GET /invitations/:token`、`POST /invitations/:token/accept` |
| 找回密码 | `/forgot-password` | 邮箱表单 | `POST /auth/password/forgot`（P1） |

## 3. 主工作区

### 3.1 问答工作台

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/chat`、`/teams/:teamId/chat/:conversationId` |
| 主要用户 | 所有已认证成员 |
| 页面目标 | 选择知识库范围，提问，流式查看答案、引用、拒答和模型状态 |
| 主要组件 | 知识库筛选器、产品/版本筛选器、会话列表、消息流、引用面板、模型状态、反馈按钮 |
| 依赖 API | `GET /teams/{teamId}/knowledge-bases`、`GET /teams/{teamId}/retrieval-facets`、`GET/POST /teams/{teamId}/conversations`、`GET /teams/{teamId}/conversations/{conversationId}/messages`、`POST /teams/{teamId}/conversations/{conversationId}/ask`、`POST /teams/{teamId}/messages/{messageId}/feedback`、`GET /teams/{teamId}/messages/{messageId}/citations` |

页面状态：

- 没有知识库时引导创建或等待管理员配置。
- 无检索结果时显示“知识库中没有足够依据”，不显示伪造答案。
- 外部模型被策略拒绝时显示 `POLICY_DENIED` 或本地模型回退状态。
- 流式响应支持停止生成和重新生成。

### 3.2 会话历史

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/conversations` |
| 页面目标 | 查看、重命名、删除和继续历史会话 |
| 主要组件 | 会话列表、时间范围筛选、知识库筛选、删除确认 |
| 依赖 API | `GET /teams/{teamId}/conversations`、`PATCH /teams/{teamId}/conversations/{conversationId}`、`DELETE /teams/{teamId}/conversations/{conversationId}` |

## 4. 知识库与文档

### 4.1 知识库列表

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-bases` |
| 页面目标 | 查看知识库、成员范围、文档数量和默认策略 |
| 主要组件 | 知识库卡片/表格、搜索、创建入口、状态标签 |
| 依赖 API | `GET /teams/{teamId}/knowledge-bases`、`POST /teams/{teamId}/knowledge-bases` |

### 4.2 知识库详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-bases/:kbId` |
| 页面目标 | 管理文档、来源、模型策略和索引状态 |
| 主要组件 | 文档列表、上传入口、GitHub 来源、任务状态、知识库策略摘要 |
| 依赖 API | `GET /teams/{teamId}/knowledge-bases/{kbId}`、`GET /teams/{teamId}/knowledge-bases/{kbId}/documents`、`GET /teams/{teamId}/knowledge-bases/{kbId}/sources`、`GET /teams/{teamId}/ingestion-runs` |

### 4.3 文件上传

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-bases/:kbId/upload` |
| 页面目标 | 上传 PDF、Markdown、TXT、DOCX 并设置元数据和可见性 |
| 主要组件 | 拖拽上传、文件列表、产品/版本、可见性、数据分类、提交按钮 |
| 依赖 API | `POST /teams/{teamId}/knowledge-bases/{kbId}/documents/upload` |

### 4.4 GitHub 来源

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-bases/:kbId/sources/github` |
| 页面目标 | 添加仓库、分支、路径白名单和同步策略 |
| 主要组件 | 仓库 URL、分支、路径规则、扩展名、凭据选择、同步频率 |
| 依赖 API | `POST /teams/{teamId}/knowledge-bases/{kbId}/sources/github`、`GET /teams/{teamId}/credentials` |

### 4.5 文档详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/documents/:documentId` |
| 页面目标 | 查看文档元数据、版本、解析状态、权限和下载入口 |
| 主要组件 | 元数据面板、版本时间线、来源链接、权限设置、重建按钮 |
| 依赖 API | `GET /teams/{teamId}/documents/{documentId}`、`GET /teams/{teamId}/documents/{documentId}/versions`、`PATCH /teams/{teamId}/documents/{documentId}`、`GET /teams/{teamId}/documents/{documentId}/download-url` |

### 4.6 文档版本

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/documents/:documentId/versions/:versionId` |
| 页面目标 | 查看版本内容、解析质量、索引 generation 和 chunk 列表 |
| 主要组件 | 原文预览、版本切换、质量标记、chunk 入口 |
| 依赖 API | `GET /teams/{teamId}/documents/{documentId}/versions/{versionId}`、`GET /teams/{teamId}/documents/{documentId}/chunks` |

### 4.7 知识库策略

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-bases/:kbId/settings` |
| 页面目标 | 在团队策略上限内收紧知识库模型策略和默认数据分类 |
| 主要组件 | 数据分类默认值、模型策略、供应商范围、策略继承说明 |
| 依赖 API | `GET/PATCH /teams/{teamId}/knowledge-bases/{kbId}/policy` |

## 5. 任务与内容治理

### 5.1 任务中心

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/tasks`、`/teams/:teamId/tasks/:runId` |
| 页面目标 | 查看入库、同步、重建和评测任务 |
| 主要组件 | 任务表格、阶段进度、失败原因、重试、取消、事件流 |
| 依赖 API | `GET /teams/{teamId}/ingestion-runs`、`GET /teams/{teamId}/ingestion-runs/{runId}`、`GET /teams/{teamId}/ingestion-runs/{runId}/events`、`POST /teams/{teamId}/ingestion-runs/{runId}/retry`、`POST /teams/{teamId}/ingestion-runs/{runId}/cancel` |

### 5.2 Chunk 管理

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/chunks`、`/teams/:teamId/chunks/:chunkId` |
| 页面目标 | 检查分块质量，编辑、禁用、启用和重新生成 |
| 主要组件 | chunk 表格、原文定位、质量标记、编辑器、历史版本 |
| 依赖 API | `GET /teams/{teamId}/chunks`、`GET /teams/{teamId}/chunks/{chunkId}`、`PATCH /teams/{teamId}/chunks/{chunkId}`、`POST /teams/{teamId}/chunks/{chunkId}/disable`、`POST /teams/{teamId}/chunks/{chunkId}/enable`、`POST /teams/{teamId}/chunks/{chunkId}/regenerate`、`GET /teams/{teamId}/chunks/{chunkId}/history` |

### 5.3 检索调试台

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/traces`、`/teams/:teamId/traces/:traceId` |
| 主要用户 | `leader`、研发 |
| 页面目标 | 查看 Query Rewrite、过滤条件、候选、RRF、Rerank、最终上下文和模型信息 |
| 主要组件 | Trace 列表、阶段时间线、候选表格、引用映射、降级标记 |
| 依赖 API | `GET /teams/{teamId}/traces`、`GET /teams/{teamId}/traces/{traceId}` |

### 5.4 知识缺口

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/knowledge-gaps` |
| 页面目标 | 聚合无答案、引用错误和高频失败问题 |
| 主要组件 | 问题聚类、来源、状态、转评测样本 |
| 依赖 API | `GET /teams/{teamId}/knowledge-gaps`、`PATCH /teams/{teamId}/knowledge-gaps/{gapId}`、`POST /teams/{teamId}/knowledge-gaps/{gapId}/promote` |

## 6. 评测

### 6.1 黄金集列表

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/evaluations` |
| 页面目标 | 管理开发集、测试集和版本 |
| 主要组件 | 数据集列表、版本、样本数量、最近一次运行 |
| 依赖 API | `GET /teams/{teamId}/evaluation-datasets`、`POST /teams/{teamId}/evaluation-datasets` |

### 6.2 黄金集详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/evaluations/:datasetId` |
| 页面目标 | 管理查询、相关性标注和样本分层 |
| 主要组件 | 样本表格、导入导出、类型筛选、标注编辑器 |
| 依赖 API | `GET/POST /teams/{teamId}/evaluation-datasets/{datasetId}/cases`、`PATCH /teams/{teamId}/evaluation-datasets/{datasetId}/cases/{caseId}`、`POST /teams/{teamId}/evaluation-datasets/{datasetId}/import` |

### 6.3 评测运行与报告

| 项目 | 内容 |
| --- | --- |
| 路由 | `/teams/:teamId/evaluations/runs/:runId` |
| 页面目标 | 查看运行进度、分类指标、失败样本和 A/B 对比 |
| 主要组件 | 进度条、指标卡、查询类型分布、失败归因、导出报告 |
| 依赖 API | `GET /teams/{teamId}/evaluation-runs/{runId}`、`GET /teams/{teamId}/evaluation-runs/{runId}/report`、`GET /teams/{teamId}/evaluation-runs/{runId}/events` |

## 7. 模型策略与团队设置

### 7.1 团队设置

| 页面 | 路由 | 依赖 API |
| --- | --- | --- |
| 团队资料 | `/teams/:teamId/settings/team` | `GET/PATCH /teams/{teamId}` |
| 成员管理 | `/teams/:teamId/settings/members` | `GET/POST /teams/{teamId}/invitations`、`PATCH /teams/{teamId}/members/{userId}`、`DELETE /teams/{teamId}/members/{userId}` |
| 模型策略 | `/teams/:teamId/settings/model-policy` | `GET/PATCH /teams/{teamId}/model-policy` |
| 供应商 | `/teams/:teamId/settings/providers` | `GET /teams/{teamId}/model-providers`、`POST /teams/{teamId}/model-providers`、`POST /teams/{teamId}/model-providers/{providerId}/test` |
| 审计日志 | `/teams/:teamId/settings/audit` | `GET /teams/{teamId}/audit-logs` |
| 索引管理 | `/teams/:teamId/settings/index-generations` | `GET /teams/{teamId}/index-generations`、`POST /teams/{teamId}/index-generations/{generationId}/activate`、`POST /teams/{teamId}/index-generations/{generationId}/rollback` |

### 7.2 平台设置

| 页面 | 路由 | 依赖 API |
| --- | --- | --- |
| 全局模型策略 | `/admin/model-policy` | `GET/PATCH /admin/deployment-model-policy` |
| 供应商准入 | `/admin/model-providers` | `GET/POST/PATCH /admin/model-providers` |
| 系统状态 | `/admin/system` | `GET /health`、`GET /ready`、`GET /version` |

## 8. 页面与 API 优先级

| 优先级 | 页面 |
| --- | --- |
| P0 | 登录/注册、问答工作台、会话历史、知识库列表/详情/策略、文件上传、GitHub 来源、文档版本、任务中心、Chunk 管理、检索调试、评测列表/详情/报告、团队成员、模型策略、平台设置、审计、索引管理 |
| P1 | 知识缺口、Trace 回放、评测 A/B 对比、供应商测试、找回密码 |
| P2 | Confluence/Notion/Slack/Drive 等连接器、源系统 ACL、知识图谱、Agentic Retrieval、多租户管理 |

## 9. 前端并行开发约定

- 页面组件只调用 `docs/api/openapi.yaml` 中定义的接口。
- 未完成的后端接口使用 OpenAPI 示例或 MSW mock，不自行定义字段。
- 任何接口字段变更必须先改 OpenAPI，再同步前端类型和后端实现。
- 列表页面必须支持游标分页和错误重试。
- 所有写操作显示 `request_id`，便于联调时定位日志。
- SSE 流式问答不得使用轮询替代，除不支持 SSE 的环境外不提供降级实现。

