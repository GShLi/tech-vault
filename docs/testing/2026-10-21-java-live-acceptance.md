# Java 知识库真实环境验收记录

## 验收结论

后续修复更新：JAVA-QA-004 的分页 500 已修复并在真实页面复测通过；JAVA-QA-005 的批量请求 ID 长度校验已修复并通过 API 回归。详见文末修复记录；下面保留首次验收的原始发现。

**当前不满足生产上线条件。** 五份真实 Java 文档已全部入库，生成 323 个父块、381 个子块；Elasticsearch 与 Qdrant 均有 381 条子块记录，父块仅存于数据库快照。真实检索能够命中相关文档，但默认双引擎融合丢失父块关联，分页、批量管理、任务排队及供应商自检存在阻塞问题。详见下面的逐项复现记录。

## 范围与环境

- 日期：2026-10-21；执行用户：`double8799@163.com`，基础研发团队 leader。
- 地址：`http://127.0.0.1:5173`；API：`http://127.0.0.1:8000`。
- 主知识库：`Java 官方文档 · 生产验收 2026-10-21`，ID `01M5FDPH95JJZZQ4QG9YVM3B0T`。
- 异常样本知识库：`Java 验收异常样本`，ID `01M5FE56B70AQVMBVZS7CHF4ED`。
- 独立 PostgreSQL 数据库：`techvault_java_acceptance_20261021`。保留原有账号、团队权限和供应商配置；未删除旧库。
- 真实 PostgreSQL、Redis、MinIO、Elasticsearch、Qdrant，Celery threads worker（并发 2），本地 BGE-M3 与 bge-reranker-v2-m3；未用模拟向量替代入库。
- Redis DB 10、MinIO bucket `techvault-java-acceptance`、上传目录 `data/java-acceptance/uploads/`。
- 本地环境使用 development 配置及 HTTP；它不是生产部署。线程 worker 也不能替代生产 Linux prefork 的终止/故障恢复验收。
- 本轮新增测试脚本与记录，未修改应用行为。原工作区已有的大量实现变更不属于本轮新增修改。

## 文档与来源

| 文件 | 官方来源 | 处理方式 |
| --- | --- | --- |
| java-21-language-updates.pdf | https://docs.oracle.com/en/java/javase/21/language/java-se-language-updates.pdf | 原始 PDF |
| jep-444-virtual-threads.md | https://openjdk.org/jeps/444 | HTML 转 Markdown，保留代码块 |
| jep-395-records.md | https://openjdk.org/jeps/395 | HTML 转 Markdown，保留代码块 |
| jep-409-sealed-classes.txt | https://openjdk.org/jeps/409 | HTML 转文本 |
| java-records-derived-test.docx | https://openjdk.org/jeps/395 | 明确标注为测试转换版，附加独立标记的代码和表格样本 |

来源、下载时间和 SHA-256 见 `data/java-acceptance/corpus/manifest.json`。
官方材料用于系统内导入测试；来源文件不纳入 Git。

## 已完成检查

- 真实账号登录、刷新会话、创建知识库、五份文档异步上传成功。
- 所有原文通过普通下载和 MinIO 签名下载回读，SHA-256 均一致。
- 匿名访问拒绝；无知识库成员资格的同团队 viewer 无法读取知识库、文档、下载地址、Chunk、入库任务或他人聊天。
- 不支持扩展名、MIME 不匹配、路径穿越文件名返回 400。
- 空文件、损坏 PDF、损坏 DOCX、扫描 PDF 在串行重试后分别返回正确的不可重试错误码。
- 旧资源版本的写请求返回 409；50 次只读请求、并发 5，全部 200，P50 16.18 ms、P95 23.41 ms。该小规模检查不代表容量验收。
- 浏览器登录、知识库和任务列表可访问，无 JavaScript 运行时异常；最终五个文档详情页均因分块接口 500 显示错误，不能计为页面验收通过。初次和最终截图分别保留。
- 使用真实 BGE-M3 tokenizer 检查五份文档：父子偏移全匹配、ID 唯一、没有超预算或 unsafe split。
- 核对 active generation 的 ES/Qdrant/数据库记录一致；回滚至 360 个子块的上一代，再恢复 381 个子块的最新代，均成功。
- 三个有标准答案的问题分别使用双引擎及 Elasticsearch 单引擎检索，六次均在前十命中预期来源；命中检查不代表完整回答质量通过。

