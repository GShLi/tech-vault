from typing import Optional

from backend.app.rag.domain.models import (
    AuthorizationContext,
    Chunk,
    ChunkStatus,
    DocumentStatus,
    RetrievalFilters,
    Role,
    Visibility,
)


_DENIED = "permission denied"


def _require_identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PermissionError(_DENIED)
    return value


def _require_scope(
    context: AuthorizationContext,
    team_id: str,
    knowledge_base_id: Optional[str],
) -> None:
    _require_identifier(context.user_id)
    try:
        Role(context.role)
    except (TypeError, ValueError):
        raise PermissionError(_DENIED)
    if _require_identifier(team_id) not in context.team_ids:
        raise PermissionError(_DENIED)

    if knowledge_base_id is not None:
        if _require_identifier(knowledge_base_id) not in context.knowledge_base_ids:
            raise PermissionError(_DENIED)


def assert_may_view_document(
    context: AuthorizationContext,
    *,
    owner_user_id: str,
    team_id: str,
    visibility: Visibility,
    knowledge_base_id: Optional[str] = None,
    document_id: Optional[str] = None,
) -> None:
    """Raise PermissionError unless the authenticated context may view the document."""
    _require_scope(context, team_id, knowledge_base_id)

    try:
        normalized_visibility = Visibility(visibility)
    except (TypeError, ValueError):
        raise PermissionError(_DENIED)

    if normalized_visibility is Visibility.TEAM_SHARED:
        return

    if normalized_visibility is Visibility.PRIVATE:
        if _require_identifier(owner_user_id) == context.user_id:
            return
        if (
            document_id is not None
            and _require_identifier(document_id) in context.explicit_document_grants
        ):
            return

    raise PermissionError(_DENIED)


def assert_may_view_chunk(context: AuthorizationContext, chunk: Chunk) -> None:
    """Apply document authorization and reject chunks that are not retrievable."""
    try:
        document_status = DocumentStatus(chunk.doc_status)
        chunk_status = ChunkStatus(chunk.chunk_status)
    except (TypeError, ValueError):
        raise PermissionError(_DENIED)

    if document_status is not DocumentStatus.ACTIVE:
        raise PermissionError(_DENIED)
    if chunk_status is not ChunkStatus.ENABLED:
        raise PermissionError(_DENIED)

    assert_may_view_document(
        context,
        owner_user_id=chunk.owner_user_id,
        team_id=chunk.team_id,
        knowledge_base_id=chunk.knowledge_base_id,
        document_id=chunk.document_id,
        visibility=chunk.visibility,
    )


def build_retrieval_filters(
    context: AuthorizationContext,
    requested_filters: RetrievalFilters,
) -> RetrievalFilters:
    """Build effective filters without allowing request input to widen the scope."""
    _require_identifier(context.user_id)

    if requested_filters.viewer_user_id != context.user_id:
        raise PermissionError(_DENIED)
    if requested_filters.team_id not in context.team_ids:
        raise PermissionError(_DENIED)

    requested_knowledge_bases = tuple(requested_filters.knowledge_base_ids)
    if not requested_knowledge_bases:
        raise PermissionError(_DENIED)
    if any(
        knowledge_base_id not in context.knowledge_base_ids
        for knowledge_base_id in requested_knowledge_bases
    ):
        raise PermissionError(_DENIED)

    requested_grants = tuple(requested_filters.explicit_document_grants)
    context_grants = tuple(context.explicit_document_grants)
    if requested_grants:
        if any(grant not in context_grants for grant in requested_grants):
            raise PermissionError(_DENIED)
        explicit_document_grants = requested_grants
    else:
        explicit_document_grants = context_grants

    return RetrievalFilters(
        team_id=requested_filters.team_id,
        knowledge_base_ids=requested_knowledge_bases,
        viewer_user_id=context.user_id,
        product=requested_filters.product,
        version_values=tuple(requested_filters.version_values),
        include_private_owned_by_viewer=(
            requested_filters.include_private_owned_by_viewer
        ),
        explicit_document_grants=explicit_document_grants,
    )
