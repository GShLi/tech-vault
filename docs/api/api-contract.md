# TechVault API 契约

本文档是前后端联调的接口基线。机器可读版本见 [`openapi.yaml`](./openapi.yaml)。

## 1. 基础约定

### 1.1 基础路径

```text
https://<host>/api/v1
```

所有 P0 业务接口使用 `/api/v1`。健康检查、就绪检查和版本接口也使用版本前缀：

```text
GET /api/v1/health
GET /api/v1/ready
GET /api/v1/version
```

### 1.2 认证

业务接口使用 Bearer Access Token：

```http
Authorization: Bearer <access_token>
```

登录接口返回短期 Access Token，并通过 `HttpOnly + Secure + SameSite=Lax` Cookie 保存 Refresh Token。前端不得把 Refresh Token 写入 `localStorage`。

权限规则：

- 默认拒绝，缺少团队或知识库范围时不执行无过滤检索。
- `team_admin` 和 `platform_admin` 默认都不能查看成员私有文档正文，只有所有者或显式授权用户可以访问。
- 团队管理员只能收紧部署级策略；普通成员只能选择比团队和知识库策略更严格的模型范围。

### 1.3 通用请求头

| Header | 必填 | 用途 |
| --- | --- | --- |
| `Authorization` | 业务接口必填 | Bearer Token |
| `X-Request-Id` | 可选 | 客户端生成的请求 ID；服务端仍会返回自己的 `request_id` |
| `Idempotency-Key` | 写操作建议必填 | 上传、同步、重建、评测等幂等控制 |
| `If-Match` | 编辑资源必填 | 乐观锁，值为资源 `version` |
| `Accept-Language` | 可选 | 错误提示和界面语言 |

### 1.4 通用响应头

| Header | 用途 |
| --- | --- |
| `X-Request-Id` | 服务端请求 ID |
| `X-RateLimit-Remaining` | 剩余请求次数 |
| `X-RateLimit-Reset` | 限流重置时间 |
| `Retry-After` | 限流或可恢复错误建议等待秒数 |

### 1.5 字段格式

- JSON 字段统一使用 `snake_case`。
- ID 使用 ULID 字符串，前端不得解析。
- 时间使用 UTC ISO 8601，例如 `2026-10-18T12:00:00Z`。
- 金额使用整数 `cost_micros`，1 美元等于 `1000000`。
- 耗时使用整数毫秒，例如 `latency_ms`。
- 枚举使用小写 `snake_case`，未识别的枚举值前端应原样展示为“未知状态”。

## 2. 响应格式

### 2.1 单资源

```json
{
  "data": {
    "id": "01JABCDEF0123456789012345",
    "created_at": "2026-10-18T12:00:00Z"
  },
  "meta": {
    "request_id": "req_01JABCDEF0123456789012345"
  }
}
```

### 2.2 列表

```json
{
  "data": [],
  "meta": {
    "next_cursor": "eyJpZCI6IjAxSkFCQ0RFRiJ9",
    "has_more": false,
    "request_id": "req_01JABCDEF0123456789012345"
  }
}
```

分页参数：

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `limit` | integer | 20 | 1 至 100 |
| `cursor` | string | null | 服务端返回的 opaque cursor |
| `sort` | string | `-created_at` | 前缀 `-` 表示降序 |

