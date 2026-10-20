# LLM Query Rewrite and Self-Query

Date: 2026-10-20
Status: Approved design, pending implementation

## Goal

将 QueryRewrite 从本地确定性规则升级为由本次问答选择的 LLM 完成，并在同一次结构化
输出中执行 Self-Query：生成检索查询，同时抽取可安全应用的元数据过滤条件。

本期只允许 LLM 抽取 `product` 和 `version_values`。所有权限、团队、知识库、可见性、
数据分级和文档授权字段继续由服务端控制，LLM 不得参与。

## Non-Goals

- 不新增独立的改写模型配置，复用本次问答选择的 provider/model。
- 不提供 Self-Query 开关；本期默认启用且不可关闭。
- 不实现过滤条件加权、软过滤或零结果放宽。
- 不抽取 `source_type`、`visibility`、`data_classification`、时间或自定义标签。
- 不生成多个子查询，不做 HyDE、step-back 或查询扩展。
- 不改变现有答案生成、引用校验和拒答策略。

## Decisions

1. LLM 改写优先：每个问题先调用 LLM 改写；失败后回退本地规则，不阻断问答。
2. 结构化输出优先：先 `json_schema`，不支持时降级 `json_object`/Prompt JSON。
3. LLM 返回原文是有效结果，按原样保留；指代存在歧义时也保持原问题。
4. Self-Query 使用原生硬过滤，不做加权。
5. 用户显式选择的过滤条件优先于 LLM 抽取值。
6. 硬过滤后零结果直接按 `INSUFFICIENT_EVIDENCE` 拒答，不放宽、不重试。
7. `allow_chat_history=true` 时才把最近 6 条历史脱敏后发送给外部 LLM。

## Flow

```text
用户问题
  -> 读取最近 6 条历史（受 allow_chat_history 约束）
  -> 构造改写 Prompt（问题 + 历史 + 显式筛选 + facets 白名单）
  -> LLM 结构化输出
  -> 校验 JSON 和过滤条件
  -> 合并用户显式过滤条件
  -> Embedding
  -> ES/Qdrant 硬过滤 + 混合召回
  -> RRF、Rerank、上下文组装
  -> 答案生成
  -> 保存 QueryRewrite 与检索 Trace
```

改写失败时使用本地规则结果；规则结果不新增 Self-Query 条件，只保留用户显式过滤。

## Structured Output Contract

```json
{
  "rewritten_query": "Spring Boot 3.2 如何开启虚拟线程？",
  "filters": {
    "product": "spring-boot",
    "version_values": ["3.2"]
  }
}
```

JSON Schema：

```json
{
  "type": "object",
  "properties": {
    "rewritten_query": {
      "type": "string"
    },
    "filters": {
      "type": "object",
      "properties": {
        "product": {
          "anyOf": [{"type": "string"}, {"type": "null"}]
        },
        "version_values": {
          "type": "array",
          "items": {"type": "string"}
        }
      },
      "required": ["product", "version_values"],
      "additionalProperties": false
    }
  },
  "required": ["rewritten_query", "filters"],
  "additionalProperties": false
}
```

`null` 表示不抽取。`version_values` 为空数组表示不抽取版本条件。

远程 Schema 只使用结构化输出广泛支持的 JSON Schema 子集；长度、唯一性和最大数量
由服务端校验，避免不同模型对 `minLength`、`maxItems`、`uniqueItems` 支持不一致。

## Prompt

System Prompt：

```text
You rewrite the latest user question into one self-contained search query for a
technical knowledge base retrieval system, and extract only the metadata filters
explicitly supported by the provided filter schema.

Rules:
- Use conversation history only to resolve references and omitted context.
- Resolve pronouns only when exactly one clear antecedent exists; otherwise keep
  the original question unchanged.
- Preserve the user's language, intent, entities, versions, code identifiers,
  error messages, and constraints.
- Add product/version filters only when they are explicit in the question or
  unambiguous from the recent conversation.
- Never invent facts, products, versions, or requirements.
- Do not answer, explain, translate, or split the question.
- If no rewrite is needed, return the original question unchanged.
- Return JSON only, matching the provided schema.
```

User Prompt 包含：

- 最新问题。
- 最近 6 条历史，每条截断到 1000 字符。
- 请求中已有的 product/version 筛选值。
- 当前团队 `/facets` 返回的规范 product/version 值。

历史中只保留 `user` 和 `assistant` 角色；外部调用前执行现有敏感信息扫描和脱敏。
facets 列表按固定顺序传入并设置总量上限，最终仍以服务端白名单校验为准。

## Provider Adapters

### OpenAI Chat Completions

严格模式：

```json
{
  "model": "model-id",
  "messages": [
    {"role": "system", "content": "<system prompt>"},
    {"role": "user", "content": "<user prompt>"}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "query_rewrite",
      "strict": true,
      "schema": {"$ref": "#query_rewrite_schema"}
    }
  }
}
```

