# Spring Boot PDF 入库失败与恢复记录

## 原始问题

- 任务：`01M5FHSWVY1J300RS43DH77710`。
- 文档：`spring-boot-reference-3.2.12.pdf`，18,376,731 字节，977 页。
- 文档 ID：`01M5FHSWVYY48MN1KCJV7R5E1J`。
- 所属知识库：`Java 验收异常样本`（用户本次上传选择的知识库，恢复时未移动）。
- 原始失败：`CHUNK_QUALITY_FAILED`，进度 40%，worker 耗时 267.72 秒。
- 文本提取已成功：17,022 个结构节点、1,653,797 个字符，未检测到乱码；失败发生在分块阶段。

## 根因与修复

使用同一原文和真实 BGE-M3 tokenizer 复现：第 922 页 Appendix D 的 `@WebFluxTest` 表格行，正文 470 tokens，附加文件名、章节和表头后为 **527 tokens**，超过子块 **512-token** 限制。原逻辑要求表格行完整，遇到超长单行直接失败，导致整份 PDF 无法入库。

修复 `backend/app/rag/chunking/semantic.py`：优先保持整行；超长行允许按空白或标点安全边界拆分，完整保留内容与父块偏移。续行的 embedding 输入附带表头与首列行标识，计入相同 token 预算，并通过 `source_locator.table_row_split` 标记。没有提高上限、截断原文或跳过问题页。父块跨行拆分同样保留原始表格上下文。

同时修复 `backend/app/rag/ingestion/processor.py`：已知解析/模型异常保留说明、阶段和结构化位置，避免只有笼统错误码；任意底层异常的字符串不直接暴露给客户端。

## 验证

- 同一 PDF 的全量结构节点，使用真实 BGE-M3 tokenizer 分块成功：**2,278 个父块、2,722 个子块**，最大 512 tokens，P95 493 tokens，不安全切分数 0，父子文本覆盖与偏移校验通过。
- 回归覆盖完整表格、超长行、跨父块续行、表头/行标识、内容完整性、失败原因及页码保存。
- `.venv/bin/pytest -q backend/tests/chunking backend/tests/parsing backend/tests/indexing backend/tests/api/test_async_ingestion.py backend/tests/api/test_chunk_overrides.py`：**69 passed**；仅有 PyMuPDF/SWIG 弃用警告。
- `.venv/bin/pytest -q backend/tests`：**635 passed**，耗时 94.26 秒；测试日志保存在本地证据目录。
- 原任务已通过 `/ingestions/retry` 重新排队，继续使用真实模型、数据库和索引服务；未重新上传或创建替代文档。

## 恢复状态与证据

**已恢复成功。** 2026-10-22 01:17:17（Asia/Shanghai），原任务 `completed / 100%`，文档及版本均为 `active`，错误信息清空。本次完整重试耗时 927.82 秒，约 15 分 28 秒。

- 新活动索引代：`01M5FPTZ40JMFEK9FTCA3QQQNZ`。
- 本文档：2,278 个父块、2,722 个子块；ES 与 Qdrant 按文档过滤后均为 2,722 条。
- 全团队活动索引：ES、Qdrant 及 generation 声明数量均为 3,103（包含原先五份 Java 文档的 381 个子块）。
- 全部子块与父块原文偏移匹配；4 个表格子块标记为行内拆分，其中第 922 页有 2 个，续片包含表头及 `Table row: @WebFluxTest` 上下文。
- Chrome 观察原任务页自动更新至 100%，并打开文档详情与 Chunk 管理，3 个页面无 HTTP 错误或 JavaScript 异常。截图与页面记录见 `ui-*.png`、`browser-results.json`。
- 最终数据库/ES/Qdrant 检查见 `final-verification.json`，综合检查 `passed: true`。

性能观察：本次分块阶段产生 24,553 次成功的 `/tokenize` 请求，页面进度在阶段内固定显示 40% / 60%。大文档仍需改进 tokenizer 调用批量化、连接复用和细粒度进度；本次先修复确定的失败原因，没有把本机单次恢复当作生产容量验收。

界面观察：任务页通过 SSE 更新为完成后，“更新时间”仍显示页面加载时的值（截图为 01:06），没有同步终态时间；本轮未修改该显示逻辑，真实完成时间以上述 worker 与数据库结果为准。

本地证据目录：`artifacts/ingestion-01M5FHSWVY1J300RS43DH77710/`，含原始异常定位、token 计数、完整分块质量结果、恢复状态和 worker 日志。原文及提取内容不纳入 Git。