### 2.3 错误

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "You do not have permission to access this resource.",
    "details": {},
    "request_id": "req_01JABCDEF0123456789012345"
  }
}
```

错误码：

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | `INVALID_ARGUMENT` | 参数格式或业务规则错误 |
| 401 | `UNAUTHENTICATED` | 未登录或 Token 失效 |
| 403 | `PERMISSION_DENIED` | 无资源权限；不得泄露资源是否存在 |
| 403 | `POLICY_DENIED` | 数据出境或模型策略拒绝 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `VERSION_CONFLICT` | `If-Match` 版本不一致 |
| 409 | `RESOURCE_STATE_CONFLICT` | 当前状态不允许该操作 |
| 409 | `DUPLICATE_RESOURCE` | 内容指纹或唯一键重复 |
| 413 | `PAYLOAD_TOO_LARGE` | 文件超过限制 |
| 422 | `VALIDATION_FAILED` | 字段级校验失败，`details.fields` 返回路径和原因 |
| 429 | `RATE_LIMITED` | 请求过于频繁 |
| 500 | `INTERNAL_ERROR` | 未分类服务端错误 |
| 503 | `SERVICE_UNAVAILABLE` | 索引、模型或依赖服务不可用 |
| 503 | `INDEX_NOT_READY` | 当前索引 generation 未激活 |

### 2.4 乐观锁

所有可编辑资源返回整数 `version`。`PATCH` 必须发送：

```http
If-Match: "7"
```

版本不一致返回 `409 VERSION_CONFLICT`，前端提示用户刷新，不自动覆盖。

### 2.5 幂等

以下接口建议使用 `Idempotency-Key`，同一个 Key 在 24 小时内返回同一操作结果：

- 文件上传
- GitHub 来源同步
- 文档重建
- 索引 generation 切换
- 评测运行

## 3. 通用枚举

```text
role: team_admin | member | viewer | platform_admin
visibility: private | team_shared
data_classification: public | internal | private | restricted
doc_status: active | building | deleting | deleted | failed
chunk_status: enabled | disabled
ingestion_status: queued | fetching | parsing | chunking | embedding | indexing | validating | active | failed | deleting | cancelled
evaluation_status: queued | running | succeeded | failed | cancelled
engine_mode: dual_engine | elastic_single
model_policy_mode: local_only | external_allowed | external_required
feedback_type: useful | not_useful | citation_error | knowledge_gap
message_status: generating | completed | refused | cancelled | failed
```

## 4. 认证与团队

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | 注册账号 | P0 |
| `POST` | `/auth/login` | 登录并返回 Access Token | P0 |
| `POST` | `/auth/refresh` | 刷新 Access Token | P0 |
| `POST` | `/auth/logout` | 注销并清除 Refresh Token | P0 |
| `GET` | `/auth/me` | 当前用户和团队列表 | P0 |
| `PATCH` | `/users/me` | 更新个人资料 | P0 |
| `POST` | `/auth/password/change` | 修改密码 | P0 |
| `POST` | `/auth/password/forgot` | 发起密码重置 | P1 |
| `GET` | `/teams` | 当前用户的团队列表 | P0 |
| `POST` | `/teams` | 创建团队 | P0 |
| `GET` | `/teams/{team_id}` | 团队详情 | P0 |
| `PATCH` | `/teams/{team_id}` | 团队设置 | P0 |
| `GET` | `/teams/{team_id}/members` | 成员列表 | P0 |
| `POST` | `/teams/{team_id}/invitations` | 邀请成员 | P0 |
| `GET` | `/invitations/{token}` | 查看邀请 | P0 |
| `POST` | `/invitations/{token}/accept` | 接受邀请 | P0 |
| `PATCH` | `/teams/{team_id}/members/{user_id}` | 修改角色或状态 | P0 |
| `DELETE` | `/teams/{team_id}/members/{user_id}` | 移除成员 | P0 |
| `POST` | `/teams/{team_id}/members/{user_id}/transfer-private-documents` | 转移离职成员私有文档 | P0 |

## 5. 知识库

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/knowledge-bases` | 知识库列表 | P0 |
| `POST` | `/teams/{team_id}/knowledge-bases` | 创建知识库 | P0 |
| `GET` | `/teams/{team_id}/knowledge-bases/{kb_id}` | 知识库详情 | P0 |
| `PATCH` | `/teams/{team_id}/knowledge-bases/{kb_id}` | 更新名称、描述和成员范围 | P0 |
| `DELETE` | `/teams/{team_id}/knowledge-bases/{kb_id}` | 归档或软删除 | P0 |
| `GET` | `/teams/{team_id}/knowledge-bases/{kb_id}/policy` | 知识库默认模型策略 | P0 |
| `PATCH` | `/teams/{team_id}/knowledge-bases/{kb_id}/policy` | 收紧知识库策略 | P0 |
| `GET` | `/teams/{team_id}/retrieval-facets` | 产品、版本、来源和可选知识库范围 | P0 |

