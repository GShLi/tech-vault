import pytest

from backend.app.rag.chunking.identity import (
    build_chunk_id,
    build_logical_chunk_key,
    content_fingerprint,
)
from backend.app.rag.chunking.markdown import chunk_markdown


def test_markdown_chunks_preserve_heading_path():
    chunks = chunk_markdown(
        document_version_id="dv-1",
        source_path="docs/spring.md",
        content=(
            "# Spring\n\n"
            "Intro\n\n"
            "## Virtual Threads\n\n"
            "Use virtual threads."
        ),
    )

    assert chunks[0].heading_path == ("Spring",)
    assert chunks[-1].heading_path == ("Spring", "Virtual Threads")
    assert chunks[-1].content == "Use virtual threads."
    assert chunks[-1].logical_chunk_key.startswith("docs/spring.md#")
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_markdown_chunk_identity_is_stable_across_runs():
    content = "# Spring\n\nIntro\n\n## Virtual Threads\n\nUse virtual threads."

    first = chunk_markdown("dv-1", "docs/spring.md", content)
    second = chunk_markdown("dv-1", "docs/spring.md", content)

    assert [
        (chunk.chunk_id, chunk.logical_chunk_key, chunk.content_hash)
        for chunk in first
    ] == [
        (chunk.chunk_id, chunk.logical_chunk_key, chunk.content_hash)
        for chunk in second
    ]


def test_oversized_section_splits_at_paragraph_boundaries():
    content = (
        "# Limits\n\n"
        + "a" * 40
        + "\n\n"
        + "b" * 40
        + "\n\n"
        + "c" * 40
    )

    chunks = chunk_markdown("dv-1", "docs/limits.md", content, max_chars=50)

    assert [chunk.content for chunk in chunks] == ["a" * 40, "b" * 40, "c" * 40]
    assert all(len(chunk.content) <= 50 for chunk in chunks)


def test_long_paragraph_falls_back_to_character_windows():
    paragraph = "0123456789" * 3

    chunks = chunk_markdown(
        "dv-1",
        "docs/windows.md",
        "# Windows\n\n" + paragraph,
        max_chars=10,
    )

    assert [chunk.content for chunk in chunks] == [
        "0123456789",
        "0123456789",
        "0123456789",
    ]
    assert all(chunk.heading_path == ("Windows",) for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_duplicate_content_receives_unique_stable_ids():
    content = "# Duplicate\n\nRepeat.\n\n# Duplicate\n\nRepeat."

    chunks = chunk_markdown("dv-1", "docs/duplicate.md", content)

    assert len(chunks) == 2
    assert chunks[0].content == chunks[1].content
    assert chunks[0].content_hash == chunks[1].content_hash
    assert chunks[0].chunk_id != chunks[1].chunk_id
    assert chunks[0].logical_chunk_key != chunks[1].logical_chunk_key
    assert chunks == chunk_markdown("dv-1", "docs/duplicate.md", content)


def test_headings_inside_fenced_code_do_not_change_heading_path():
    content = (
        "# Main\n\n"
        "Before\n\n"
        "```python\n"
        "# not a heading\n\n"
        "print('ok')\n"
        "```\n\n"
        "After"
    )

    chunks = chunk_markdown("dv-1", "docs/code.md", content)

    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Main",)
    assert "# not a heading" in chunks[0].content


def test_empty_markdown_produces_no_chunks():
    assert chunk_markdown("dv-1", "docs/empty.md", " \n\n\t") == []


def test_non_positive_max_chars_is_rejected():
    with pytest.raises(ValueError, match="max_chars"):
        chunk_markdown("dv-1", "docs/a.md", "# A\n\nBody", max_chars=0)


def test_identity_normalizes_line_endings_and_trailing_whitespace():
    assert content_fingerprint("first  \r\n\r\nsecond") == content_fingerprint(
        "first\n\nsecond"
    )


def test_logical_key_and_chunk_id_include_structural_position():
    logical_key = build_logical_chunk_key(
        "docs/spring.md",
        ("Spring", "Virtual Threads"),
    )
    first_id = build_chunk_id(
        "dv-1",
        "docs/spring.md",
        ("Spring", "Virtual Threads"),
        "content-hash",
    )
    duplicate_id = build_chunk_id(
        "dv-1",
        "docs/spring.md",
        ("Spring", "Virtual Threads"),
        "content-hash",
        occurrence=2,
    )

    assert logical_key == "docs/spring.md#spring/virtual-threads"
    assert first_id != duplicate_id