| 文件 | 父块 | 子块 | 父块最大 tokens | 子块最大 tokens |
| --- | ---: | ---: | ---: | ---: |
| Java 21 PDF | 182 | 196 | 854 | 508 |
| Virtual Threads | 56 | 67 | 764 | 495 |
| Records Markdown | 73 | 78 | 779 | 471 |
| Sealed Classes TXT | 5 | 19 | 1383 | 480 |
| Records DOCX | 7 | 21 | 1397 | 477 |

## 真实问答与引用结果

使用团队已有 DeepSeek / `deepseek-flash` 配置，预热真实 embedding 与 reranker 后串行执行；下表为单次实测，不是 P95 或生产 SLA。

| 场景 | 结果 | 客户端耗时 |
| --- | --- | ---: |
| JEP 444 虚拟线程是否应池化 | 回答不应池化，说明成本和每任务一个线程，给出引用 | 18.37 秒 |
| Record 自动成员及 Point 访问器 | 回答 `x()` / `y()`、构造器及 equals/hashCode/toString，给出引用 | 18.32 秒 |
| sealed class 子类修饰符 | 回答 final / sealed / non-sealed，给出引用 | 17.54 秒 |
| 文档是否包含公司薪酬预算 | 明确没有依据，没有编造金额 | 15.98 秒 |
| 直接追问预算准确数值 | 明确拒绝猜测，没有编造金额 | 15.65 秒 |
| SSE 虚拟线程问答 | meta、rewrite、93 个 delta、4 个 citation、1 个 done；无 error | 16.86 秒 |

前四条回答的行内引用均匹配返回的 citation ID，12 次引用分块详情读取均为 200，Trace 详情均可读取。内容拒绝猜测的两条回答，API 状态仍为 `completed`，不能据此声称结构化 `refused` 状态验收通过。默认双引擎 Trace 的父块上下文数为 0，见 JAVA-QA-009。模型重排阶段约 10.9–11.4 秒，是当前本机延迟的主要组成部分。

综合结果：导入与索引一致性、原文回读、已覆盖的权限拒绝、基础问答内容及 SSE 通过；分页/批量管理、排队可靠性、父块上下文及部分可观测性失败。完整生产验收不通过。

## 问题清单

### JAVA-QA-001 / P1：readiness 未检查关键依赖

复现：Embedding 服务未启动，访问 `GET /api/v1/ready`。
实际：200 / `ready`；同一环境真实入库报 `TOKENIZER_UNAVAILABLE`。
请求 ID：`req_01M5FDPHA2WFY6NKPWNMZ3CZ1J`。
影响：服务可被错误纳入负载均衡，文档导入进入失败与重试循环。
位置：`backend/app/api/v1/health.py`。
建议：区分 liveness/readiness；检查必需依赖、模型加载状态及工作队列消费者。

### JAVA-QA-002 / P1：团队锁竞争耗尽业务任务重试

复现：一个任务在 tokenizer 冷启动中持有团队锁，同时上传另外四份文档。
实际：其他任务报 `INGESTION_BUSY`，每 30 秒重试，共三次后出现 `MaxRetriesExceededError`，任务停留失败状态。
影响：正常批量导入会因等待锁而失败；异常样本解析也被同团队长任务阻塞。
证据：`worker.log` 22:31–22:36；运行 ID `01M5FDYWG2KQBDTNSW1X07GH9W` 等。
位置：`rag/ingestion/leases.py`、`workers/tasks.py:ingest_document`。
建议：锁竞争采用独立排队/延后机制，不消耗处理故障的重试预算；完成后自动推进待处理文档。

### JAVA-QA-003 / P2：重试中的任务和文档状态不一致

复现：模型不可用导致失败，等待 Celery 自动重试。
实际：任务显示 `running/chunking`，仍带旧 `TOKENIZER_UNAVAILABLE`；文档显示失败；版本显示构建中；页面仍展示重试按钮。
证据：`browser-results.json` 与 `ui-tasks.png`、`ui-jep-409-sealed-classes-txt.png`。
位置：`rag/ingestion/processor.py`、`frontend/src/views/TasksView.vue`、`TaskDetailView.vue`。
建议：重试开始时同步清理旧错误并更新文档/版本状态；运行中的任务不展示可执行重试操作。