## 6. 文档与来源

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/knowledge-bases/{kb_id}/documents` | 文档列表 | P0 |
| `POST` | `/teams/{team_id}/knowledge-bases/{kb_id}/documents/upload` | 上传单个文件 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}` | 文档详情 | P0 |
| `PATCH` | `/teams/{team_id}/documents/{document_id}` | 元数据、可见性、分类、所有者 | P0 |
| `DELETE` | `/teams/{team_id}/documents/{document_id}` | 软删除并停止召回 | P0 |
| `POST` | `/teams/{team_id}/documents/{document_id}/restore` | 恢复软删除文档 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/versions` | 文档版本列表 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/versions/{version_id}` | 版本详情 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/download-url` | 获取短期签名下载地址 | P0 |
| `POST` | `/teams/{team_id}/documents/{document_id}/rebuild` | 重建文档索引 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/grants` | 私有文档显式授权列表 | P0 |
| `POST` | `/teams/{team_id}/documents/{document_id}/grants` | 添加显式授权 | P0 |
| `DELETE` | `/teams/{team_id}/documents/{document_id}/grants/{grant_id}` | 撤销显式授权 | P0 |
| `GET` | `/teams/{team_id}/knowledge-bases/{kb_id}/sources` | 来源列表 | P0 |
| `POST` | `/teams/{team_id}/knowledge-bases/{kb_id}/sources/github` | 添加 GitHub 来源 | P0 |
| `GET` | `/teams/{team_id}/sources/{source_id}` | 来源详情 | P0 |
| `PATCH` | `/teams/{team_id}/sources/{source_id}` | 修改分支、路径和同步设置 | P0 |
| `DELETE` | `/teams/{team_id}/sources/{source_id}` | 删除来源 | P0 |
| `POST` | `/teams/{team_id}/sources/{source_id}/sync` | 触发增量同步 | P0 |
| `POST` | `/teams/{team_id}/sources/{source_id}/pause` | 暂停同步 | P0 |
| `POST` | `/teams/{team_id}/sources/{source_id}/resume` | 恢复同步 | P0 |
| `GET` | `/teams/{team_id}/credentials` | GitHub 等来源凭据列表 | P0 |
| `POST` | `/teams/{team_id}/credentials` | 创建只写凭据 | P0 |
| `DELETE` | `/teams/{team_id}/credentials/{credential_id}` | 删除凭据 | P0 |

文件上传请求：

```http
POST /api/v1/teams/{team_id}/knowledge-bases/{kb_id}/documents/upload
Content-Type: multipart/form-data
Idempotency-Key: upload-01JABCDEF
```

字段：

- `file`：单个文件，P0 最大 50 MB。
- `metadata`：JSON 字符串，包含 `product`、`version_values`、`visibility`、`data_classification`、`owner_user_id`。

成功返回 `202 Accepted`，同时创建 `document`、`document_version` 和 `ingestion_run`。

## 7. 入库任务

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/ingestion-runs` | 任务列表 | P0 |
| `GET` | `/teams/{team_id}/ingestion-runs/{run_id}` | 任务详情和阶段进度 | P0 |
| `GET` | `/teams/{team_id}/ingestion-runs/{run_id}/events` | SSE 任务事件 | P0 |
| `POST` | `/teams/{team_id}/ingestion-runs/{run_id}/retry` | 从可恢复阶段重试 | P0 |
| `POST` | `/teams/{team_id}/ingestion-runs/{run_id}/cancel` | 取消未完成任务 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/tasks` | 文档最近任务 | P0 |

任务 SSE 事件：

```text
event: progress
data: {"stage":"embedding","processed":120,"total":300,"percent":40.0}

event: warning
data: {"code":"PARTIAL_PARSE","message":"2 pages contain no extractable text"}

event: completed
data: {"run_id":"...","status":"active","index_generation":"..."}

event: failed
data: {"run_id":"...","status":"failed","error_code":"PARSING_FAILED","retryable":true}
```

