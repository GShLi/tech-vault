from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Union


@dataclass(frozen=True)
class GoldenCase:
    query_id: str
    query_type: str
    query: str
    relevant_chunk_ids: Tuple[str, ...]
    filters: Dict[str, Any] = field(default_factory=dict)
    relevance: Dict[str, float] = field(default_factory=dict)


def _require_string(row: Dict[str, Any], field_name: str, line_number: int) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "line {}: {} must be a non-empty string".format(line_number, field_name)
        )
    return value


def _chunk_ids(row: Dict[str, Any], line_number: int) -> Tuple[str, ...]:
    if row.get("relevant_chunk_ids") is None:
        raise ValueError(
            "line {}: relevant_chunk_ids is required".format(line_number)
        )
    values = row["relevant_chunk_ids"]
    if not isinstance(values, list):
        raise ValueError(
            "line {}: relevant_chunk_ids must be a list".format(line_number)
        )
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(
            "line {}: relevant_chunk_ids must contain non-empty strings".format(
                line_number
            )
        )
    if len(set(values)) != len(values):
        raise ValueError(
            "line {}: relevant_chunk_ids must not contain duplicates".format(
                line_number
            )
        )
    return tuple(values)


def _optional_object(
    row: Dict[str, Any],
    field_name: str,
    line_number: int,
) -> Dict[str, Any]:
    value = row.get(field_name, {})
    if not isinstance(value, dict):
        raise ValueError(
            "line {}: {} must be an object".format(line_number, field_name)
        )
    return value


def load_golden_set(path: Union[str, Path]) -> List[GoldenCase]:
    """Load and validate a JSONL golden query set."""
    cases: List[GoldenCase] = []
    seen_query_ids: Set[str] = set()

    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    "line {}: invalid JSON: {}".format(line_number, error.msg)
                ) from error
            if not isinstance(row, dict):
                raise ValueError(
                    "line {}: each row must be a JSON object".format(line_number)
                )

            query_id = _require_string(row, "query_id", line_number)
            if query_id in seen_query_ids:
                raise ValueError(
                    "duplicate query_id {!r} at line {}".format(query_id, line_number)
                )
            seen_query_ids.add(query_id)

            filters = _optional_object(row, "filters", line_number)
            raw_relevance = _optional_object(row, "relevance", line_number)
            relevance: Dict[str, float] = {}
            for chunk_id, value in raw_relevance.items():
                if (
                    not isinstance(chunk_id, str)
                    or not chunk_id
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    raise ValueError(
                        "line {}: relevance must map chunk IDs to numbers".format(
                            line_number
                        )
                    )
                relevance[chunk_id] = float(value)

            cases.append(
                GoldenCase(
                    query_id=query_id,
                    query_type=_require_string(row, "query_type", line_number),
                    query=_require_string(row, "query", line_number),
                    relevant_chunk_ids=_chunk_ids(row, line_number),
                    filters=dict(filters),
                    relevance=relevance,
                )
            )

    return cases