### JAVA-QA-004 / P1：新 Chunk ID 与分页游标不兼容

复现：成功入库后请求 `GET /chunks?team_id=...&document_id=...&limit=1`。
实际：500 / `INTERNAL_ERROR`，后端 `ValueError: cursor id is invalid`。
请求 ID：`req_01M5FF0FFYYWVGBMDFY3M7S4DX`。
根因：`api/pagination.py` 只接受 ULID 或 `chk_`，新分块生成 `chd_` / `par_`。
影响：需要下一页时接口失败；真实 PDF 196 个子块，页面无法正常分页。最终浏览器五个文档详情页均请求 `GET /docs/chunks?...&limit=20` 并收到 500，整页只显示错误提示（该接口还包含父块）。
页面证据：`browser-final-results.json`、`ui-final-java-21-language-updates-pdf.png`；请求 ID `req_01M5FFM52FSDX2RN65633EQJNW`。

### JAVA-QA-005 / P1：批量 Chunk 管理仍限制旧 ID 长度

复现：向 `POST /chunks/bulk` 提交真实新子块 ID，action=`disable`。
实际：422，`String should have at most 26 characters`；新子块 ID 长度为 68。
请求 ID：`req_01M5FF1HFT2HJET88546J55TBY`。
位置：`api/v1/chunks.py:ChunkBulkBody.chunk_ids` 使用 `Identifier`。
影响：正常生成的 Chunk 无法通过批量管理接口启用/禁用。

### JAVA-QA-006 / P1（当前本机推理环境）：并发推理导致 MPS 进程崩溃

复现：BGE-M3 正在批量入库时发起真实问答，进程同时处理推理请求。
实际：22:46:09 模型进程退出码 134，原生断言 `_status < MTLCommandBufferStatusCommitted`，DOCX 入库出现 `EMBEDDING_UNAVAILABLE` / `TOKENIZER_UNAVAILABLE`。
证据：`embedding-warm.log`；先前 active generation 仍有 360 个子块，失败 staging generation 未发布。
范围：macOS MPS，不能推断 Linux CPU/CUDA 一定复现。恢复服务后采用串行负载重试。
建议：显式配置推理设备、请求并发及模型初始化锁；在目标部署硬件上执行并发压力与自动恢复验证。

### JAVA-QA-007 / P1：当前配置的问答供应商未通过真实调用

复现：选择已有 ClinePass 供应商及其配置模型，对已入库 Java 文档提问。
实际：四个问答请求均返回 502 / `MODEL_RESPONSE_INVALID`，提示 Chat Completions response did not contain choices。
示例请求 ID：`req_01M5FET5Z4V1N8MSCRKXMX8RDK`。
影响：ClinePass 当前配置不能提供问答。另行选择团队已有 DeepSeek 配置后真实回答成功，因此该问题限于此供应商配置或协议链路。
性质：供应商配置或协议兼容性问题，尚不能仅凭 502 判定哪一端有错。

### JAVA-QA-008 / P1：供应商测试接口无条件返回成功

复现：`POST /providers/test`，提供不存在的 provider_id=`00000000000000000000000000`。
实际：200，返回该 ID 及 `status: ok`。
请求 ID：`req_01M5FEZGYPPZ2PGWACWKV4KH6R`。
位置：`api/v1/model_policy.py:test_provider` 仅检查团队成员身份。
影响：供应商配置不可用或不存在也被标记测试成功，误导上线判断。
建议：校验供应商存在性与可见范围，执行受限的真实协议请求，返回明确错误。

### JAVA-QA-009 / P1：默认双引擎融合丢失父块及索引代信息

复现：在真实 ES/Qdrant 索引上分别询问虚拟线程、Record 访问器、sealed 子类修饰符，检查融合前后候选及父块补全。
实际：BM25 和 dense 各 50 个候选均有父块关联；双引擎融合后的 50 个候选关联全部丢失，补全父块数、证据子块数均为 0。三个问题都复现。
对照：Elasticsearch 单引擎保留 50 个关联，分别补全 42、44、36 个父块，并保留 50 个证据子块。
位置：`rag/retrieval/engines.py:DualEngineRetriever.search` 重建 `RetrievedChunk` 时未传递 `parent_chunk_id`、`index_generation`。
影响：默认配置下“子块检索、父块上下文”的设计未真正生效，代际追踪也不完整。
证据：`retrieval-results.json`；建议通过统一的候选转换函数保留元数据，并增加真实融合到上下文的回归覆盖。

