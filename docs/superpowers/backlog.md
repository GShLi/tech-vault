# TechVault Engineering Backlog

Items below are deliberately deferred from the current API and RAG slices.

## RAG correctness

- Make oversized fenced code blocks split safely without breaking the fence.
- Add full retrieval Trace persistence: filters, BM25/Dense candidates, RRF, rerank, final context, latency, model metadata, and degradation.
- Add `source_revision` and validity-window fields to the chunk contract and enforce them in retrieval.
- Route the vertical-slice smoke test through `AuthorizationContext` and `build_retrieval_filters`.
- Validate zero, negative, and blank retrieval scope values in `InMemoryRetriever.search`.

## API and persistence

- Add Alembic migrations instead of schema creation at application startup.
- Add refresh-token rotation, logout revocation, and password-change endpoints.
- Add active-membership filtering to `/auth/me` if disabled memberships should not be displayed.
- Add API tests for validation-error redaction regression and request-ID sanitization as new endpoints are added.
