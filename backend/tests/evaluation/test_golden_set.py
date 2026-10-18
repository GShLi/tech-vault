from pathlib import Path

import pytest

from backend.app.rag.evaluation.golden_set import load_golden_set


def test_golden_set_rejects_duplicate_query_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"query_id":"q1","query_type":"concept","query":"a","relevant_chunk_ids":["c1"]}\n'
        '{"query_id":"q1","query_type":"concept","query":"b","relevant_chunk_ids":["c2"]}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate query_id"):
        load_golden_set(path)


def test_golden_set_rejects_missing_relevant_chunk_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"query_id":"q1","query_type":"concept","query":"a"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relevant_chunk_ids"):
        load_golden_set(path)


def test_golden_set_supports_optional_filters_and_relevance(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '{"query_id":"q1","query_type":"version_filter","query":"a",'
        '"relevant_chunk_ids":["c1","c2"],'
        '"filters":{"product":"spring-boot","version_values":["3.2"]},'
        '"relevance":{"c1":3,"c2":1}}\n'
        '{"query_id":"q2","query_type":"concept","query":"b",'
        '"relevant_chunk_ids":[]}\n',
        encoding="utf-8",
    )

    cases = load_golden_set(path)

    assert cases[0].filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
    assert cases[0].relevance == {"c1": 3.0, "c2": 1.0}
    assert cases[0].relevant_chunk_ids == ("c1", "c2")
    assert cases[1].filters == {}
    assert cases[1].relevance == {}
    assert cases[1].relevant_chunk_ids == ()


def test_seed_golden_set_covers_required_query_classes():
    seed_path = Path(__file__).resolve().parents[1] / "fixtures" / "golden_set.seed.jsonl"

    cases = load_golden_set(seed_path)

    required_types = {
        "exact_identifier",
        "concept",
        "cross_language",
        "version_filter",
        "follow_up",
        "insufficient_evidence",
        "permission_negative",
    }
    assert required_types.issubset({case.query_type for case in cases})
    assert all(
        case.relevant_chunk_ids == ()
        for case in cases
        if case.query_type in {"insufficient_evidence", "permission_negative"}
    )
