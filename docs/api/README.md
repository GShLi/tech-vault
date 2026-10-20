# API 与页面联调文档

- [页面与路由清单](../product/page-map.md)
- [API 契约](./api-contract.md)
- [OpenAPI 契约](./openapi.yaml)

约定：

- 所有业务接口使用 `/api/v1`。
- 路径中不放置团队 ID 和资源 ID；写操作参数放在请求体，查询接口只使用少量 query 参数。
- JSON 字段使用 `snake_case`，ID 使用 ULID，时间使用 UTC ISO 8601。
- 分页列表统一返回带具体 item schema 的 `PageEnvelope`；未声明 `limit`/`cursor`
  的读取接口不得按分页接口调用。
- 错误使用统一 `error.code`、`details` 和 `request_id`。
- 可编辑资源使用 `If-Match` 做乐观锁。
- 流式问答使用 SSE；文档入库任务使用 SSE 阶段快照，不使用轮询替代。
- `api-contract.md` 是当前 P0 语义基线，`openapi.yaml` 是机器可读契约；写接口使用
  具名请求 schema，分页接口使用带具体 item schema 的 `PageEnvelope`。

当前状态：

- P0 HTTP 路由和页面依赖以 `api-contract.md`、`page-map.md` 为准。
- 契约中标记为 P1 的能力是路线图条目，不保证当前后端已提供对应路由。
- P0 不实现 `Idempotency-Key` 重放缓存；客户端不得假设写请求可以安全重放。