## 8. Chunk

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/chunks` | chunk 列表和筛选 | P0 |
| `GET` | `/teams/{team_id}/chunks/{chunk_id}` | chunk 详情 | P0 |
| `PATCH` | `/teams/{team_id}/chunks/{chunk_id}` | 编辑内容或结构信息 | P0 |
| `POST` | `/teams/{team_id}/chunks/{chunk_id}/disable` | 禁用 chunk | P0 |
| `POST` | `/teams/{team_id}/chunks/{chunk_id}/enable` | 启用 chunk | P0 |
| `POST` | `/teams/{team_id}/chunks/{chunk_id}/regenerate` | 重新生成 chunk | P0 |
| `GET` | `/teams/{team_id}/chunks/{chunk_id}/history` | 人工修改和状态历史 | P0 |
| `GET` | `/teams/{team_id}/documents/{document_id}/chunks` | 按文档查看 chunk | P0 |
| `POST` | `/teams/{team_id}/chunks/bulk` | 批量禁用或启用 | P1 |

Chunk 编辑必须发送 `If-Match`。人工修改保存在 `chunk_override` 中，重建索引时不得覆盖未确认的覆盖记录。

## 9. 问答与会话

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/conversations` | 会话列表 | P0 |
| `POST` | `/teams/{team_id}/conversations` | 创建会话 | P0 |
| `GET` | `/teams/{team_id}/conversations/{conversation_id}` | 会话详情 | P0 |
| `PATCH` | `/teams/{team_id}/conversations/{conversation_id}` | 重命名会话 | P0 |
| `DELETE` | `/teams/{team_id}/conversations/{conversation_id}` | 删除会话 | P0 |
| `GET` | `/teams/{team_id}/conversations/{conversation_id}/messages` | 消息列表 | P0 |
| `POST` | `/teams/{team_id}/conversations/{conversation_id}/ask` | 发起问答并返回 SSE | P0 |
| `POST` | `/teams/{team_id}/conversations/{conversation_id}/messages/{message_id}/cancel` | 取消生成 | P0 |
| `GET` | `/teams/{team_id}/messages/{message_id}` | 消息详情 | P0 |
| `GET` | `/teams/{team_id}/messages/{message_id}/citations` | 引用列表 | P0 |
| `POST` | `/teams/{team_id}/messages/{message_id}/feedback` | 用户反馈 | P0 |

### 9.1 问答请求

```json
{
  "question": "Spring Boot 3.2 如何配置虚拟线程？",
  "filters": {
    "knowledge_base_ids": ["01JKB00000000000000000001"],
    "product": "spring-boot",
    "version_values": ["3.2"]
  },
  "model_policy": "inherit",
  "stream": true
}
```

标准请求必须使用 `Accept: text/event-stream`。服务端自行决定检索参数，普通用户不能直接设置 TopK、RRF 或 Rerank 参数。

### 9.2 SSE 事件

```text
event: meta
data: {"trace_id":"...","message_id":"...","engine_mode":"dual_engine","model_id":"...","degraded":false}

event: rewrite
data: {"original":"它和 2.x 有什么区别？","rewritten":"Spring Boot 3.x 自动配置与 2.x 有什么区别？"}

event: citation
data: {"citation_id":"c1","chunk_id":"...","document_id":"...","document_name":"...","page_no":12,"heading_path":["Spring Boot","Auto-configuration"],"source_url":"..."}

event: delta
data: {"text":"Spring Boot 3.2 "}

event: done
data: {"message_id":"...","status":"completed","citation_ids":["c1"],"input_tokens":1200,"output_tokens":320,"cost_micros":0,"latency_ms":2400}

event: refused
data: {"message_id":"...","status":"refused","reason_code":"INSUFFICIENT_EVIDENCE","message":"知识库中没有足够依据。"}

event: error
data: {"code":"MODEL_UNAVAILABLE","message":"No approved model is available.","retryable":true,"request_id":"..."}
```

客户端使用 `AbortController` 取消请求。服务端收到断开后停止生成，并保存已生成内容和取消状态。

