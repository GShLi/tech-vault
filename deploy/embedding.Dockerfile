FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip \
    && pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" \
    && pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install FlagEmbedding

COPY deploy/embedding_service.py /app/embedding_service.py

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8001/health || exit 1

CMD ["uvicorn", "embedding_service:app", "--host", "0.0.0.0", "--port", "8001"]
