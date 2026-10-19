import pytest

from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DataClassification,
    DocumentStatus,
    RetrievalFilters,
    Role,
    Visibility,
    AuthorizationContext,
)


def _context(
    *,
    user_id: str = "user-b",
    team_ids=("team-a",),
    knowledge_base_ids=("kb-a",),
    role: Role = Role.MEMBER,
    explicit_document_grants=(),
) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=user_id,
        team_ids=tuple(team_ids),
        knowledge_base_ids=tuple(knowledge_base_ids),
        role=role,
        explicit_document_grants=tuple(explicit_document_grants),
    )


def _chunk(
    *,
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    team_id: str = "team-a",
    knowledge_base_id: str = "kb-a",
    owner_user_id: str = "user-a",
    visibility: Visibility = Visibility.PRIVATE,
    doc_status: DocumentStatus = DocumentStatus.ACTIVE,
    chunk_status: ChunkStatus = ChunkStatus.ENABLED,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version_id="dv-1",
        team_id=team_id,
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        visibility=visibility,
        data_classification=DataClassification.INTERNAL,
        source_path="docs/private.md",
        heading_path=("Private",),
        content="private content",
        logical_chunk_key="docs/private.md#private",
        content_hash="hash-1",
        doc_status=doc_status,
        chunk_status=chunk_status,
    )


def test_private_document_is_not_visible_to_another_member():
    from backend.app.core.authorization import assert_may_view_document

    with pytest.raises(PermissionError):
        assert_may_view_document(
            _context(),
            owner_user_id="user-a",
            team_id="team-a",
            knowledge_base_id="kb-a",
            document_id="doc-1",
            visibility=Visibility.PRIVATE,
        )


def test_administrator_does_not_automatically_see_private_documents():
    from backend.app.core.authorization import assert_may_view_document

    with pytest.raises(PermissionError):
        assert_may_view_document(
            _context(role=Role.ADMIN),
            owner_user_id="user-a",
            team_id="team-a",
            knowledge_base_id="kb-a",
            document_id="doc-1",
            visibility=Visibility.PRIVATE,
        )


def test_private_owner_can_view_own_document():
    from backend.app.core.authorization import assert_may_view_document

    assert_may_view_document(
        _context(user_id="user-a"),
        owner_user_id="user-a",
        team_id="team-a",
        knowledge_base_id="kb-a",
        document_id="doc-1",
        visibility=Visibility.PRIVATE,
    )


def test_explicit_document_grant_allows_private_document():
    from backend.app.core.authorization import assert_may_view_document

    assert_may_view_document(
        _context(explicit_document_grants=("doc-1",)),
        owner_user_id="user-a",
        team_id="team-a",
        knowledge_base_id="kb-a",
        document_id="doc-1",
        visibility=Visibility.PRIVATE,
    )


def test_explicit_grant_does_not_bypass_team_or_knowledge_base_scope():
    from backend.app.core.authorization import assert_may_view_document

    with pytest.raises(PermissionError):
        assert_may_view_document(
            _context(explicit_document_grants=("doc-1",)),
            owner_user_id="user-a",
            team_id="team-b",
            knowledge_base_id="kb-a",
            document_id="doc-1",
            visibility=Visibility.PRIVATE,
        )

    with pytest.raises(PermissionError):
        assert_may_view_document(
            _context(explicit_document_grants=("doc-1",)),
            owner_user_id="user-a",
            team_id="team-a",
            knowledge_base_id="kb-b",
            document_id="doc-1",
            visibility=Visibility.PRIVATE,
        )


def test_team_shared_document_requires_team_and_knowledge_base_scope():
    from backend.app.core.authorization import assert_may_view_document

    assert_may_view_document(
        _context(),
        owner_user_id="user-a",
        team_id="team-a",
        knowledge_base_id="kb-a",
        document_id="doc-1",
        visibility=Visibility.TEAM_SHARED,
    )

    with pytest.raises(PermissionError):
        assert_may_view_document(
            _context(),
            owner_user_id="user-a",
            team_id="team-a",
            knowledge_base_id="kb-b",
            document_id="doc-1",
            visibility=Visibility.TEAM_SHARED,
        )


def test_chunk_authorization_uses_document_grant_and_defaults_to_deny():
    from backend.app.core.authorization import assert_may_view_chunk

    assert_may_view_chunk(_context(explicit_document_grants=("doc-1",)), _chunk())

    with pytest.raises(PermissionError):
        assert_may_view_chunk(_context(), _chunk())


def test_chunk_authorization_denies_unavailable_chunks():
    from backend.app.core.authorization import assert_may_view_chunk

    with pytest.raises(PermissionError):
        assert_may_view_chunk(
            _context(user_id="user-a"),
            _chunk(doc_status=DocumentStatus.DELETING),
        )

    with pytest.raises(PermissionError):
        assert_may_view_chunk(
            _context(user_id="user-a"),
            _chunk(chunk_status=ChunkStatus.DISABLED),
        )


def test_build_retrieval_filters_preserves_narrow_scope_and_context_grants():
    from backend.app.core.authorization import build_retrieval_filters

    context = _context(
        team_ids=("team-a", "team-b"),
        knowledge_base_ids=("kb-a", "kb-b"),
        explicit_document_grants=("doc-1",),
    )
    requested = RetrievalFilters(
        team_id="team-a",
        knowledge_base_ids=("kb-a",),
        viewer_user_id="user-b",
        product="spring-boot",
        version_values=("3.2",),
        include_private_owned_by_viewer=False,
    )

    filters = build_retrieval_filters(context, requested)

    assert filters.team_id == "team-a"
    assert filters.knowledge_base_ids == ("kb-a",)
    assert filters.viewer_user_id == "user-b"
    assert filters.product == "spring-boot"
    assert filters.version_values == ("3.2",)
    assert filters.include_private_owned_by_viewer is False
    assert filters.explicit_document_grants == ("doc-1",)


def test_build_retrieval_filters_accepts_a_narrower_grant_subset():
    from backend.app.core.authorization import build_retrieval_filters

    context = _context(explicit_document_grants=("doc-1", "doc-2"))
    requested = RetrievalFilters(
        team_id="team-a",
        knowledge_base_ids=("kb-a",),
        viewer_user_id="user-b",
        explicit_document_grants=("doc-2",),
    )

    filters = build_retrieval_filters(context, requested)

    assert filters.explicit_document_grants == ("doc-2",)


@pytest.mark.parametrize(
    "requested",
    [
        RetrievalFilters(
            team_id="team-b",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-b",
        ),
        RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a", "kb-b"),
            viewer_user_id="user-b",
        ),
        RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-a",
        ),
        RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-b",
            explicit_document_grants=("doc-unauthorized",),
        ),
    ],
)
def test_build_retrieval_filters_rejects_attempts_to_widen_access(requested):
    from backend.app.core.authorization import build_retrieval_filters

    with pytest.raises(PermissionError):
        build_retrieval_filters(_context(), requested)


def test_administrator_cannot_widen_retrieval_scope():
    from backend.app.core.authorization import build_retrieval_filters

    requested = RetrievalFilters(
        team_id="team-a",
        knowledge_base_ids=("kb-a",),
        viewer_user_id="user-a",
    )

    with pytest.raises(PermissionError):
        build_retrieval_filters(_context(role=Role.ADMIN), requested)
