"""Local BGE-M3 embedding and rerank service.

Runs behind the `ml` compose profile. The model is downloaded on first start.
"""

from __future__ import annotations

import os
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel, Field

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")

app = FastAPI(title="TechVault Embedding Service", version="0.1.0")

_embedder = None
_reranker = None


class EmbedRequest(BaseModel):
    texts: List[str] = Field(min_length=1, max_length=256)


class EmbedResponse(BaseModel):
    vectors: List[List[float]]
    model: str
    dimension: int


class RerankRequest(BaseModel):
    query: str
    documents: List[str]


class RerankResponse(BaseModel):
    scores: List[float]


def _get_embedder():
    global _embedder
    if _embedder is None:
        from FlagEmbedding import FlagModel

        _embedder = FlagModel(MODEL_NAME, use_fp16=False)
    return _embedder


def _get_reranker():
    global _reranker
    if _reranker is None:
        from FlagEmbedding import FlagReranker

        _reranker = FlagReranker(RERANK_MODEL_NAME, use_fp16=False)
    return _reranker


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
def embed(body: EmbedRequest):
    model = _get_embedder()
    vectors = model.encode(body.texts).tolist()
    return EmbedResponse(
        vectors=vectors,
        model=MODEL_NAME,
        dimension=len(vectors[0]) if vectors else 0,
    )


@app.post("/rerank", response_model=RerankResponse)
def rerank(body: RerankRequest):
    reranker = _get_reranker()
    pairs = [[body.query, document] for document in body.documents]
    scores = reranker.compute_score(pairs)
    if isinstance(scores, float):
        scores = [scores]
    return RerankResponse(scores=[float(score) for score in scores])


class TokenizeResponse(BaseModel):
    counts: List[int]
    model: str
    max_length: int


@app.post("/tokenize", response_model=TokenizeResponse)
def tokenize(body: EmbedRequest):
    tokenizer = _get_embedder().tokenizer
    encoded = tokenizer(body.texts, add_special_tokens=True, truncation=False, padding=False)
    return TokenizeResponse(counts=[len(ids) for ids in encoded["input_ids"]],
                            model=MODEL_NAME, max_length=8192)
