# TechVault 前端页面与路由清单

本文档定义 P0 前端页面、路由、主要组件和依赖 API。P2 页面单独标记，不进入当前开发排期。

## 1. 全局约定

### 1.1 路由与团队上下文

页面路由不包含团队 ID：

```text
/chat
/knowledge-bases
/documents/:documentId
```

当前团队由顶部团队选择器和前端状态维护：

- 登录后调用 `GET /auth/me` 获取团队列表。
- 只有一个团队时自动选中；多个团队时恢复最近使用的团队，否则展示团队选择器。
- 切换团队时清理旧团队查询缓存，并重新加载知识库和权限。
- 查询 API 使用 `team_id` query 参数；写操作在 JSON body 中传 `team_id`。
- 资源 ID 可以保留在前端路由中，但不会出现在后端 API 路径中。
- 直接打开深链接而当前没有团队上下文时，先展示团队选择器，再加载资源。

### 1.2 角色

| 角色 | 标识 | 权限摘要 |
| --- | --- | --- |
| 平台管理员 | `admin` | 供应商、全局模型策略、系统健康 |
| 团队管理员 | `leader` | 团队资料、成员、知识库、审计、评测、模型策略 |
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
- 契约提供 `limit`/`cursor` 的资源列表统一使用游标分页；`facets` 等派生聚合
  对象和详情内嵌数组按接口文档处理，不假定其具备独立翻页能力。
- 可编辑资源使用 `version` 做乐观锁；提交时发送 `If-Match`。

## 2. 公开页面

| 页面 | 路由 | 主要组件 | 依赖 API |
| --- | --- | --- | --- |
| 登录 | `/login` | 账号密码表单、登录状态 | `POST /auth/login` |
| 账号开通 | - | 由平台管理员在用户管理中创建，不提供外部注册入口 | `POST /admin/users/create` |
| 接受邀请 | `/invite/:token` | 邀请信息、加入团队 | `GET /invitations/detail?token=`、`POST /invitations/accept` |
| 找回密码 | `/forgot-password` | 邮箱表单 | `POST /auth/password/forgot`（P1） |

## 3. 主工作区

### 3.1 问答工作台

| 项目 | 内容 |
| --- | --- |
| 路由 | `/chat`、`/chat/:chatId` |
| 主要用户 | 所有已认证成员 |
| 页面目标 | 选择知识库范围，提问，流式查看答案、引用、拒答和模型状态 |
| 主要组件 | 知识库筛选器、产品/版本筛选器、会话列表、消息流、引用面板、模型状态、反馈按钮 |
| 依赖 API | `GET /kbs?team_id=`、`GET /facets?team_id=`、`GET /chats?team_id=`、`POST /chats/create`、`GET /chats/messages?team_id=&chat_id=`、`POST /chats/ask`、`POST /messages/feedback`、`GET /messages/citations?team_id=&message_id=` |

页面状态：

- 没有知识库时引导创建或等待管理员配置。
- 发送按钮在供应商、模型、知识库和问题均已选择前保持禁用并显示为灰色；供应商和模型选项来自当前团队策略允许的可用供应商及其 `model_ids`。
- 无检索结果时显示“知识库中没有足够依据”，不显示伪造答案。服务端以
  `refused` 终止事件和 `reason_code=INSUFFICIENT_EVIDENCE` 表示受控拒答，界面
  不应把它展示成系统错误。
- LLM Self-Query 抽取的 `product`/`version_values` 是硬过滤条件；过滤后零结果时
  直接展示证据不足，不使用未过滤结果补救。
- 引用只展示模型通过有效 `[cN]` 标记明确指向的 Chunk。模型回答没有有效引用
  标记时，按证据不足处理并清空引用，不得展示本轮全部检索片段。
- `citation_id` 保留模型原始 `[cN]` 标签；回答正文中的有效标记可点击，点击后滚动
  定位并展开对应引用，引用条目的摘要也可通过键盘或点击展开/收起。无匹配引用的
  标记显示为不可点击的不可用状态。
