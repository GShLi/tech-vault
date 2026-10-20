# Repository Guidelines

TechVault is a FastAPI and Vue 3 private knowledge-base and RAG system.

## Project Structure & Module Organization

- `backend/app/api/v1/`: FastAPI routes and response envelopes.
- `backend/app/core/`: configuration, authentication, authorization, and security.
- `backend/app/db/`: SQLAlchemy models and session setup.
- `backend/app/modules/`: business services.
- `backend/app/rag/`: RAG domain ports and adapters for parsing, indexing, retrieval, fusion, and evaluation.
- `backend/tests/`: pytest suites organized by backend domain.
- `frontend/src/`: Vue views, Pinia stores, API client, router, and types. Use `@/` for `frontend/src/` imports.
- `deploy/`, `docs/`, and `scripts/`: local infrastructure, design/API documentation, and operational checks.

## Build, Test, and Development Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,api]"
pytest -q                              # Run backend tests
cd deploy && docker compose up -d      # Start local dependencies
TECHVAULT_ENVIRONMENT=development .venv/bin/uvicorn backend.app.main:create_app --factory --reload
```

```bash
cd frontend
npm install
npm test                               # Run Vitest suites
npm run build                          # Type-check and build
npm run dev                            # Start Vite on port 5173
npm run integration                    # Requires both servers and Chrome
```

See `README.md` for required `TECHVAULT_*` environment variables.

## Coding Style & Naming Conventions

Use 4-space indentation and PEP 8 naming in Python: `snake_case` functions, `PascalCase` classes, and `test_*` functions. Use 2-space indentation, single quotes, no semicolons, and PascalCase Vue component filenames in the frontend. Name Pinia stores `useXStore`. No repository-wide linter or formatter is configured; match surrounding code and rely on `pytest` and `npm run build`.

## Testing Guidelines

Use pytest for backend tests and Vitest with jsdom for frontend tests. Mirror the affected module under `backend/tests/` or place a colocated `*.spec.ts` file. Add regression coverage for changed behavior and run the narrow test first, then the full relevant suite. No explicit coverage threshold is enforced.

## Commit & Pull Request Guidelines

Use concise Conventional Commit subjects such as `feat: add audit export`, `fix: reject expired tokens`, or `test: cover pagination`. Use feature branches such as `feat/auth-core`. Pull requests should explain scope and behavior, list verification commands, link related issues, and include screenshots for UI changes. Call out API, configuration, or migration impacts.

## Architecture & Security

Business modules should call RAG ports rather than Elasticsearch, Qdrant, or model SDKs directly. Permission filters must apply before retrieval. Route external model calls through `llm_gateway`. Never commit `.env` or production secrets; production requires a unique `TECHVAULT_JWT_SECRET` of at least 32 bytes.
