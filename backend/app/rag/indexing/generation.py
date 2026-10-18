from __future__ import annotations

from typing import Dict, Iterable, List, Set

from backend.app.rag.domain.models import Chunk, ValidationResult


class InMemoryIndexWriter:
    """Generation-aware index writer used by tests and the first vertical slice."""

    def __init__(self) -> None:
        self._staged: Dict[str, List[Chunk]] = {}
        self._validated: Set[str] = set()
        self._active_generation: str = ""

    async def stage(self, generation_id: str, chunks: Iterable[Chunk]) -> None:
        if generation_id == self._active_generation:
            raise ValueError("cannot stage into the active generation")
        self._staged[generation_id] = list(chunks)
        self._validated.discard(generation_id)

    async def validate(self, generation_id: str) -> ValidationResult:
        chunks = self._staged.get(generation_id)
        if chunks is None:
            return ValidationResult(False, ("generation not staged",), 0)

        errors = []
        seen = set()
        for chunk in chunks:
            if not chunk.chunk_id:
                errors.append("chunk_id is empty")
            if chunk.chunk_id in seen:
                errors.append("duplicate chunk_id: " + chunk.chunk_id)
            seen.add(chunk.chunk_id)
            if not chunk.content.strip():
                errors.append("empty content: " + chunk.chunk_id)
            if not chunk.team_id or not chunk.knowledge_base_id:
                errors.append("missing authorization scope: " + chunk.chunk_id)
            if chunk.index_generation and chunk.index_generation != generation_id:
                errors.append("generation mismatch: " + chunk.chunk_id)

        result = ValidationResult(not errors, tuple(errors), len(chunks))
        if result.passed:
            self._validated.add(generation_id)
        return result

    async def activate(self, generation_id: str) -> None:
        if generation_id not in self._validated:
            raise ValueError("cannot activate an unvalidated generation")
        self._active_generation = generation_id

    async def cleanup(self, generation_id: str) -> None:
        if generation_id == self._active_generation:
            raise ValueError("cannot cleanup the active generation")
        self._staged.pop(generation_id, None)
        self._validated.discard(generation_id)

    def active_chunks(self) -> List[Chunk]:
        return list(self._staged.get(self._active_generation, ()))

    @property
    def active_generation(self) -> str:
        return self._active_generation