## 10. 检索 Trace

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/traces` | Trace 列表 | P0 |
| `GET` | `/teams/{team_id}/traces/{trace_id}` | 完整问答链路 | P0 |
| `POST` | `/teams/{team_id}/traces/{trace_id}/replay` | 用新版本重放 | P1 |
| `GET` | `/teams/{team_id}/traces/{trace_id}/export` | 导出评测快照 | P1 |

Trace 详情至少返回：

- Query Rewrite 前后文本。
- 实际过滤条件。
- BM25 和 Dense 候选及排名。
- RRF 和 Rerank 排名。
- 最终上下文和引用映射。
- 模型、策略、token、成本和耗时。
- `degraded`、错误和用户反馈。

## 11. 评测

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/evaluation-datasets` | 黄金集列表 | P0 |
| `POST` | `/teams/{team_id}/evaluation-datasets` | 创建黄金集 | P0 |
| `GET` | `/teams/{team_id}/evaluation-datasets/{dataset_id}` | 黄金集详情 | P0 |
| `PATCH` | `/teams/{team_id}/evaluation-datasets/{dataset_id}` | 更新名称和版本 | P0 |
| `DELETE` | `/teams/{team_id}/evaluation-datasets/{dataset_id}` | 归档黄金集 | P0 |
| `GET` | `/teams/{team_id}/evaluation-datasets/{dataset_id}/cases` | 样本列表 | P0 |
| `POST` | `/teams/{team_id}/evaluation-datasets/{dataset_id}/cases` | 新增样本 | P0 |
| `PATCH` | `/teams/{team_id}/evaluation-datasets/{dataset_id}/cases/{case_id}` | 修改样本 | P0 |
| `DELETE` | `/teams/{team_id}/evaluation-datasets/{dataset_id}/cases/{case_id}` | 删除样本 | P0 |
| `POST` | `/teams/{team_id}/evaluation-datasets/{dataset_id}/import` | 导入 JSONL | P0 |
| `GET` | `/teams/{team_id}/evaluation-runs` | 评测运行列表 | P0 |
| `POST` | `/teams/{team_id}/evaluation-runs` | 发起评测 | P0 |
| `GET` | `/teams/{team_id}/evaluation-runs/{run_id}` | 运行状态 | P0 |
| `GET` | `/teams/{team_id}/evaluation-runs/{run_id}/events` | 运行 SSE | P0 |
| `POST` | `/teams/{team_id}/evaluation-runs/{run_id}/cancel` | 取消运行 | P0 |
| `GET` | `/teams/{team_id}/evaluation-runs/{run_id}/report` | 评测报告 | P0 |
| `POST` | `/teams/{team_id}/evaluation-comparisons` | A/B 对比 | P1 |
| `GET` | `/teams/{team_id}/evaluation-comparisons/{comparison_id}` | 对比结果 | P1 |

评测运行请求：

```json
{
  "dataset_id": "01JDATASET0000000000000001",
  "engine_mode": "dual_engine",
  "judge_mode": "rules_and_manual",
  "baseline_run_id": null
}
```

P0 的 `judge_mode` 允许 `rules`、`rules_and_manual`。LLM-as-Judge 在评分口径校准后再启用。

## 12. 模型策略与审计

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/model-policy` | 团队模型策略 | P0 |
| `PATCH` | `/teams/{team_id}/model-policy` | 收紧团队模型策略 | P0 |
| `GET` | `/teams/{team_id}/knowledge-bases/{kb_id}/policy` | 知识库模型策略 | P0 |
| `PATCH` | `/teams/{team_id}/knowledge-bases/{kb_id}/policy` | 收紧知识库模型策略 | P0 |
| `GET` | `/teams/{team_id}/model-providers` | 可用供应商 | P0 |
| `POST` | `/teams/{team_id}/model-providers` | 创建供应商配置 | P0 |
| `POST` | `/teams/{team_id}/model-providers/{provider_id}/test` | 健康检查 | P1 |
| `GET` | `/teams/{team_id}/llm-invocations` | 模型调用审计 | P0 |
| `GET` | `/teams/{team_id}/audit-logs` | 业务审计日志 | P0 |
| `GET` | `/teams/{team_id}/audit-logs/{audit_id}` | 审计详情 | P0 |
| `GET` | `/admin/deployment-model-policy` | 部署级策略 | P0 |
| `PATCH` | `/admin/deployment-model-policy` | 修改部署级上限 | P0 |
| `GET` | `/admin/model-providers` | 全部供应商 | P0 |
| `POST` | `/admin/model-providers` | 创建全局供应商 | P0 |
| `PATCH` | `/admin/model-providers/{provider_id}` | 修改供应商 | P0 |
| `GET` | `/admin/models` | 模型列表 | P0 |
| `PATCH` | `/admin/models/{model_id}` | 启用或禁用模型 | P0 |

API Key 只写不读。任何响应都不得返回完整密钥，只能返回掩码和最后更新时间。

## 13. 知识缺口

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/knowledge-gaps` | 知识缺口列表 | P1 |
| `PATCH` | `/teams/{team_id}/knowledge-gaps/{gap_id}` | 更新处理状态 | P1 |
| `POST` | `/teams/{team_id}/knowledge-gaps/{gap_id}/promote` | 转为评测样本 | P1 |

## 14. 索引管理

