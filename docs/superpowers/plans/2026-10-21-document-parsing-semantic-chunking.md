# Document Parsing and Semantic Chunking Implementation Plan

Updated 2026-10-21 following code review and the decision to discard development data.
This plan replaces the earlier illustrative code snippets. The specification remains
`../specs/2026-10-21-document-parsing-semantic-chunking-design.md`.

## Scope and Constraints

- Fresh database and retrieval indexes; no historical migration or payload fallback.
- Existing source files, runtime databases and storage volumes are not automatically deleted.
- MD/TXT, ordered DOCX and native PDF produce typed nodes. Scanned/mixed PDFs fail explicitly.
- Actual BGE-M3 token counts include embedding metadata. Ingestion cannot fall back to hash vectors.
- Child IDs are versioned; override logical keys are structural and content-independent.
- Child offsets refer to exact parent text, including whitespace and overlap.
- Parents are database context; only enabled children enter retrieval indexes.
- A failed replacement must preserve the previous active generation.

## Implementation Order

1. Structured parsing contracts and format adapters, MIME checks and PDF limits.
2. Strict tokenizer/embedding contracts, bounded batches and response validation.
3. Exact-span semantic chunking, separate code/table budgets, overlap and quality metrics.
4. Parent/child persistence, independent generation membership snapshots and publication leases.
5. Ingestion integration, manual override inheritance, cancellation and failure diagnostics.
6. Child-only payloads/filters; validate individual ES bulk results and index counts.
7. Parent hydration in streaming and non-streaming chat, scope checks and child evidence tracing.
8. Document/task diagnostics in API contracts, types and document detail UI.
9. Regression coverage and clean-environment deployment documentation.

## Acceptance

- DOCX paragraph/table order, native PDF location and scanned/mixed rejection.
- Exact child spans, deterministic unique IDs, token limits including prefixes,
  code/table type preservation and explicit unsafe long-token splits.
- Tokenizer/model/vector errors fail ingestion without changing published data.
- Manual edits survive version changes by logical key; conflicting edits fail explicitly.
- Complete team snapshots preserve unrelated documents; successful switch and rollback work.
- Parent content is deduplicated, scope-checked and uses child overrides; Trace retains child evidence.
- API diagnostics match OpenAPI and frontend types; frontend tests and build pass.
- Backend regression suite passes. Real-model and real-engine checks are reported separately
  from deterministic test doubles.

## Deferred Production Work

Production credentials/network hardening, monitored dependency readiness, backup/restore
exercises, deployment migration tooling and capacity/load testing are a separate milestone.
Native PDF heuristics require ongoing tuning with representative customer documents.