### JAVA-QA-010 / P2：Trace 清理逻辑删除证据子块关联

复现：调用实际 `sanitize_trace_context`，输入包含 `chunk_id`、`evidence_chunk_ids` 和 `index_generation`。
实际：输出仅剩 `chunk_id`；数据库写入事件和 API 读取使用该清理逻辑。
位置：`db/models.py:_TRACE_LOCATION_FIELDS` 未纳入新证据字段。
影响：即使单引擎已补全父块，审计中仍无法保留父块对应的检索证据子块。
证据：`component-findings.json`。此项为真实组件级复现；没有把尚未跑通的父块问答审计声明为端到端通过。

### JAVA-QA-011 / P2：重排失败静默降级，调用方无法识别

复现：实际 `RerankerClient` 指向本机未监听端口后执行评分。
实际：异常被捕获，返回词汇重叠分数，不返回降级状态；`component-findings.json` 验证与词汇回退完全一致。模型尚在加载时，真实 DeepSeek 问答也曾耗时约 34 秒却返回 `degraded: false`。
位置：`rag/rerank/service.py:RerankerClient.score`。
影响：监控和验收无法区分模型重排与词汇回退，质量下降被正常成功指标掩盖。
建议：显式返回重排来源、失败原因和降级标记，并纳入 Trace 与告警。

### JAVA-QA-012 / P2：流式响应总耗时重复累计

复现：正常完成一次真实 SSE 问答，记录客户端单调时钟与 `done.latency_ms`。
实际：客户端从请求至流结束为 16,855.77 ms，服务端返回 30,932 ms。
位置：`api/v1/chats.py:effective_stage_latency` 同时收集阶段耗时与对应 gateway 耗时，`done` 对全部值求和；重写、embedding、rerank 被重复计入，检索总计与子阶段也有重叠。
影响：流式性能指标失真，不能直接用于延迟 SLA 或与非流式请求比较。
建议：端到端耗时单独使用单调时钟，阶段指标分别展示，不累加嵌套时间。证据：`sse-results.json`。

### JAVA-QA-013 / P2：知识库详情的最近任务混入其他知识库任务

复现：主 Java 知识库五份文档全部启用后，查看详情页“最近任务”。
实际：显示四条来自“Java 验收异常样本”知识库的失败任务，例如 `01M5FE6C2J0DFYJ2260803MS8Q`；用户容易误认为当前知识库导入仍然失败。
位置：`frontend/src/views/KnowledgeBaseDetailView.vue` 获取团队任务后直接取前五条，没有限定当前知识库。
证据：`ui-final-knowledge-base.png`，对应任务所属异常知识库 ID 可在 `state.json` 中核对。
建议：按当前知识库过滤任务，并在任务展示中明确文档名称；本次未发现因此越过团队权限边界。

## 环境准备发现与范围限制

- 旧库缺少 `documents.mime_type`、`chunks.chunk_level`、`document_versions.parse_metadata`；本轮依照开发期全新建库约定使用独立库。生产升级仍需要明确迁移或重建方案。
- 初始环境没有模型服务和 BGE-M3 权重；下载并校验 2,271,145,830 字节官方权重后，真实 `/tokenize` 和 `/embed` 成功，向量维度 1024。冷启动耗时不能作为正常推理延迟。
- 另下载并校验 2,271,071,852 字节 bge-reranker-v2-m3 权重；`/rerank` 实际返回区分相关/无关文档的分数，后续六条问答请求均使用已预热服务。
- 独立 MinIO bucket 创建前，上传正确返回 `OBJECT_STORAGE_UNAVAILABLE`；创建后恢复。这是测试环境初始化步骤，不记作应用缺陷。
- 初始测试脚本误调用不存在的 `/models`，后改为从 `/providers` 获取模型；该 404 不记作产品缺陷。
- `local_only` 策略正确拒绝外部回答。仅将本次公开 Java 文档知识库切换为团队已允许的 `external_allowed`；未修改部署/团队准入配置。
- 对已结束任务的取消请求返回 409，符合接口约定，不记作缺陷。
- HTML 转换样本仍包含部分官网导航文本；本轮没有静默清洗后重建，来源和导入内容均可通过 manifest 校验。
- 尚未完成生产容量、长时间稳定性、Linux CPU/CUDA 并发推理、备份恢复、跨团队完整权限矩阵及 TLS/网关配置验收。Chunk 批量操作及父块问答完整链路被已记录缺陷阻塞。

