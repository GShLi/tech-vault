# Deployment

## Development Dependencies

日常开发只容器化外部依赖，自有前后端代码直接运行：

```bash
cd deploy
docker compose up -d
```

| Service | Port | Purpose |
| --- | --- | --- |
| `postgres` | `55433` | Primary database with pgvector |
| `redis` | `56379` | Celery broker and cache |
| `elasticsearch` | `59200` | BM25 and ES hybrid retrieval |
| `qdrant` | `56333` | Dense vectors |
| `minio` | `59000` / `59001` | Object storage and console |

MinIO local credentials are `minioadmin / minioadmin`; the application bucket is
`techvault`.

## Backend

```bash
cd ..
export TECHVAULT_ENVIRONMENT=development
export TECHVAULT_DATABASE_URL=postgresql+psycopg2://techvault:techvault@127.0.0.1:55433/techvault
export TECHVAULT_REDIS_URL=redis://127.0.0.1:56379/0
export TECHVAULT_ES_URL=http://127.0.0.1:59200
export TECHVAULT_QDRANT_URL=http://127.0.0.1:56333
export TECHVAULT_MINIO_URL=http://127.0.0.1:59000
export TECHVAULT_MINIO_PUBLIC_URL=http://127.0.0.1:59000
export TECHVAULT_MINIO_ACCESS_KEY=minioadmin
export TECHVAULT_MINIO_SECRET_KEY=minioadmin
export TECHVAULT_MINIO_BUCKET=techvault
export TECHVAULT_UPLOAD_DIR="$PWD/data/uploads"
export TECHVAULT_OBJECT_STORAGE_ENABLED=true
export TECHVAULT_ENABLE_INDEXING=true
export TECHVAULT_TASK_EXECUTION_MODE=inline
export TECHVAULT_DOCUMENT_RETENTION_DAYS=7

.venv/bin/uvicorn backend.app.main:create_app --factory --reload --port 8000
```

`TECHVAULT_TASK_EXECUTION_MODE`:

- `inline`: execute ingestion, source sync, reindex and maintenance in-process.
- `celery`: enqueue work for a worker. This is the production shape.

For Celery mode, run a worker and beat scheduler in separate terminals:

```bash
.venv/bin/celery -A backend.app.workers.tasks worker --loglevel=info
.venv/bin/celery -A backend.app.workers.tasks beat --loglevel=info
```

Beat dispatches `techvault.purge_expired_documents` every hour. A document is not
physically purged until its `TECHVAULT_DOCUMENT_RETENTION_DAYS` window expires.
The purge is idempotent and retries on the next run if MinIO or an index is
unavailable.

## Frontend

```bash
cd frontend
export PATH="$HOME/.nvm/versions/node/v22.15.0/bin:$PATH"
VITE_DEV_API_TARGET=http://127.0.0.1:8000 npm run dev
```

Open `http://127.0.0.1:5173/login`.

## Initial Administrator

The backend creates the protected super administrator on first startup:

```text
email:    admin@techvault.local
password: ChangeMe-123!
```

Change the password after first login. External registration is disabled. The
administrator creates every user and team. Override initial values with
`TECHVAULT_ADMIN_EMAIL`, `TECHVAULT_ADMIN_PASSWORD`, and
`TECHVAULT_ADMIN_DISPLAY_NAME`.

## Containerized Application Profile

The `app` profile is kept only for deployment verification:

```bash
docker compose --profile app up -d --build
```

It starts the backend, Celery worker, Celery beat, Flower and the built frontend.
Use local processes for day-to-day debugging so code changes take effect without
image rebuilds.

## Local Embedding Profile

The optional embedding service downloads BGE-M3 on first start:

```bash
docker compose --profile ml up -d --build
```

## Useful Commands

```bash
docker compose ps
docker compose logs -f postgres redis minio elasticsearch qdrant
docker compose exec postgres psql -U techvault -d techvault
docker compose exec redis redis-cli
docker compose down
docker compose down -v
```

## Notes

- Elasticsearch runs single-node with security disabled only for local development.
- `TECHVAULT_JWT_SECRET` in Compose is a local value. Production must inject a unique 32+ byte secret.
- The PoC creates and bridges the schema on startup. Alembic migrations remain required before production.
- Secrets are write-only through the API. Responses and audit records expose only masks.
