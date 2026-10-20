# Scripts

真实依赖验证脚本：

| Script | Purpose |
| --- | --- |
| `verify_retrieval_stack.py` | 验证 Elasticsearch/Qdrant staging、激活、RRF、`dual_engine` 与 `elastic_single` 对照以及私有文档过滤 |
| `verify_object_storage.py` | 验证 MinIO 上传、下载、删除和删除后不可下载 |
| `verify_rag_e2e.py` | 验证上传、入库、Chunk、问答、检索和引用链路 |

运行前先启动 `deploy/docker-compose.yml` 中的外部依赖，并使用仓库内 Python 虚拟环境：

```bash
.venv/bin/python scripts/verify_retrieval_stack.py
.venv/bin/python scripts/verify_object_storage.py
.venv/bin/python scripts/verify_rag_e2e.py
```

脚本使用本地开发端口，不修改生产配置。任何失败都会以非零退出码结束。