## 复现与证据

```bash
.venv/bin/python scripts/prepare_java_acceptance_corpus.py
.venv/bin/python scripts/verify_java_knowledge_base.py --phase setup --email '<account>'
.venv/bin/python scripts/verify_java_knowledge_base.py --phase upload --email '<account>'
.venv/bin/python scripts/verify_java_knowledge_base.py --phase inspect --email '<account>'
.venv/bin/python scripts/verify_java_knowledge_base.py --phase query --email '<account>' --provider-id '<approved-provider-id>'
```

脚本交互式读取密码，不把密码或访问令牌写入结果。
仅在主动停掉模型服务进行故障检查时，给 setup 添加 `--expect-embedding-unavailable`；常规 setup 预期 readiness 为 200。query 的 HTTP 成功与引用完整性分别记录，答案语义仍须人工核对。脚本不会自动修改知识库外发策略，也不会代替完整生产测试。

本地原始证据目录：`artifacts/java-acceptance-2026-10-21/`，包括 `results.jsonl`、`parsing.json`、`actual-token-checks.json`、`isolation-results.json`、`index-consistency.json`、`retrieval-results.json`、`component-findings.json`、`answer-quality.json`、`sse-results.json`、`final-summary.json`、浏览器截图及服务日志。初始故障、恢复过程和最终结果全部保留，不能直接把 JSONL 中的 HTTP PASS 条数当作整体通过率。
`runtime.json` 与 `isolation-user.json` 为 0600 私有配置，包含秘密值，禁止提交或转发。

验收状态：本轮真实环境功能与故障检查已完成，共记录 13 项问题（8 项 P1、5 项 P2，其中并发崩溃限于本机 MPS，供应商失败限于当前 ClinePass 配置）。问题未修复，生产准入不通过；修复后须复测，并补齐上述尚未覆盖的部署验收项。

## 后续修复：Chunk 管理与文档详情 500（2026-10-21）

- 用户再次报告 Java 官方文档知识库的 Chunk 管理报错；修复前真实请求返回 500，request_id=`req_01M5FHKB7C4P9ADVHYY4B219DY`。
- JAVA-QA-004：分页游标改为识别当前 `chd_` / `par_` 加 64 位小写十六进制摘要。按用户要求移除旧 `chk_` 支持；其他资源仍采用 ULID。没有清空或重新导入 Java 文档。
- JAVA-QA-005：`ChunkBulkBody.chunk_ids` 使用已有的 68 字符 `ChunkIdentifier`，同步 OpenAPI 文档；父块仍禁止编辑。
- 新增回归先复现 6 个失败，再修复：覆盖父/子块游标、旧格式拒绝、异常摘要、两种列表的全量翻页、子块批量禁用/启用及父块拒绝。
- 命令：`.venv/bin/pytest -q backend/tests/api/test_pagination.py backend/tests/api/test_chunk_overrides.py backend/tests/api/test_list_pagination_contract.py backend/tests/docs/test_openapi.py`；结果 **69 passed**。
- 重启本地 API 后，真实五份文档的 `/chunks` 与 `/docs/chunks` 共遍历 **59 页**，全部 200，分别完整返回 **381 个子块 / 704 个父子块**，无重复；证据 `chunk-fix-api-results.json`。
- Chrome 实测知识库、任务页、五个文档详情、五个 Chunk 管理入口，共 **12 个页面**；所有可见的 Chunk“加载更多”均成功，未出现 HTTP 错误或 JavaScript 异常。证据 `browser-chunk-fix-results.json`、`ui-chunk-fix-*.png`。
- 批量启停与父块保护使用测试数据库验证；本次真实 Java 知识库复测仅做读取，没有修改分块状态。其他已登记问题仍待处理，本次修复不等于整体生产验收通过。
