from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import AsyncIterable, AsyncIterator, Iterable, Optional, Sequence, Tuple

from backend.app.rag.domain.models import RetrievedChunk


_CITATION_RE = re.compile(r"\[c(\d+)\]", re.IGNORECASE)


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
        citation_chunk_ids, citations_degraded = _citation_chunk_ids(
            text,
            self._chunks,
        )
        has_content = bool(text.strip())
        return AnswerResult(
            text=text,
            status="completed" if has_content else "refused",
            citation_chunk_ids=citation_chunk_ids if has_content else (),
            model_id=self._model_id,
            route=self._route,
            degraded=(
                (self._degraded or citations_degraded)
                if has_content
                else self._degraded
            ),
            input_tokens=estimate_tokens(self._question)
            + sum(estimate_tokens(chunk.content) for chunk in self._chunks),
            output_tokens=estimate_tokens(text),
            refusal_reason=None if has_content else "INSUFFICIENT_EVIDENCE",
        )


def _citation_chunk_ids(
    text: str,
    chunks: Sequence[RetrievedChunk],
) -> Tuple[Tuple[str, ...], bool]:
    matches = _CITATION_RE.findall(text)
    if not matches:
        return (), True

    cited = []
    seen = set()
    has_invalid_citation = False
    for raw_index in matches:
        index = int(raw_index) - 1
        if 0 <= index < len(chunks):
            chunk_id = chunks[index].chunk_id
            if chunk_id not in seen:
                seen.add(chunk_id)
                cited.append(chunk_id)
        else:
            has_invalid_citation = True
    if cited:
        return tuple(cited), has_invalid_citation
    return (), True


def _piece_text(piece: object) -> str:
    if isinstance(piece, bytes):
        return piece.decode("utf-8", errors="replace")
    if isinstance(piece, str):
        return piece
    return str(piece) if piece is not None else ""


def answer_result_from_text(
    text: str,
    *,
    question: str,
    chunks: Sequence[RetrievedChunk],
    model_id: str,
    route: str,
    degraded: bool = False,
) -> AnswerResult:
    """Build the canonical answer shape from one provider text response."""
    accumulator = AnswerAccumulator(
        question=question,
        chunks=chunks,
        model_id=model_id,
        route=route,
        degraded=degraded,
    )
    accumulator.add(text)
    return accumulator.finish()


def answer_stream_from_pieces(
    pieces: Iterable[object] | AsyncIterable[object],
    *,
    question: str,
    chunks: Sequence[RetrievedChunk],
    model_id: str,
    route: str,
    degraded: bool = False,
) -> AnswerStream:
    """Wrap provider text pieces in a normalized stream with a terminal result."""
    stream = AnswerStream()
    accumulator = AnswerAccumulator(
        question=question,
        chunks=chunks,
        model_id=model_id,
        route=route,
        degraded=degraded,
    )

    async def iterate():
        if inspect.isasyncgen(pieces) or hasattr(pieces, "__aiter__"):
            async for piece in pieces:
                text = _piece_text(piece)
                if not text:
                    continue
                accumulator.add(text)
                yield text
        else:
            for piece in pieces:
                text = _piece_text(piece)
                if not text:
                    continue
                accumulator.add(text)
                yield text
        stream.result = accumulator.finish()

    stream.bind(iterate())
    return stream
