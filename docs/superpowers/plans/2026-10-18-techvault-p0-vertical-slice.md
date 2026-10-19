# TechVault P0 Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested, runnable first vertical slice of TechVault that ingests representative documents, produces structure-aware chunks, applies permission-safe retrieval filters, runs both retrieval engine modes behind one contract, returns cited or refused answers, and records reproducible retrieval traces.

**Architecture:** A Python backend exposes one RAG application service. Shared domain contracts are independent of Elasticsearch, Qdrant, LLM providers, and the web framework. Storage and model integrations implement narrow ports, allowing in-memory tests now and production adapters later. Evaluation runs from the same trace and candidate contracts used by the live pipeline.

**Tech Stack:** Python 3.10+ target, Python 3.9-compatible core tests, FastAPI, Pydantic, SQLAlchemy, Celery, PostgreSQL, MinIO, Elasticsearch 8.x, Qdrant, BGE-M3, bge-reranker-v2-m3, pytest.

**Spec:** `TechVault 典阁 — 团队私有技术知识库 RAG 系统.md`

## Global Constraints

- Permission leakage must be zero; every retrieval request must carry an explicit authorization scope.
- Never retrieve first and filter unauthorized results in the application layer.
- External LLM calls are disabled by default; all model calls go through `LlmGateway`.
- A/B retrieval modes share parsing, chunk IDs, embeddings, reranking, context assembly, and evaluation.
- `dual_engine` and `elastic_single` are selected by configuration, never by branching throughout the domain.
- Index writes use staging generations, validation, activation, and delayed cleanup.
- No full-document text, ACL, internal paths, or real chunk IDs are sent to external models.
- Every answer trace records the engine mode, filters, candidates, fusion, rerank, final context, model metadata, latency, and degradation state.
- Default external model policy is `local_only`.

---

### Task 1: Shared Domain Contracts

**Files:**
- Create: `backend/app/rag/domain/models.py`
- Create: `backend/app/rag/domain/ports.py`
- Test: `backend/tests/domain/test_models.py`

**Interfaces:**
- Produces: `DataClassification`, `Visibility`, `DocumentStatus`, `ChunkStatus`, `RetrievalFilters`, `SearchRequest`, `RetrievedChunk`, `SearchResult`, `AuthorizationContext`, `Retriever`, `IndexWriter`.
- Later tasks construct these types and must not invent alternate field names.

- [x] **Step 1: Write the failing test**

```python
def test_search_request_defaults_are_stable():
    request = SearchRequest(
        query="Spring Boot 3.2 virtual threads",
        rewritten_query=None,
        query_vector=[0.1, 0.2],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-a",
        ),
    )
    assert request.bm25_top_k == 50
    assert request.rrf_k == 60
    assert request.final_top_n == 10
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/domain/test_models.py -v`

Expected: FAIL because `SearchRequest` is not defined.

- [x] **Step 3: Implement immutable dataclasses and protocol ports**

Use `@dataclass(frozen=True)` for request/result values and `Protocol` for ports. Use `typing.Optional`, `typing.Tuple`, and `typing.List` in public annotations so the bootstrap runs on Python 3.9.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/domain/test_models.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/domain backend/tests/domain
git commit -m "feat: add shared RAG domain contracts"
```

### Task 2: Permission-Safe Retrieval Filters

**Files:**
- Create: `backend/app/core/authorization.py`
- Test: `backend/tests/core/test_authorization.py`

**Interfaces:**
- Consumes: `AuthorizationContext`, `RetrievalFilters`.
- Produces: `build_retrieval_filters(context, requested_filters) -> RetrievalFilters`; `assert_may_view_chunk(context, chunk) -> None`.

- [x] **Step 1: Write the failing test**

```python
def test_private_document_is_not_visible_to_another_member():
    context = AuthorizationContext(
        user_id="user-b",
        team_ids=("team-a",),
        knowledge_base_ids=("kb-a",),
        role=Role.MEMBER,
    )
    with pytest.raises(PermissionError):
        assert_may_view_document(
            context,
            owner_user_id="user-a",
            team_id="team-a",
            visibility=Visibility.PRIVATE,
        )
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/core/test_authorization.py -v`

Expected: FAIL because authorization functions do not exist.

- [x] **Step 3: Implement default-deny authorization**

Allow team-shared documents only when the team is in the context. Allow private documents only to the owner or an explicit grant. Do not grant access to team administrators by default.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/core/test_authorization.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/core/authorization.py backend/tests/core/test_authorization.py
git commit -m "feat: enforce default-deny document authorization"
```

