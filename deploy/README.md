# Deployment

## PoC Stack

`docker-compose.yml` starts the full local stack:

| Service | Image | Port | Purpose |
| --- | --- | --- | --- |
| `frontend` | nginx + built Vue app | 8080 | Web UI, proxies `/api` to backend |
| `backend` | Python 3.11 + FastAPI | 8000 | API, `/docs` for OpenAPI |
| `celery-worker` | same image | - | Async ingestion and indexing |
| `flower` | same image | 5555 | Celery task monitoring |
| `postgres` | postgres:16-alpine | 5432 | Primary database |
| `redis` | redis:7-alpine | 6379 | Broker and cache |
| `elasticsearch` | 8.13.4 | 9200 | BM25 and dense vectors |
| `qdrant` | v1.12.4 | 6333 | Dense vectors |
| `minio` | RELEASE.2024-10-13 | 9000/9001 | Object storage |
| `embedding` | custom (profile `ml`) | 8001 | BGE-M3 + rerank |

## Development: External Services Only

```bash
cd deploy
docker compose up -d
```

This starts PostgreSQL, Redis, MinIO, Elasticsearch and Qdrant only. Run the
application code directly for debugging:

```bash
cd ..
TECHVAULT_ENVIRONMENT=development \
TECHVAULT_DATABASE_URL=postgresql+psycopg2://techvault:techvault@127.0.0.1:55433/techvault \
TECHVAULT_REDIS_URL=redis://127.0.0.1:56379/0 \
TECHVAULT_ES_URL=http://127.0.0.1:59200 \
TECHVAULT_QDRANT_URL=http://127.0.0.1:56333 \
TECHVAULT_ENABLE_INDEXING=true \
.venv/bin/uvicorn backend.app.main:create_app --factory --reload

cd frontend
export PATH="$HOME/.nvm/versions/node/v22.15.0/bin:$PATH"
npm run dev
```

## Full Container Mode

Use this only for deployment verification, not day-to-day development:

```bash
cd deploy
docker compose --profile app up -d --build
```

First start:

```text
http://127.0.0.1:8080          # Frontend
http://127.0.0.1:8000/docs     # API docs
http://127.0.0.1:9001          # MinIO console (minioadmin/minioadmin)
http://127.0.0.1:5555          # Flower
```

## Initial administrator

The backend creates the protected super administrator on first startup:

```text
email:    admin@techvault.local
password: ChangeMe-123!
```

Change this password after the first login. Override the initial values with
`TECHVAULT_ADMIN_EMAIL`, `TECHVAULT_ADMIN_PASSWORD`, and
`TECHVAULT_ADMIN_DISPLAY_NAME`. External registration is disabled by default;
create all other users through the administrator's user-management page.

## With Local Embedding

The `embedding` service downloads BGE-M3 (~2 GB) on first start:

```bash
cd deploy
docker compose --profile ml up -d --build
```

To run the embedding service together with the container app:

```bash
docker compose --profile app --profile ml up -d --build
```

## Useful Commands

```bash
docker compose logs -f backend
docker compose exec postgres psql -U techvault -d techvault
docker compose exec redis redis-cli
docker compose down          # stop, keep data
docker compose down -v       # stop and delete volumes
```

## Notes

- `elasticsearch` runs single-node with security disabled; do not reuse this
  configuration outside local development.
- `TECHVAULT_JWT_SECRET` in `docker-compose.yml` is a local development value.
  Production deployments must inject a unique 32+ byte secret.
- The backend creates the schema on startup. Alembic migrations replace this
  bridge before production.
- File uploads persist to the `upload-data` volume at `/data/uploads`.
