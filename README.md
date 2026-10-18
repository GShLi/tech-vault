# TechVault 典阁

Private team knowledge base with permission-aware hybrid RAG retrieval.

The canonical product and architecture specification is
[`TechVault 典阁 — 团队私有技术知识库 RAG 系统.md`](./TechVault%20典阁%20—%20团队私有技术知识库%20RAG%20系统.md).

## Repository layout

```text
backend/
  app/
    core/          # configuration, identity and policies
    rag/
      domain/      # shared contracts and value objects
      chunking/    # structure-aware chunk generation
      fusion/      # RRF and candidate normalization
      evaluation/  # offline metrics and golden-set loading
      indexing/    # IndexWriter implementations
      retrieval/   # Retriever implementations
  tests/
docs/
  superpowers/
    plans/         # implementation plans
```

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
pytest
```

The target runtime is Python 3.10+. The current bootstrap must also remain
compatible with Python 3.9 so core logic can be tested in the local shell.

