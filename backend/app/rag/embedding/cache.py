"""Reuse vectors for unchanged embedding inputs within the same team and model."""
import hashlib
import json
from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select

from backend.app.db.models import EmbeddingCache, utc_now
from backend.app.rag.chunking.semantic import embedding_input
from backend.app.rag.embedding.service import EmbeddingClient, validate_vectors
from backend.app.rag.parsing.contracts import ParseError


def embed_chunks(session, chunks, settings):
    if not chunks:
        return []
    inputs = [embedding_input(chunk.source_path, chunk.heading_path, chunk.content,
                              chunk.source_locator.get("table_header", "")) for chunk in chunks]
    keys = [hashlib.sha256(json.dumps([chunk.team_id, settings.embedding_model,
             settings.embedding_dimension, text], ensure_ascii=False).encode()).hexdigest()
            for chunk, text in zip(chunks, inputs)]
    cache = {}
    for start in range(0, len(keys), 500):
        rows = session.scalars(select(EmbeddingCache).where(
            EmbeddingCache.key.in_(keys[start:start + 500]),
            EmbeddingCache.created_at >= utc_now() - timedelta(days=7),
        ))
        cache.update({row.key: (json.loads(row.vector), row.token_count) for row in rows})
    missing = {key: text for key, text in zip(keys, inputs) if key not in cache}
    if missing:
        client = EmbeddingClient(settings.embedding_url, dimension=settings.embedding_dimension,
            allow_hash_fallback=False, model=settings.embedding_model, batch_size=settings.embedding_batch_size)
        texts = list(missing.values())
        counts = client.tokenize(texts)
        vectors = client.embed(texts)
        validate_vectors(vectors, len(texts), settings.embedding_dimension)
        cache.update({key: (vector, count) for key, vector, count in zip(missing, vectors, counts)})
        # Concurrent teams cannot share keys; duplicate deliveries remain harmless.
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        teams = {key: chunk.team_id for key, chunk in zip(keys, chunks)}
        values = [{"key": key, "team_id": teams[key], "vector": json.dumps(cache[key][0]), "token_count": cache[key][1]} for key in missing]
        for start in range(0, len(values), 100):
            statement = insert(EmbeddingCache).values(values[start:start + 100])
            session.execute(statement.on_conflict_do_update(index_elements=["key"], set_={
                "vector": statement.excluded.vector, "token_count": statement.excluded.token_count,
                "created_at": statement.excluded.created_at,
            }))
    result = []
    for chunk, key in zip(chunks, keys):
        vector, count = cache[key]
        maximum = 160 if chunk.node_type == "code" else settings.chunk_child_max_tokens
        if count > maximum:
            raise ParseError("CHUNK_QUALITY_FAILED", "Effective child content exceeds its token budget.")
        result.append(replace(chunk, content_vector=vector, token_count=count,
                              embedding_model=settings.embedding_model, tokenizer_model=settings.embedding_model))
    return result
