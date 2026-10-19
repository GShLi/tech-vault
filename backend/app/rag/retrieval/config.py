from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EngineMode(str, Enum):
    DUAL_ENGINE = "dual_engine"
    ELASTIC_SINGLE = "elastic_single"


@dataclass(frozen=True)
class RetrievalConfig:
    engine_mode: EngineMode = EngineMode.DUAL_ENGINE
    bm25_top_k: int = 50
    dense_top_k: int = 50
    rrf_k: int = 60
    rerank_input_size: int = 50
    final_top_n: int = 10
    answer_context_top_n: int = 8