降级模式：

```json
{
  "response_format": {"type": "json_object"}
}
```

### OpenAI Responses

严格模式：

```json
{
  "model": "model-id",
  "input": "<system prompt + user prompt>",
  "text": {
    "format": {
      "type": "json_schema",
      "name": "query_rewrite",
      "strict": true,
      "schema": {"$ref": "#query_rewrite_schema"}
    }
  }
}
```

降级模式：

```json
{
  "text": {"format": {"type": "json_object"}}
}
```

### Anthropic Messages

严格模式使用强制工具调用：

```json
{
  "model": "model-id",
  "max_tokens": 256,
  "messages": [{"role": "user", "content": "<prompt>"}],
  "tools": [
    {
      "name": "submit_query_rewrite",
      "description": "Submit the rewritten query and metadata filters.",
      "input_schema": {"$ref": "#query_rewrite_schema"}
    }
  ],
  "tool_choice": {"type": "tool", "name": "submit_query_rewrite"}
}
```

解析 `content` 中 `type=tool_use` 且 `name=submit_query_rewrite` 的 `input`。
工具不可用时降级为 Prompt JSON 文本，再由后台校验。

示例中的 `$ref` 只是文档引用标记；实际请求内联上方 Structured Output Contract 的完整
JSON Schema。

### Capability Downgrade

只有明确的“结构化参数不支持”错误才触发降级，例如 HTTP 400/422 且错误体指向
`response_format`、`json_schema`、`text.format` 或 `tool_choice`。其他网络、鉴权、
限流和服务错误直接进入规则回退。

## Validation

服务端按以下顺序校验：

1. 响应必须是 JSON 对象，不能包含 Markdown 代码块或额外文本。
2. `rewritten_query` 必须是非空字符串，去除首尾空白并折叠连续空白。
3. 长度必须在 1–4000 字符之间。
4. `filters` 必须是对象，只允许 `product` 和 `version_values`。
5. `product` 必须是字符串或 `null`。
6. `version_values` 必须是字符串数组，去重后最多 5 个。
7. LLM 值必须能映射到当前团队 facets 的规范值，比较时忽略首尾空白、大小写、
   空格和连字符差异。
8. 用户显式选择的 product/version 优先；冲突的 LLM 值丢弃并记录原因。
9. 校验失败时使用规则改写；不把非法过滤条件带入检索。

## Filter Merge

```text
applied_product = 用户显式 product 或 LLM product
applied_versions = 用户显式 versions 或 LLM versions
```

如果用户显式选择了字段，LLM 对该字段的值不覆盖、不合并。被丢弃的值写入
`dropped_filters`，原因包括 `unknown_facet_value`、`user_override` 和
`invalid_type`。

安全字段永远不进入 LLM schema，也不接受 LLM 输出：

- `team_id`
- `knowledge_base_ids`
- `viewer_user_id`
- `visibility`
- `data_classification`
- `explicit_document_grants`

## Retrieval Semantics

Self-Query 过滤条件直接写入 `RetrievalFilters`，在召回阶段执行：

- Elasticsearch：`term(product)`、`terms(version_values)`
- Qdrant：`match(product)`、`match(any=version_values)`
- 内存检索：与 ES/Qdrant 相同的缺失字段语义

当前内存检索会把缺少 `product`/`version_values` 的 chunk 当作匹配，必须改为字段缺失
即不匹配，确保三套引擎一致。

硬过滤后 `result.chunks` 为空时返回：

```json
{
  "status": "refused",
  "refusal_reason": "INSUFFICIENT_EVIDENCE",
  "citations": []
}
```

不执行过滤放宽，不使用未过滤结果补救。

## Gateway Behavior

`LlmProviderAdapter` 增加可选 `rewrite(...)` 方法。Gateway 通过 `getattr` 调用，兼容
只实现 `generate`/`generate_stream` 的测试 Provider。

`RewriteResult` 扩展字段：

```python
original_query: str
rewritten_query: str
changed: bool
route: str
model_id: str
provider_id: Optional[str]
structured_mode: Optional[str]
extracted_filters: Dict[str, Any]
applied_filters: Dict[str, Any]
dropped_filters: List[dict]
fallback_reason: Optional[str]
validation_error: Optional[str]
context_used: Dict[str, Any]
input_tokens: int
output_tokens: int
```

`structured_mode` 取值：`json_schema`、`json_object`、`tool_use`、`prompt_json`、
`none`。

Gateway 顺序：

1. 计算确定性规则结果，作为回退基线。
2. 外部调用策略允许时，调用 Adapter 严格结构化改写。
3. 严格模式不可用时尝试弱结构化模式。
4. 有效结果直接返回；无效结果回退规则基线。
5. 策略拒绝、超时、Provider 错误均回退规则基线，不抛出阻断异常。
6. 写入 `query_rewrite` 审计：route、model、provider、tokens、latency、degraded。

