import math

from backend.app.rag.parsing.contracts import ParseError


def chunk_quality_report(result):
    parents = {parent.parent_id: parent for parent in result.parents}
    if len(parents) != len(result.parents) or len({child.child_id for child in result.children}) != len(result.children):
        raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Duplicate chunk identities.")
    coverage = {parent_id: [] for parent_id in parents}
    for child in result.children:
        parent = parents.get(child.parent_chunk_id)
        if parent is None or not 0 <= child.parent_start_offset < child.parent_end_offset <= len(parent.content):
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Invalid parent span.")
        if parent.content[child.parent_start_offset:child.parent_end_offset] != child.content:
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Child text differs from its source span.")
        if not child.content.strip():
            raise ParseError("CHUNK_QUALITY_FAILED", "Empty child chunk.")
        coverage[parent.parent_id].append((child.parent_start_offset, child.parent_end_offset))
    for parent_id, spans in coverage.items():
        end = 0
        for start, stop in sorted(spans):
            if start > end and parents[parent_id].content[end:start].strip():
                raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Uncovered parent text.")
            end = max(end, stop)
        if not spans or parents[parent_id].content[end:].strip():
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Incomplete parent coverage.")
    counts = sorted(child.token_count for child in result.children)
    return {"passed": True, "parent_count": len(parents), "child_count": len(counts),
            "min_tokens": min(counts, default=0), "max_tokens": max(counts, default=0),
            "average_tokens": sum(counts) / max(1, len(counts)),
            "p95_tokens": counts[max(0, math.ceil(len(counts) * .95) - 1)] if counts else 0,
            "unsafe_split_count": sum(child.unsafe_split for child in result.children)}
