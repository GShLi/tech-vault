# Required LLM Provider for Q&A

Date: 2026-10-20
Status: Approved design, pending implementation

## Goal

问答回答必须由用户明确选择的、已配置的 LLM 供应商和模型生成。系统不再使用
`ExtractiveLocalGenerator`，也不在没有可用供应商时自动拼接检索片段作为回答。

聊天页必须选择供应商和模型；任一未选择时，消息发送按钮保持灰色不可用。后端同时
校验请求中的供应商和模型，不能只依赖前端禁用按钮。

## Supported Provider Formats

供应商配置继续支持三种上游格式：

- `openai_responses`: `POST {base_url}/v1/responses`
- `openai_chat_completions`: `POST {base_url}/v1/chat/completions`
- `anthropic_messages`: `POST {base_url}/v1/messages`

模型列表继续通过 `/providers/models` 和 `/admin/providers/models` 获取。供应商 API Key
只写不读，响应只返回掩码和更新时间。

## User Flow

1. 用户进入问答页。
2. 前端加载当前团队知识库、有效模型策略和可用供应商。
3. 用户在工具栏选择知识库、供应商和模型。
4. 供应商或模型未选择时，发送按钮保持禁用。
5. 发送问题时，请求体包含 `provider_id` 和 `model_id`。
6. 后端校验供应商、模型、API Key、团队权限和模型策略。
7. 校验通过后，由对应供应商 Adapter 执行流式或非流式生成。
8. 返回真实 `provider_id`、`model_id`、model route、耗时和降级状态。

默认不自动选择供应商或模型。用户必须显式选择后才能发送。

## Backend Architecture

### Provider Adapter

新增统一接口：

```python
class LlmProviderAdapter:
    provider_id: str
    model_id: str
    route: str

    def generate(self, *, question, chunks, max_chunks) -> AnswerResult: ...
    def generate_stream(self, *, question, chunks, max_chunks) -> AnswerStream: ...
```

三个实现：

- `OpenAIResponsesAdapter`
- `OpenAIChatCompletionsAdapter`
- `AnthropicMessagesAdapter`

Adapter 负责构造 Prompt、认证、请求、响应解析、流式增量和错误归一化。业务层只使用
`AnswerResult` 和 `AnswerStream`，不直接处理供应商响应格式。

### Provider Resolution

新增问答专用解析器：

1. 读取请求的 `provider_id` 和 `model_id`。
2. 查供应商，要求状态为 `active`。
3. 要求供应商属于当前团队，或为平台级供应商。
4. 要求模型 ID 在供应商 `model_ids` 中。
5. 要求供应商存在可解密的 API Key。
6. 要求供应商 ID 在有效模型策略的 `allowed_provider_ids` 中。
7. 要求当前数据分类允许外部调用。

任何一项失败都返回结构化错误，不进行抽取式回退。

### Gateway

`LlmGateway` 保留策略、脱敏、审计和路由职责，但移除：

- `ExtractiveLocalGenerator` 依赖。
- 默认本地答案生成器。
- 外部调用失败后的抽取式回答回退。

答案生成必须拿到显式 Adapter。无 Adapter 时返回 `MODEL_UNAVAILABLE`。

## API Changes

`POST /chats/ask` 请求新增必填字段：

```json
{
  "provider_id": "01JPROVIDER000000000000001",
  "model_id": "gpt-5-mini"
}
```

供应商响应新增只读字段：

- `has_api_key`: boolean
- `api_key_masked`: string
- `api_key_updated_at`: datetime | null

聊天页只展示：

- `status=active`
- `has_api_key=true`
- 被当前模型策略允许
- `model_ids` 非空

## Error Semantics

- 未选择供应商或模型：`400 INVALID_ARGUMENT`
- 供应商不存在或已停用：`404 NOT_FOUND` 或 `409 RESOURCE_STATE_CONFLICT`
- 模型不在供应商模型列表：`400 INVALID_ARGUMENT`
- 缺少可用 API Key：`409 RESOURCE_STATE_CONFLICT`
- 供应商不在策略允许范围：`403 POLICY_DENIED`
- 上游认证失败：`502 MODEL_AUTH_FAILED`
- 上游超时或不可用：`503 MODEL_UNAVAILABLE`
- 响应格式无效：`502 MODEL_RESPONSE_INVALID`

不提供静默回退。

## Trace and Audit

每次问答必须记录真实的：

- `provider_id`
- `model_id`
- 上游格式
- route
- data classification
- 输入/输出 token 估算或供应商返回值
- 延迟
- 错误码
- degraded 状态

API Key、请求认证头和完整上游响应不得写入 Trace 或日志。

## Documentation Changes

- 删除 API 契约中的 `local-extractive` 和 `local_extractive_fallback` 示例。
- 明确 `provider_id` 和 `model_id` 为问答必填字段。
- 明确没有可用供应商时返回 `MODEL_UNAVAILABLE`。
- 从主设计文档和 page map 中移除“自动本地抽取式回答”的歧义。

## Testing

后端：

- 三种 Adapter 的非流式响应解析。
- 三种 Adapter 的流式文本增量解析。
- API Key 解密和认证头。
- 供应商/模型/策略校验。
- 未选择供应商、模型不匹配、无 Key、停用供应商等错误路径。
- 确认代码中不再引用 `ExtractiveLocalGenerator`。

前端：

- 供应商和模型选择器。
- 未选择任一项时发送按钮禁用。
- 切换团队或知识库时重新过滤可用供应商。
- `/chats/ask` 请求包含 `provider_id` 和 `model_id`。
- 上游失败展示真实错误，不显示抽取式回答。

端到端：

- 使用模拟 OpenAI Responses、Chat Completions 和 Anthropic Messages 服务完成问答。
- 确认 Trace 中记录真实供应商和模型。
- 确认无供应商时无法发送，绕过前端直接请求也返回错误。

## Out of Scope

- 自动多供应商故障切换。
- 用户级默认模型。
- 模型价格实时同步。
- LLM-as-Judge 评测。