| 方法 | 路径 | 说明 | 优先级 |
| --- | --- | --- | --- |
| `GET` | `/teams/{team_id}/index-generations` | generation 列表 | P0 |
| `GET` | `/teams/{team_id}/index-generations/{generation_id}` | generation 详情 | P0 |
| `GET` | `/teams/{team_id}/index-generations/{generation_id}/validation` | 校验结果 | P0 |
| `POST` | `/teams/{team_id}/index-generations/{generation_id}/validate` | 重新校验 | P0 |
| `POST` | `/teams/{team_id}/index-generations/{generation_id}/activate` | 激活 generation | P0 |
| `POST` | `/teams/{team_id}/index-generations/{generation_id}/rollback` | 回滚到上一个 active | P0 |

## 15. 核心数据对象

### 14.1 KnowledgeBase

```json
{
  "id": "01JKB00000000000000000001",
  "team_id": "01JTEAM000000000000000001",
  "name": "Spring 技术资料",
  "description": "团队共享技术文档",
  "default_model_policy_mode": "local_only",
  "document_count": 42,
  "version": 3,
  "created_at": "2026-10-18T12:00:00Z",
  "updated_at": "2026-10-18T12:00:00Z"
}
```

### 14.2 Document

```json
{
  "id": "01JDOC0000000000000000001",
  "knowledge_base_id": "01JKB00000000000000000001",
  "owner_user_id": "01JUSER00000000000000001",
  "source_type": "upload",
  "source_uri": "s3://local/...",
  "file_name": "spring-boot-reference.pdf",
  "product": "spring-boot",
  "version_family": "3.x",
  "version_values": ["3.2", "3.3"],
  "visibility": "team_shared",
  "data_classification": "internal",
  "doc_status": "active",
  "current_version_id": "01JDV00000000000000000001",
  "version": 2,
  "created_at": "2026-10-18T12:00:00Z",
  "updated_at": "2026-10-18T12:00:00Z"
}
```

### 14.3 Chunk

```json
{
  "id": "01JCHUNK00000000000000001",
  "document_id": "01JDOC0000000000000000001",
  "document_version_id": "01JDV00000000000000000001",
  "content": "Virtual threads are ...",
  "heading_path": ["Spring Boot", "Virtual Threads"],
  "source_locator": {
    "page_no": 12,
    "line_start": 120,
    "line_end": 132
  },
  "status": "enabled",
  "quality_flags": [],
  "version": 1,
  "index_generation": "gen-20261018-01",
  "updated_at": "2026-10-18T12:00:00Z"
}
```

### 14.4 Conversation 与 Message

```json
{
  "id": "01JCONV000000000000000001",
  "title": "Spring Boot 虚拟线程",
  "knowledge_base_ids": ["01JKB00000000000000000001"],
  "created_at": "2026-10-18T12:00:00Z",
  "updated_at": "2026-10-18T12:00:00Z"
}
```

```json
{
  "id": "01JMSG000000000000000001",
  "conversation_id": "01JCONV000000000000000001",
  "role": "assistant",
  "content": "Spring Boot 3.2 ...",
  "status": "completed",
  "trace_id": "01JTRACE0000000000000001",
  "citation_ids": ["c1", "c2"],
  "refusal_reason": null,
  "created_at": "2026-10-18T12:00:00Z"
}
```

### 14.5 Citation

```json
{
  "citation_id": "c1",
  "chunk_id": "01JCHUNK00000000000000001",
  "document_id": "01JDOC0000000000000000001",
  "document_name": "spring-boot-reference.pdf",
  "page_no": 12,
  "heading_path": ["Spring Boot", "Virtual Threads"],
  "source_url": "/api/v1/teams/.../documents/.../download-url",
  "excerpt": "Virtual threads are ...",
  "support_score": 0.91
}
```

## 16. 前后端联调规则

1. OpenAPI 是字段和路径的唯一来源，任何接口变更先修改契约。
2. 前端通过生成的 TypeScript 类型或客户端调用，不手写重复 DTO。
3. 后端在接口未实现前提供 OpenAPI 示例或 mock server。
4. 所有错误响应必须包含稳定的 `code` 和 `request_id`。
5. 列表接口不得返回无分页的全量数据。
6. SSE 事件必须向前兼容：新增事件类型时旧前端忽略未知事件。
7. 涉及权限、策略、索引和删除的测试必须同时覆盖成功、拒绝和冲突状态。

