import re

import pytest

from backend.app.rag.chunking.semantic import ChunkBudget, SemanticChunker, embedding_input
from backend.app.rag.chunking.quality import chunk_quality_report
from backend.app.rag.parsing.contracts import DocumentNode, NodeType


def tokenize(texts):
    return [len(re.findall(r"\w+|[^\s\w]", text)) + 2 for text in texts]


def test_exact_spans_budget_overlap_and_unique_duplicate_sections():
    nodes = [DocumentNode(str(index), NodeType.PARAGRAPH,
             "First sentence stays whole.\n\nSecond sentence stays whole. Third sentence stays whole.",
             ("Section",)) for index in range(3)]
    chunker = SemanticChunker(tokenize=tokenize, budget=ChunkBudget(
        child_target=23, child_max=24, child_overlap=7, parent_target=20, parent_max=25, minimum_child=0))
    result = chunker.chunk(nodes, document_version_id="v1", source_path="guide.md")
    assert len(result.parents) == 3
    assert len({parent.parent_id for parent in result.parents}) == 3
    assert chunk_quality_report(result)["passed"]
    assert all(child.token_count <= 24 for child in result.children)
    assert any(child.overlap_before_tokens > 0 for child in result.children)
    for child in result.children:
        parent = next(item for item in result.parents if item.parent_id == child.parent_chunk_id)
        assert parent.content[child.parent_start_offset:child.parent_end_offset] == child.content
        assert child.token_count == tokenize([embedding_input("guide.md", child.heading_path, child.content)])[0]


def test_logical_keys_survive_content_and_version_change():
    chunker = SemanticChunker(tokenize=tokenize)
    def chunks(text, version):
        return chunker.chunk([DocumentNode("n", NodeType.PARAGRAPH, text, ("Guide",))],
                             document_version_id=version, source_path="guide.md")
    before, after = chunks("Java 17 is supported.", "v1"), chunks("Java 21 is supported.", "v2")
    assert before.children[0].logical_key == after.children[0].logical_key
    assert before.children[0].child_id != after.children[0].child_id


def test_huge_identifier_is_bounded_and_reported():
    chunker = SemanticChunker(tokenize=lambda texts: [len(text) for text in texts],
                             budget=ChunkBudget(child_target=65, child_max=80, child_overlap=0, parent_target=90, parent_max=100))
    result = chunker.chunk([DocumentNode("n", NodeType.PARAGRAPH, "A" * 500)], document_version_id="v", source_path="a")
    assert all(child.token_count <= 80 for child in result.children)
    assert all(parent.token_count <= 100 for parent in result.parents)
    assert any(child.unsafe_split for child in result.children)
    assert chunk_quality_report(result)["passed"]


def test_code_and_table_remain_typed_and_exact():
    nodes = [DocumentNode("code", NodeType.CODE, "```python\n    value = 42\n    return value\n```"),
             DocumentNode("table", NodeType.TABLE, "| Name | Value |\n| Java | 21 |")]
    result = SemanticChunker(tokenize=tokenize).chunk(nodes, document_version_id="v", source_path="a.md")
    assert {child.node_type for child in result.children} == {"code", "table"}
    assert "    value" in result.children[0].content
    assert chunk_quality_report(result)["passed"]


@pytest.mark.parametrize("parent_max", [1400, 150])
def test_oversized_table_row_keeps_content_header_and_row_label(parent_max):
    header = "| Test slice | Imported auto-configuration |"
    row = "| @WebFluxTest | " + " ".join("AutoConfiguration{0}".format(n) for n in range(900)) + " |"
    text = header + "\n" + row
    result = SemanticChunker(tokenize=tokenize, budget=ChunkBudget(
        parent_target=parent_max, parent_max=parent_max,
    )).chunk([DocumentNode("table", NodeType.TABLE, text, page_no=922)],
            document_version_id="v", source_path="reference.pdf")
    assert chunk_quality_report(result)["passed"]
    assert "".join(p.content for p in result.parents) == text
    assert any(c.source_locator.get("table_row_split") for c in result.children)
    assert all(p.token_count <= parent_max for p in result.parents)
    for child in result.children:
        context = child.source_locator.get("table_header", "")
        rendered = embedding_input("reference.pdf", child.heading_path, child.content, context)
        assert child.token_count == tokenize([rendered])[0] <= 512
        if "@WebFluxTest" not in child.content and child.content.strip() != header:
            assert "Table row: @WebFluxTest" in context
        assert not child.unsafe_split