### Task 3: Structure-Aware Chunking and Stable IDs

**Files:**
- Create: `backend/app/rag/chunking/markdown.py`
- Create: `backend/app/rag/chunking/identity.py`
- Test: `backend/tests/chunking/test_markdown.py`

**Interfaces:**
- Consumes: document version ID, source path, Markdown text, and a chunk size limit.
- Produces: `chunk_markdown(document_version_id, source_path, content, max_chars=1200) -> List[Chunk]`; stable `chunk_id` and `logical_chunk_key`.

- [x] **Step 1: Write the failing test**

```python
def test_markdown_chunks_preserve_heading_path():
    chunks = chunk_markdown(
        document_version_id="dv-1",
        source_path="docs/spring.md",
        content="# Spring\n\nIntro\n\n## Virtual Threads\n\nUse virtual threads.",
    )
    assert chunks[-1].heading_path == ("Spring", "Virtual Threads")
    assert chunks[-1].logical_chunk_key.startswith("docs/spring.md#")
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/chunking/test_markdown.py -v`

Expected: FAIL because `chunk_markdown` is not defined.

- [x] **Step 3: Implement heading-aware chunks**

Split at Markdown headings while preserving heading paths. Split oversized sections at paragraph boundaries. Compute the content hash from normalized text. Build `chunk_id` from document version, source path, structural path, and content hash. Build `logical_chunk_key` without the content hash.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/chunking/test_markdown.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/chunking backend/tests/chunking
git commit -m "feat: add structure-aware markdown chunking"
```

### Task 4: RRF Fusion and Candidate Normalization

**Files:**
- Create: `backend/app/rag/fusion/rrf.py`
- Test: `backend/tests/fusion/test_rrf.py`

**Interfaces:**
- Consumes: ordered lists of chunk IDs from BM25 and Dense retrieval.
- Produces: `reciprocal_rank_fusion(bm25_ids, dense_ids, k=60, bm25_weight=1.0, dense_weight=1.0) -> List[FusedCandidate]`.

- [x] **Step 1: Write the failing test**

```python
def test_rrf_deduplicates_and_prefers_candidates_seen_in_both_lists():
    fused = reciprocal_rank_fusion(
        bm25_ids=["a", "b", "c"],
        dense_ids=["b", "a", "d"],
        k=60,
    )
    assert [candidate.chunk_id for candidate in fused[:2]] == ["a", "b"]
    assert len(fused) == 4
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/fusion/test_rrf.py -v`

Expected: FAIL because `reciprocal_rank_fusion` is not defined.

- [x] **Step 3: Implement weighted RRF**

Use `weight / (k + rank)` with rank starting at 1. Merge duplicate chunk IDs. Preserve each candidate's BM25 and Dense rank and the sorted fused score.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/fusion/test_rrf.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/fusion backend/tests/fusion
git commit -m "feat: add weighted reciprocal rank fusion"
```

### Task 5: Retrieval Port and In-Memory Verification Adapter

**Files:**
- Create: `backend/app/rag/retrieval/in_memory.py`
- Test: `backend/tests/retrieval/test_in_memory.py`

**Interfaces:**
- Consumes: `SearchRequest`, `RetrievedChunk`, `AuthorizationContext`.
- Produces: `InMemoryRetriever` implementing `Retriever.search`.

- [x] **Step 1: Write the failing test**

```python
async def test_in_memory_retriever_applies_permission_filters():
    retriever = InMemoryRetriever(chunks=[private_chunk, shared_chunk])
    result = await retriever.search(request_for_user_b)
    assert [chunk.chunk_id for chunk in result.chunks] == [shared_chunk.chunk_id]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/retrieval/test_in_memory.py -v`

Expected: FAIL because `InMemoryRetriever` is not defined.

- [x] **Step 3: Implement the adapter**

