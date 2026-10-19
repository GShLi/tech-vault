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

## Quick Start

```bash
cd deploy
docker compose up -d --build
```

First start:

```text
http://127.0.0.1:8080          # Frontend
http://127.0.0.1:8000/docs     # API docs
http://127.0.0.1:9001          # MinIO console (minioadmin/minioadmin)
http://127.0.0.1:5555          # Flower
```

## With Local Embedding

The `embedding` service downloads BGE-M3 (~2 GB) on first start:

```bash
cd deploy
docker compose --profile ml up -d --build
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