- 外部模型被策略拒绝时显示 `POLICY_DENIED`；已配置供应商不可用时显示
  `MODEL_UNAVAILABLE`，不进行抽取式回退。
- 流式响应支持停止生成和重新生成。

### 3.2 会话历史

| 项目 | 内容 |
| --- | --- |
| 路由 | `/chats` |
| 页面目标 | 查看、重命名、删除和继续历史会话 |
| 主要组件 | 会话列表、时间范围筛选、知识库筛选、删除确认 |
| 依赖 API | `GET /chats?team_id=`、`POST /chats/update`、`POST /chats/delete` |

## 4. 知识库与文档

### 4.1 知识库列表

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-bases` |
| 页面目标 | 查看知识库、成员范围、文档数量和默认策略 |
| 主要组件 | 知识库卡片/表格、搜索、创建入口、状态标签 |
| 依赖 API | `GET /kbs?team_id=`、`POST /kbs/create` |

### 4.2 知识库详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-bases/:kbId` |
| 页面目标 | 管理文档、来源、模型策略、索引状态和知识库成员范围 |
| 主要组件 | 文档列表、上传入口、GitHub 来源、任务状态、知识库策略摘要、成员范围列表与多选编辑器 |
| 依赖 API | `GET /kbs/detail?team_id=&kb_id=`、`GET /docs?team_id=&kb_id=`、`GET /sources?team_id=&kb_id=`、`GET /ingestions?team_id=`、`GET /kbs/members?team_id=&kb_id=`、`POST /kbs/members/update` |

知识库成员范围对所有有知识库访问权限的成员展示。团队 `leader` 可以从当前团队
所有 `active` 成员中选择并保存成员范围；`member` 和 `viewer` 仅能查看，不能
提交成员范围修改。平台 `admin` 不自动获得团队知识库的管理权限。

### 4.3 文件上传

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-bases/:kbId/upload` |
| 页面目标 | 上传 PDF、Markdown、TXT、DOCX 并设置元数据和可见性 |
| 主要组件 | 拖拽上传、文件列表、产品/版本、可见性、数据分类、提交按钮 |
| 依赖 API | `POST /docs/upload` |

### 4.4 GitHub 来源

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-bases/:kbId/sources/github` |
| 页面目标 | 添加仓库、分支、路径白名单和同步策略 |
| 主要组件 | 仓库 URL、分支、路径规则、扩展名、凭据选择、同步频率 |
| 依赖 API | `POST /sources/github/create`、`GET /credentials?team_id=` |

### 4.5 文档详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/documents/:documentId` |
| 页面目标 | 查看文档元数据、版本、解析状态、权限和下载入口 |
| 主要组件 | 元数据面板、版本时间线、来源链接、权限设置、重建按钮 |
| 依赖 API | `GET /docs/detail?team_id=&document_id=`、`GET /docs/versions?team_id=&document_id=`、`POST /docs/update`、`GET /docs/download?team_id=&document_id=`、`GET /docs/download-url?team_id=&document_id=` |

### 4.6 文档版本

| 项目 | 内容 |
| --- | --- |
| 路由 | `/documents/:documentId/versions/:versionId` |
| 页面目标 | 查看版本内容、解析质量、索引 generation 和 chunk 列表 |
| 主要组件 | 原文预览、版本切换、质量标记、chunk 入口 |
| 依赖 API | `GET /docs/version?team_id=&document_id=&version_id=`、`GET /docs/chunks?team_id=&document_id=` |

