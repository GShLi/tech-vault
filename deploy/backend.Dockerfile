FROM lm2kjj4pk1kreo.xuanyuan.run/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY backend ./backend

RUN pip install --upgrade pip setuptools \
    && pip install -e ".[test,api,tasks]"

ENV TECHVAULT_DATABASE_URL=postgresql+psycopg2://techvault:techvault@postgres:5432/techvault \
    TECHVAULT_ENVIRONMENT=development \
    TECHVAULT_JWT_SECRET=local-development-secret-at-least-32-bytes

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

CMD ["uvicorn", "backend.app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
