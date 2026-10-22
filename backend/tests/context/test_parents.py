import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.rag.context.parents import hydrate_parent_chunks
from backend.app.rag.domain.models import RetrievedChunk
from backend.app.rag.parsing.contracts import ParseError


def _family():
    common = dict(document_id="document", team_id="team", knowledge_base_id="kb",
                  owner_user_id="owner", visibility="team_shared", data_classification="public",
                  source_locator=json.dumps({"document_version_id": "version"}), chunk_status="enabled")
    parent = dict(common, id="parent", parent_chunk_id=None, chunk_level="parent", content="original text")
    child = dict(common, id="child", parent_chunk_id="parent", chunk_level="child",
                 content="original text", auto_content="original text", parent_start_offset=0, parent_end_offset=13)
    return parent, child


def _evidence():
    return RetrievedChunk("child", "version", "original text", 1,
                          parent_chunk_id="parent", index_generation="generation")


def _session(*rows):
    session = Mock()
    session.execute.return_value = [(row["id"], json.dumps(row)) for row in rows]
    return session


def test_uses_one_snapshot_query_and_retains_child_evidence():
    session = _session(*_family())
    result = hydrate_parent_chunks(session, [_evidence()])
    assert result[0].chunk_id == "parent"
    assert result[0].evidence_chunk_ids == ("child",)
    assert result[0].content == "original text"
    session.execute.assert_called_once()
    session.scalars.assert_not_called()  # No live rows or per-parent membership queries.


@pytest.mark.parametrize("mutation", ["scope", "disabled", "version", "membership", "missing"])
def test_rejects_inconsistent_snapshot_evidence(mutation):
    parent, child = _family()
    if mutation == "scope":
        child["team_id"] = "other-team"
    elif mutation == "disabled":
        child["chunk_status"] = "disabled"
    elif mutation == "version":
        parent["source_locator"] = json.dumps({"document_version_id": "other-version"})
    session = _session(parent, child)
    if mutation == "membership":
        session.execute.return_value[0] = ("other-parent", json.dumps(parent))
    elif mutation == "missing":
        session.execute.return_value = session.execute.return_value[1:]
    with pytest.raises(ParseError):
        hydrate_parent_chunks(session, [_evidence()])


def test_generation_snapshot_manual_edit_is_applied():
    parent, child = _family()
    child["content"] = "updated text"
    result = hydrate_parent_chunks(_session(parent, child), [_evidence()])
    assert result[0].content == "updated text"
