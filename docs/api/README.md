# API 与页面联调文档

- [页面与路由清单](../product/page-map.md)
- [API 契约](./api-contract.md)
- [OpenAPI 骨架](./openapi.yaml)

约定：

- 所有业务接口使用 `/api/v1`。
- 路径中不放置团队 ID 和资源 ID；写操作参数放在请求体，查询接口只使用少量 query 参数。
- JSON 字段使用 `snake_case`，ID 使用 ULID，时间使用 UTC ISO 8601。
- 列表使用游标分页，错误使用统一 `error.code` 和 `request_id`。
- 可编辑资源使用 `If-Match` 做乐观锁。
- 问答和任务进度使用 SSE，不使用轮询替代。
- OpenAPI 是前端生成类型和 mock 的基线；接口变更先修改契约。