Filter before ranking. Return a `SearchResult` with stage latency, `trace_id`, and `degraded=False`. The adapter is for tests and local development only, not a production fallback.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/retrieval/test_in_memory.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/retrieval backend/tests/retrieval
git commit -m "feat: add permission-safe in-memory retriever"
```

### Task 6: Offline Evaluation Metrics

**Files:**
- Create: `backend/app/rag/evaluation/metrics.py`
- Test: `backend/tests/evaluation/test_metrics.py`

**Interfaces:**
- Consumes: ranked chunk IDs and relevance judgments.
- Produces: `recall_at_k`, `mrr`, `ndcg_at_k`.

- [x] **Step 1: Write the failing test**

```python
def test_recall_at_k_counts_relevant_documents_in_the_top_k():
    assert recall_at_k(["a", "b", "c"], {"b", "z"}, k=2) == 0.5
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/evaluation/test_metrics.py -v`

Expected: FAIL because `recall_at_k` is not defined.

- [x] **Step 3: Implement deterministic retrieval metrics**

Keep the metrics independent of model response quality. For nDCG, accept graded relevance as `Mapping[str, float]` and use binary relevance when a set is supplied.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/evaluation/test_metrics.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/evaluation backend/tests/evaluation
git commit -m "feat: add offline retrieval metrics"
```

### Task 7: Golden Set Loader and Seed Dataset

**Files:**
- Create: `backend/app/rag/evaluation/golden_set.py`
- Create: `backend/tests/fixtures/golden_set.seed.jsonl`
- Test: `backend/tests/evaluation/test_golden_set.py`

**Interfaces:**
- Consumes: JSONL rows with `query_id`, `query_type`, `query`, `filters`, `relevant_chunk_ids`.
- Produces: `load_golden_set(path) -> List[GoldenCase]` and validation errors for duplicate IDs or missing relevance.

- [x] **Step 1: Write the failing test**

```python
def test_golden_set_rejects_duplicate_query_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"query_id":"q1","query_type":"concept","query":"a","relevant_chunk_ids":["c1"]}\n'
        '{"query_id":"q1","query_type":"concept","query":"b","relevant_chunk_ids":["c2"]}\n'
    )
    with pytest.raises(ValueError, match="duplicate query_id"):
        load_golden_set(path)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/evaluation/test_golden_set.py -v`

Expected: FAIL because `load_golden_set` is not defined.

- [x] **Step 3: Implement loader and a small representative seed set**

Include at least one case for each required class: exact identifier, concept, cross-language, version filter, follow-up, insufficient evidence, and permission negative.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/evaluation/test_golden_set.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/rag/evaluation backend/tests/evaluation backend/tests/fixtures
git commit -m "feat: add golden set loading and seed cases"
```

### Task 8: LLM Policy Gateway Contract

**Files:**
- Create: `backend/app/core/llm_policy.py`
- Test: `backend/tests/core/test_llm_policy.py`

**Interfaces:**
- Consumes: deployment/team/knowledge-base policy, `DataClassification`, and request preferences.
- Produces: `resolve_model_policy(...) -> ModelPolicyDecision`; `assert_external_call_allowed(decision, classification) -> None`.

- [x] **Step 1: Write the failing test**

```python
def test_default_policy_blocks_external_calls():
    decision = resolve_model_policy(
        deployment_mode="local_only",
        requested_classification=DataClassification.PUBLIC,
    )
    assert decision.allow_external is False
    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.PUBLIC)
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/core/test_llm_policy.py -v`

Expected: FAIL because policy functions do not exist.

- [x] **Step 3: Implement the policy resolver**

Use the strictest decision. `restricted` is never external. Policy-service failure is fail-closed. The gateway contract must be used by Query Rewrite, remote Embedding, remote Rerank, and answer generation.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/core/test_llm_policy.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/core/llm_policy.py backend/tests/core/test_llm_policy.py
git commit -m "feat: enforce fail-closed LLM data policy"
```

### Task 9: Full Suite and Vertical Slice Verification

**Files:**
- Modify: `README.md`
- Verify: all files above

- [x] **Step 1: Run the full suite**

Run: `pytest -q`

Expected: all tests pass.

- [x] **Step 2: Run a smoke script**

Create `backend/tests/smoke/test_vertical_slice.py` that combines a Markdown fixture, chunking, permission filter, in-memory retrieval, RRF, and evaluation metrics. Run `pytest backend/tests/smoke/test_vertical_slice.py -q`.

Expected: PASS and produces a trace with a stable `trace_id`.

- [x] **Step 3: Update the README with exact commands and current limitations**

Document that ES/Qdrant, FastAPI routes, Celery workers, and the UI are not yet implemented in this first slice.

- [x] **Step 4: Commit**

```bash
git add README.md backend/tests/smoke
git commit -m "test: verify first RAG vertical slice"
```