超时 10 秒，最大输出 token 256。改写调用只做非流式请求。

## History Policy

`allow_chat_history` 必须真正约束外部调用：

- `true`：最近 6 条 `user`/`assistant` 消息脱敏后进入 Prompt。
- `false`：外部 LLM 只收到当前问题，不发送历史。

本地规则回退不受此限制，可以继续使用本地历史推断 product/version。

## Trace

`TraceRecord` 新增：

```python
rewrite: Mapped[str] = mapped_column(Text, default="{}")
```

SQLite/Postgres 兼容迁移增加：

```sql
ALTER TABLE retrieval_traces ADD COLUMN rewrite TEXT NOT NULL DEFAULT '{}'
```

迁移必须先检查列是否存在，重复启动保持幂等；旧 Trace 读取时按 `{}` 处理。

保存结构：

```json
{
  "original_query": "它怎么开启？",
  "rewritten_query": "Spring Boot 3.2 如何开启虚拟线程？",
  "changed": true,
  "route": "openai_chat_completions",
  "provider_id": "01JPROVIDER...",
  "model_id": "gpt-5-mini",
  "structured_mode": "json_schema",
  "extracted_filters": {"product": "spring-boot", "version_values": ["3.2"]},
  "applied_filters": {"product": "spring-boot", "version_values": ["3.2"]},
  "dropped_filters": [],
  "fallback_reason": null,
  "validation_error": null,
  "latency_ms": 820,
  "input_tokens": 450,
  "output_tokens": 24
}
```

旧 Trace 没有该字段时返回 `{}`，页面回退到现有 `rewritten_query` 展示。

`validation_error` 和 `fallback_reason` 保存稳定的原因码，例如 `invalid_json`、
`missing_field`、`unknown_facet_value`、`user_override`、`policy_denied`、
`structured_output_unsupported`、`timeout`、`provider_error`，不保存模型原始响应
或完整 Prompt。

Trace 详情新增 QueryRewrite 区块：

- 原始问题 → 改写结果。
- 来源标记：LLM 结构化、LLM JSON、规则回退。
- 应用和丢弃的过滤条件。
- provider、model、structured mode、耗时和 token。
- 回退原因和校验错误。

## SSE

`rewrite` 事件在文本变化或产生有效过滤条件时发送：

```json
{
  "original": "它怎么开启？",
  "rewritten": "Spring Boot 3.2 如何开启虚拟线程？",
  "changed": true,
  "route": "openai_chat_completions",
  "model_id": "gpt-5-mini",
  "structured_mode": "json_schema",
  "applied_filters": {"product": "spring-boot", "version_values": ["3.2"]},
  "fallback_reason": null
}
```

新增字段保持向后兼容；现有前端忽略未知字段。

## Testing

Adapter 测试：

- Chat Completions `json_schema` 请求体与 `json_object` 降级。
- Responses `text.format` 请求体与降级。
- Anthropic 强制 `tool_use` 请求体和 `tool_use` 结果解析。
- 不支持结构化参数时只降级一次。
- 无效 JSON、缺失字段、额外字段、超长文本和未知过滤值。

Gateway 测试：

- LLM 成功改写并抽取过滤条件。
- LLM 返回原文时保持原文。
- 指代有歧义时保持原问题；没有历史时不得凭空补全指代。
- 策略拒绝、超时、Provider 异常回退规则。
- `allow_chat_history=false` 时历史不进入外部请求。
- 用户显式过滤条件覆盖 LLM 值。

检索测试：

- 三种引擎对 `product`/`version_values` 的硬过滤一致。
- 字段缺失时不匹配。
- 硬过滤零结果返回 `INSUFFICIENT_EVIDENCE`，不执行放宽。

API/Trace 测试：

- `rewrite` 字段迁移和 JSON 返回。
- Trace 详情包含 extracted/applied/dropped filters。
- 旧 Trace 兼容。

前端测试：

- QueryRewrite 区块展示改写前后、来源、过滤条件和回退原因。
- 无元数据时显示兼容占位。

文档更新：

- `docs/api/api-contract.md` 的问答、Trace 和 SSE 契约。
- `docs/product/page-map.md` 的问答页与 Trace 详情说明。

## Risks

- Self-Query 硬过滤依赖文档标签质量；未标注产品/版本的文档不会参与检索。
- LLM 抽取错误会直接影响召回；通过 facets 白名单、用户优先和 Trace 可观测性控制。
- 每次问答新增一次 LLM 调用，需要关注延迟和成本。
- 官方 OpenAI 文档站当前对开发机返回 403；实现阶段以 Adapter 单测锁定请求体结构，
  如上线前可获得官方文档，再做一次核对。
