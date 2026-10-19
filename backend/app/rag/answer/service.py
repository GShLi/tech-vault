from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Sequence, Tuple

from backend.app.rag.domain.models import RetrievedChunk


def estimate_tokens(text: str) -> int:
    """Return a deterministic local estimate for trace and gate accounting."""
    normalized = text.strip()
    if not normalized:
        return 0
    return max(1, (len(normalized) + 3) // 4)


@dataclass(frozen=True)
class AnswerResult:
    text: str
    status: str
    citation_chunk_ids: Tuple[str, ...]
    model_id: str
    route: str
    degraded: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    refusal_reason: str | None = None


class AnswerStream:
    """Async answer stream whose terminal result is available after iteration."""

    def __init__(self) -> None:
        self._iterator: Optional[AsyncIterator[str]] = None
        self.result: Optional[AnswerResult] = None

    def bind(self, iterator: AsyncIterator[str]) -> None:
        self._iterator = iterator

    def __aiter__(self) -> "AnswerStream":
        return self

    async def __anext__(self) -> str:
        if self._iterator is None:
            raise RuntimeError("answer stream is not bound")
        return await self._iterator.__anext__()

    async def aclose(self) -> None:
        if self._iterator is not None and hasattr(self._iterator, "aclose"):
            await self._iterator.aclose()


class AnswerAccumulator:
    """Collect provider stream pieces into the canonical answer result."""

    def __init__(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        model_id: str,
        route: str,
        degraded: bool = False,
    ) -> None:
        self._question = question
        self._chunks = tuple(chunks)
        self._model_id = model_id
        self._route = route
        self._degraded = degraded
        self._pieces = []

    @property
    def has_content(self) -> bool:
        return bool(self._pieces)

    def add(self, piece: str) -> None:
        if piece:
            self._pieces.append(piece)

    def finish(self) -> AnswerResult:
        text = "".join(self._pieces)
        return AnswerResult(
            text=text,
            status="completed" if text else "refused",
            citation_chunk_ids=tuple(chunk.chunk_id for chunk in self._chunks),
            model_id=self._model_id,
            route=self._route,
            degraded=self._degraded,
            input_tokens=estimate_tokens(self._question)
            + sum(estimate_tokens(chunk.content) for chunk in self._chunks),
            output_tokens=estimate_tokens(text),
            refusal_reason=None if text else "INSUFFICIENT_EVIDENCE",
        )


class ExtractiveLocalGenerator:
    """Deterministic local fallback used when no local LLM server is configured."""

    model_id = "extractive-local"
    route = "local_extractive_fallback"

    def generate(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int = 8,
    ) -> AnswerResult:
        selected = list(chunks[:max_chunks])
        if not selected:
            refusal = "知识库中没有足够依据。"
            return AnswerResult(
                text=refusal,
                status="refused",
                citation_chunk_ids=(),
                model_id=self.model_id,
                route=self.route,
                degraded=True,
                input_tokens=estimate_tokens(question),
                output_tokens=estimate_tokens(refusal),
                refusal_reason="INSUFFICIENT_EVIDENCE",
            )

        lines = ["根据知识库检索结果："]
        for index, chunk in enumerate(selected, start=1):
            lines.append("[c{0}] {1}".format(index, chunk.content.strip()))
        text = "\n\n".join(lines)
        return AnswerResult(
            text=text,
            status="completed",
            citation_chunk_ids=tuple(chunk.chunk_id for chunk in selected),
            model_id=self.model_id,
            route=self.route,
            degraded=True,
            input_tokens=estimate_tokens(question)
            + sum(estimate_tokens(chunk.content) for chunk in selected),
            output_tokens=estimate_tokens(text),
        )
