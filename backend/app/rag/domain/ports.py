from __future__ import annotations

from typing import List, Protocol

from .models import Chunk, SearchRequest, SearchResult, ValidationResult


class Retriever(Protocol):
    async def search(self, request: SearchRequest) -> SearchResult:
        ...


class IndexWriter(Protocol):
    async def stage(self, generation_id: str, chunks: List[Chunk]) -> None:
        ...

    async def validate(self, generation_id: str) -> ValidationResult:
        ...

    async def activate(self, generation_id: str) -> None:
        ...

    async def cleanup(self, generation_id: str) -> None:
        ...