### 4.7 知识库策略

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-bases/:kbId/settings` |
| 页面目标 | 在团队策略上限内收紧知识库模型策略和默认数据分类 |
| 主要组件 | 数据分类默认值、模型策略、供应商范围、策略继承说明 |
| 依赖 API | `GET /kbs/policy?team_id=&kb_id=`、`POST /kbs/policy/update` |

## 5. 任务与内容治理

### 5.1 任务中心

| 项目 | 内容 |
| --- | --- |
| 路由 | `/tasks`、`/tasks/:runId` |
| 页面目标 | 查看入库、同步、重建和评测任务 |
| 主要组件 | 任务表格、阶段进度、失败原因、重试、取消、事件流 |
| 依赖 API | `GET /ingestions?team_id=`、`GET /ingestions/detail?team_id=&run_id=`、`GET /ingestions/events?team_id=&run_id=`、`POST /ingestions/retry`、`POST /ingestions/cancel` |

### 5.2 Chunk 管理

| 项目 | 内容 |
| --- | --- |
| 路由 | `/chunks`、`/chunks/:chunkId` |
| 页面目标 | 检查分块质量，编辑、禁用、启用和重新生成 |
| 主要组件 | chunk 表格、原文定位、质量标记、编辑器、历史版本 |
| 依赖 API | `GET /chunks?team_id=`、`GET /chunks/detail?team_id=&chunk_id=`、`POST /chunks/update`、`POST /chunks/disable`、`POST /chunks/enable`、`POST /chunks/regenerate`、`GET /chunks/history?team_id=&chunk_id=` |

### 5.3 检索调试台

| 项目 | 内容 |
| --- | --- |
| 路由 | `/traces`、`/traces/:traceId` |
| 主要用户 | `leader`、研发 |
| 页面目标 | 查看 Query Rewrite、过滤条件、候选、RRF、Rerank、最终上下文和模型信息 |
| 主要组件 | Trace 列表、QueryRewrite 摘要、阶段时间线、候选表格、引用映射、降级标记、用户反馈摘要 |
| 依赖 API | `GET /traces?team_id=`、`GET /traces/detail?team_id=&trace_id=` |

候选表格直接显示 Chunk 原文摘要，内容区域具备按钮语义和悬浮反馈，点击后在抽屉中
按“字段名 + 内容”查看完整明细，并可复制原始 JSON。无权限查看的私有 Chunk 只显示
受限提示，不展示正文；已被删除的 Chunk 显示记录不存在。

BM25 候选使用 Elasticsearch 返回的实际命中词在 Chunk 摘要中高亮；Dense、RRF、
Rerank 和最终上下文不显示关键词高亮。旧 Trace 没有命中词数据时保持普通文本。

候选表格按阶段显示对应分数：BM25、Dense、RRF、Rerank 分别展示
`bm25_score`、`dense_score`、`rrf_score`、`rerank_score`。旧 Trace 没有阶段专用
字段时回退到通用 `score`；仍无值时显示 `—`。

QueryRewrite 区块展示原始问题到检索问题的变化、来源标签（LLM 结构化、LLM JSON、
规则回退）、应用的 product/version 过滤条件、provider/model、耗时、token 和回退
原因。旧 Trace 没有改写元数据时不显示该区块。

### 5.4 知识缺口

| 项目 | 内容 |
| --- | --- |
| 路由 | `/knowledge-gaps` |
| 页面目标 | 聚合无答案、引用错误和高频失败问题 |
| 主要组件 | 问题聚类、来源、状态、转评测样本 |
| 依赖 API | `GET /gaps?team_id=`、`POST /gaps/update`、`POST /gaps/promote` |

## 6. 评测

### 6.1 黄金集列表

| 项目 | 内容 |
| --- | --- |
| 路由 | `/evaluations` |
| 页面目标 | 管理开发集、测试集和版本 |
| 主要组件 | 数据集列表、版本、样本数量、最近一次运行 |
| 依赖 API | `GET /evals/datasets?team_id=`、`POST /evals/datasets/create` |

### 6.2 黄金集详情

| 项目 | 内容 |
| --- | --- |
| 路由 | `/evaluations/:datasetId` |
| 页面目标 | 管理查询、相关性标注和样本分层 |
| 主要组件 | 样本表格、导入导出、类型筛选、标注编辑器 |
| 依赖 API | `GET /evals/datasets/cases?team_id=&dataset_id=`、`POST /evals/datasets/cases/create`、`POST /evals/datasets/cases/update`、`POST /evals/datasets/import` |

### 6.3 评测运行与报告

| 项目 | 内容 |
| --- | --- |
| 路由 | `/evaluations/runs/:runId` |
| 页面目标 | 查看运行进度、分类指标、失败样本和 A/B 对比 |
| 主要组件 | 进度条、指标卡、查询类型分布、失败归因、导出报告 |
| 依赖 API | `GET /evals/runs/detail?team_id=&run_id=`、`GET /evals/runs/report?team_id=&run_id=`、`GET /evals/runs/events?team_id=&run_id=` |

## 7. 模型策略与团队设置

### 7.1 团队设置

| 页面 | 路由 | 依赖 API |
| --- | --- | --- |
| 团队选择 | `/teams` | `GET /auth/me` |
| 团队资料 | `/settings/team` | `GET /teams/detail?team_id=`、`POST /teams/update` |
| 成员管理 | `/settings/members` | `POST /invitations/create`、`POST /members/update`、`POST /members/remove` |
| 模型策略 | `/settings/model-policy` | `GET /model-policy?team_id=`、`POST /model-policy/update` |
| 供应商 | `/settings/providers` | `GET /providers?team_id=`、`POST /providers/create`、`POST /providers/test` |
| 审计日志 | `/settings/audit` | `GET /audit?team_id=` |
| 索引管理 | `/settings/index-generations` | `GET /generations?team_id=`、`POST /generations/reindex`、`POST /generations/activate`、`POST /generations/rollback` |

### 7.2 平台设置

| 页面 | 路由 | 依赖 API |
| --- | --- | --- |
| 全局模型策略 | `/admin/model-policy` | `GET /admin/model-policy`、`POST /admin/model-policy/update`、`GET /admin/providers` |
| 供应商准入 | `/admin/model-providers` | `GET /admin/providers`、`POST /admin/providers/create`、`POST /admin/providers/update` |
| 用户管理 | `/admin/users` | `GET /admin/users`、`POST /admin/users/create`、`POST /admin/users/update`、`GET /teams` |
| 全局审计 | `/admin/audit`、`/admin/audit/:auditId` | `GET /admin/audit`、`GET /admin/audit/detail?audit_id=` |
| 系统状态 | `/admin/system` | `GET /health`、`GET /ready`、`GET /version` |

全局模型策略页同时提供部署级供应商准入区域：平台管理员从全部平台供应商中
多选允许团队继承的供应商，保存时以完整 `allowed_provider_ids` 列表更新部署
策略。列表展示供应商类型、启停状态、模型和 API Key 可用性；没有供应商时提供
前往供应商准入页的入口。`local_only` 模式下允许保留准入选择，但明确提示外部
模型调用当前禁用。

团队模型策略页可从部署级允许的供应商中重新选择任意子集；因此团队列表可以从空
列表添加供应商，也可以移除供应商。模式、数据分类、聊天历史和文档元数据开关仍受
部署级及既有团队安全上限约束。

## 8. 页面与 API 优先级

| 优先级 | 页面 |
| --- | --- |
| P0 | 登录与管理员开户、问答工作台、会话历史、知识库列表/详情/策略、文件上传、GitHub 来源、文档版本与恢复、任务中心、Chunk 管理、检索调试、评测列表/详情/报告、团队成员、模型策略、平台设置、审计、索引管理 |
| P1 | 知识缺口、Trace 回放、评测 A/B 对比、供应商测试、找回密码 |
| P2 | Confluence/Notion/Slack/Drive 等连接器、源系统 ACL、知识图谱、Agentic Retrieval |

## 9. 前端并行开发约定

- 页面组件只调用 `docs/api/openapi.yaml` 中定义的接口。
- 未完成的后端接口使用 OpenAPI 示例或 MSW mock，不自行定义字段。
- 任何接口字段变更必须先改 OpenAPI，再同步前端类型和后端实现。
- 声明支持游标分页的列表必须实现继续加载和错误重试；派生聚合结果不得伪造
  `has_more=true`。
- 所有写操作显示 `request_id`，便于联调时定位日志。
- SSE 流式问答不得使用轮询替代，除不支持 SSE 的环境外不提供降级实现。

