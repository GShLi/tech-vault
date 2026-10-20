"""GitHub source discovery and ingestion into the document pipeline."""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import json
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.storage import store_file
from backend.app.core.config import Settings
from backend.app.core.ids import new_ulid
from backend.app.core.secrets import decrypt_secret
from backend.app.db.models import (
    AuditLog,
    ChunkRecord,
    Credential,
    Document,
    DocumentVersion,
    IngestionRun,
    IndexGenerationRecord,
    SourceConnection,
)
from backend.app.rag.indexing.maintenance import delete_document_from_indexes
from backend.app.rag.ingestion.processor import process_markdown


_SUPPORTED_SUFFIXES = frozenset({".md", ".txt"})
_MAX_FILES_PER_SYNC = 500
_MAX_FILE_BYTES = 50 * 1024 * 1024
_GITHUB_API_URL = "https://api.github.com"
_REPOSITORY_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitHubSyncError(Exception):
    """An expected GitHub synchronization failure."""

    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return self.owner + "/" + self.name


@dataclass(frozen=True)
class GitHubTreeFile:
    path: str
    sha: str
    size: int


@dataclass(frozen=True)
class GitHubSnapshot:
    commit_sha: str
    files: Tuple[GitHubTreeFile, ...]
    files_seen: int


@dataclass(frozen=True)
class GitHubSyncSummary:
    source_id: str
    status: str
    cursor: str
    files_seen: int
    documents_created: int
    documents_updated: int
    documents_unchanged: int
    documents_deleted: int
    documents_failed: int

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "cursor": self.cursor,
            "files_seen": self.files_seen,
            "documents_created": self.documents_created,
            "documents_updated": self.documents_updated,
            "documents_unchanged": self.documents_unchanged,
            "documents_deleted": self.documents_deleted,
            "documents_failed": self.documents_failed,
        }


def parse_github_repository(repo_url: str) -> GitHubRepository:
    """Parse HTTPS and GitHub SSH repository URLs without accepting subpaths."""
    value = (repo_url or "").strip()
    owner = ""
    name = ""

    if value.startswith("git@github.com:"):
        path = value[len("git@github.com:") :]
        parts = path.rstrip("/").split("/")
        if len(parts) == 2:
            owner, name = parts
    else:
        parsed = urlparse(value)
        if parsed.scheme in {"https", "http", "ssh"} and parsed.hostname in {
            "github.com",
            "www.github.com",
        }:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 2:
                owner, name = parts

    if name.endswith(".git"):
        name = name[:-4]
    if (
        not owner
        or not name
        or not _REPOSITORY_PART.fullmatch(owner)
        or not _REPOSITORY_PART.fullmatch(name)
        or name in {".", ".."}
    ):
        raise GitHubSyncError(
            "SOURCE_INVALID_REPOSITORY",
            "repo_url must identify a GitHub repository such as "
            "https://github.com/owner/repository.",
            400,
        )
    return GitHubRepository(owner=owner, name=name)


def parse_path_filters(raw: Optional[str]) -> Tuple[str, ...]:
    if not raw:
        return ()
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as error:
        raise GitHubSyncError(
            "SOURCE_INVALID_PATH_FILTER",
            "path_filters must be a JSON array of strings.",
            400,
        ) from error
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise GitHubSyncError(
            "SOURCE_INVALID_PATH_FILTER",
            "path_filters must be a JSON array of strings.",
            400,
        )
    normalized = tuple(item.strip().replace("\\", "/") for item in values if item.strip())
    return normalized


def _matches_path(path: str, filters: Iterable[str]) -> bool:
    values = tuple(filters)
    if not values:
        return True
    for pattern in values:
        if pattern.endswith("/") and path.startswith(pattern):
            return True
        if fnmatch.fnmatchcase(path, pattern):
            return True
    return False


class GitHubClient:
    """Minimal GitHub REST client used by the source synchronizer."""

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: str = _GITHUB_API_URL,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token or os.getenv("TECHVAULT_GITHUB_TOKEN")
        self._transport = transport
        self._timeout = timeout

    def fetch_snapshot(
        self,
        repository: GitHubRepository,
        branch: str,
        filters: Iterable[str],
    ) -> GitHubSnapshot:
        branch_path = "/repos/{0}/branches/{1}".format(
            repository.full_name,
            quote(branch, safe=""),
        )
        branch_payload = self._get_json(branch_path)
        commit = branch_payload.get("commit") or {}
        commit_sha = str(commit.get("sha") or "")
        tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
        if not commit_sha or not tree_sha:
            raise GitHubSyncError(
                "SOURCE_INVALID_GITHUB_RESPONSE",
                "GitHub did not return the branch commit and tree identifiers.",
            )

        tree_path = "/repos/{0}/git/trees/{1}".format(repository.full_name, tree_sha)
        tree_payload = self._get_json(tree_path, params={"recursive": "1"})
        if tree_payload.get("truncated"):
            raise GitHubSyncError(
                "SOURCE_TREE_TRUNCATED",
                "The GitHub repository tree is too large for a single synchronization.",
                413,
            )

        files: List[GitHubTreeFile] = []
        files_seen = 0
        for item in tree_payload.get("tree") or []:
            path = str(item.get("path") or "")
            sha = str(item.get("sha") or "")
            size = int(item.get("size") or 0)
            if item.get("type") != "blob" or not path or not sha:
                continue
            files_seen += 1
            if Path(path).suffix.lower() not in _SUPPORTED_SUFFIXES:
                continue
            if size > _MAX_FILE_BYTES or not _matches_path(path, filters):
                continue
            files.append(GitHubTreeFile(path=path, sha=sha, size=size))

        if len(files) > _MAX_FILES_PER_SYNC:
            raise GitHubSyncError(
                "SOURCE_TOO_MANY_FILES",
                "A synchronization may contain at most {0} supported files.".format(
                    _MAX_FILES_PER_SYNC
                ),
                413,
            )
        files.sort(key=lambda item: item.path)
        return GitHubSnapshot(
            commit_sha=commit_sha,
            files=tuple(files),
            files_seen=files_seen,
        )

    def read_file(self, repository: GitHubRepository, sha: str) -> bytes:
        payload = self._get_json(
            "/repos/{0}/git/blobs/{1}".format(repository.full_name, sha)
        )
        if payload.get("encoding") != "base64" or not payload.get("content"):
            raise GitHubSyncError(
                "SOURCE_INVALID_FILE_CONTENT",
                "GitHub returned unsupported blob content for {0}.".format(sha),
            )
        try:
            content = base64.b64decode(payload["content"])
        except (ValueError, TypeError) as error:
            raise GitHubSyncError(
                "SOURCE_INVALID_FILE_CONTENT",
                "GitHub returned invalid base64 content for {0}.".format(sha),
            ) from error
        if len(content) > _MAX_FILE_BYTES:
            raise GitHubSyncError(
                "SOURCE_FILE_TOO_LARGE",
                "A source file exceeds the 50 MB ingestion limit.",
                413,
            )
        return content

    def _get_json(self, path: str, params: Optional[dict] = None) -> dict:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "TechVault-Source-Sync",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token

        try:
            with httpx.Client(
                base_url=self._base_url,
                headers=headers,
                transport=self._transport,
                timeout=self._timeout,
            ) as client:
                response = client.get(path, params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 401:
                raise GitHubSyncError(
                    "SOURCE_AUTH_FAILED",
                    "GitHub rejected the configured credentials.",
                ) from error
            if status == 403:
                code = "SOURCE_RATE_LIMITED" if error.response.headers.get("x-ratelimit-remaining") == "0" else "SOURCE_AUTH_FAILED"
                raise GitHubSyncError(
                    code,
                    "GitHub denied access to the repository or rate-limited the request.",
                    503 if code == "SOURCE_RATE_LIMITED" else 502,
                ) from error
            if status == 404:
                raise GitHubSyncError(
                    "SOURCE_REPOSITORY_NOT_FOUND",
                    "The repository, branch, or requested Git object was not found.",
                    404,
                ) from error
            raise GitHubSyncError(
                "SOURCE_GITHUB_UNAVAILABLE",
                "GitHub returned HTTP {0}.".format(status),
            ) from error
        except (httpx.HTTPError, ValueError) as error:
            raise GitHubSyncError(
                "SOURCE_GITHUB_UNAVAILABLE",
                "GitHub could not be reached or returned invalid JSON.",
            ) from error

        if not isinstance(payload, dict):
            raise GitHubSyncError(
                "SOURCE_INVALID_GITHUB_RESPONSE",
                "GitHub returned an unexpected response.",
            )
        return payload


def build_github_client(
    source: SourceConnection, token: Optional[str] = None
) -> GitHubClient:
    """Build the default client; deployments may inject a transport in tests."""
    return GitHubClient(token=token or os.getenv("TECHVAULT_GITHUB_TOKEN"))


def _existing_documents(
    session: Session,
    source: SourceConnection,
    repository: GitHubRepository,
) -> Dict[str, Document]:
    prefix = repository.full_name + "/"
    rows = session.scalars(
        select(Document).where(
            Document.knowledge_base_id == source.kb_id,
            Document.source_type == "github",
            Document.file_name.startswith(prefix),
            Document.doc_status != "deleted",
        )
    ).all()
    return {document.file_name: document for document in rows}


def _content_fingerprint(session: Session, document: Document) -> str:
    if not document.current_version_id:
        return ""
    version = session.get(DocumentVersion, document.current_version_id)
    return version.content_fingerprint if version is not None else ""


def _ingest_file(
    session: Session,
    settings: Settings,
    source: SourceConnection,
    repository: GitHubRepository,
    item: GitHubTreeFile,
    content: bytes,
    existing: Optional[Document],
) -> bool:
    suffix = Path(item.path).suffix.lower()
    document_name = repository.full_name + "/" + item.path
    version_id = new_ulid()
    stored = store_file(BytesIO(content), version_id + suffix, version_id)

    if existing is None:
        document_id = new_ulid()
        document = Document(
            id=document_id,
            knowledge_base_id=source.kb_id,
            owner_user_id=source.created_by,
            file_name=document_name,
            source_type="github",
            source_uri=str(stored.path),
            version_values="[]",
            visibility="team_shared",
            data_classification="internal",
            doc_status="building",
            current_version_id=version_id,
        )
        session.add(document)
        session.flush()
    else:
        document = existing
        document.source_uri = str(stored.path)
        document.current_version_id = version_id
        document.version += 1
        document.doc_status = "building"

    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        content_fingerprint=item.sha,
        file_size_bytes=len(content),
        status="building",
    )
    run = IngestionRun(
        document_version_id=version_id,
        status="queued",
        current_stage="parsing",
        stage_progress_pct=0,
    )
    session.add_all([version, run])
    session.commit()

    chunk_ids = process_markdown(document, run, session, settings)
    return bool(chunk_ids) and run.status == "completed"


def _documents_for_source(session: Session, source: SourceConnection) -> List[Document]:
    repository = parse_github_repository(source.repo_url)
    prefix = repository.full_name + "/"
    return list(
        session.scalars(
            select(Document).where(
                Document.knowledge_base_id == source.kb_id,
                Document.source_type == "github",
                Document.file_name.startswith(prefix),
                Document.doc_status != "deleted",
            )
        ).all()
    )


def _retire_document(
    session: Session,
    settings: Settings,
    team_id: str,
    document: Document,
) -> None:
    """Remove every indexed generation before disabling the database rows."""

    chunks = session.scalars(
        select(ChunkRecord).where(ChunkRecord.document_id == document.id)
    ).all()
    generations = {
        chunk.index_generation for chunk in chunks if chunk.index_generation
    }
    active_generation = session.scalar(
        select(IndexGenerationRecord.id).where(
            IndexGenerationRecord.team_id == team_id,
            IndexGenerationRecord.status == "active",
        )
    )
    if active_generation:
        generations.add(active_generation)
    try:
        for generation_id in sorted(generations):
            asyncio.run(
                delete_document_from_indexes(
                    settings,
                    generation_id,
                    document.id,
                )
            )
    except Exception as error:
        raise GitHubSyncError(
            "SOURCE_INDEX_CLEANUP_FAILED",
            "Indexed content for the source document could not be removed.",
            503,
        ) from error

    document.doc_status = "deleted"
    document.deleted_at = document.updated_at
    for chunk in chunks:
        chunk.doc_status = "deleted"
        chunk.status = "disabled"
        chunk.chunk_status = "disabled"
    session.commit()


def remove_source_documents(
    source: SourceConnection,
    session: Session,
    settings: Settings,
) -> int:
    """Soft-delete a source's documents and remove their active index rows."""

    documents = _documents_for_source(session, source)
    for document in documents:
        _retire_document(session, settings, source.team_id, document)
    return len(documents)


def _record_sync_failure(
    session: Session,
    source: SourceConnection,
    code: str,
    message: str,
    cursor: Optional[str],
    failed_documents: int = 0,
) -> None:
    session.add(
        AuditLog(
            team_id=source.team_id,
            actor_id=source.created_by,
            action="source.sync.failed",
            resource_type="source_connection",
            resource_id=source.id,
            details=json.dumps(
                {
                    "error_code": code,
                    "message": message,
                    "cursor": cursor,
                    "failed_documents": failed_documents,
                },
                separators=(",", ":"),
            ),
        )
    )


def _mark_source_failed(
    session: Session,
    source_id: str,
    code: str,
    message: str,
    cursor: Optional[str],
    failed_documents: int = 0,
) -> None:
    session.rollback()
    source = session.get(SourceConnection, source_id)
    if source is None:
        return
    source.status = "error"
    source.sync_cursor = cursor
    _record_sync_failure(session, source, code, message, cursor, failed_documents)
    session.commit()


def sync_github_source(
    source: SourceConnection,
    session: Session,
    settings: Settings,
) -> GitHubSyncSummary:
    """Synchronize one source and return counters suitable for the API response."""
    source_id = source.id
    previous_cursor = source.sync_cursor
    try:
        return _sync_github_source(source, session, settings)
    except GitHubSyncError as error:
        _mark_source_failed(
            session,
            source_id,
            error.code,
            error.message,
            previous_cursor,
        )
        raise
    except Exception as error:
        _mark_source_failed(
            session,
            source_id,
            "SOURCE_SYNC_FAILED",
            "The GitHub source could not be synchronized.",
            previous_cursor,
        )
        raise GitHubSyncError(
            "SOURCE_SYNC_FAILED",
            "The GitHub source could not be synchronized.",
        ) from error


def _sync_github_source(
    source: SourceConnection,
    session: Session,
    settings: Settings,
) -> GitHubSyncSummary:
    repository = parse_github_repository(source.repo_url)
    filters = parse_path_filters(source.path_filters)
    previous_cursor = source.sync_cursor
    token = None
    if source.credentials_id:
        credential = session.get(Credential, source.credentials_id)
        if credential is None or not credential.secret_encrypted:
            raise GitHubSyncError(
                "SOURCE_AUTH_FAILED", "The source credential is unavailable."
            )
        try:
            token = decrypt_secret(credential.secret_encrypted, settings)
        except Exception as error:
            raise GitHubSyncError(
                "SOURCE_AUTH_FAILED", "The source credential could not be decrypted."
            ) from error
    client = build_github_client(source, token=token)
    snapshot = client.fetch_snapshot(repository, source.branch, filters)
    existing_documents = _existing_documents(session, source, repository)

    created = 0
    updated = 0
    unchanged = 0
    deleted = 0
    failed = 0
    failures: List[str] = []
    current_names = {
        repository.full_name + "/" + item.path for item in snapshot.files
    }

    for item in snapshot.files:
        document_name = repository.full_name + "/" + item.path
        existing = existing_documents.get(document_name)
        if existing is not None and _content_fingerprint(session, existing) == item.sha:
            unchanged += 1
            continue

        try:
            content = client.read_file(repository, item.sha)
        except GitHubSyncError as error:
            failed += 1
            failures.append(item.path + ": " + error.message)
            continue

        try:
            ingested = _ingest_file(
                session,
                settings,
                source,
                repository,
                item,
                content,
                existing,
            )
        except Exception as error:
            session.rollback()
            failed += 1
            failures.append(item.path + ": " + str(error))
            continue

        if not ingested:
            failed += 1
            failures.append(item.path + ": ingestion failed")
        elif existing is None:
            created += 1
        else:
            updated += 1

    for document_name, document in existing_documents.items():
        if document_name in current_names:
            continue
        try:
            _retire_document(session, settings, source.team_id, document)
            deleted += 1
        except GitHubSyncError as error:
            failed += 1
            failures.append(document_name + ": " + error.message)

    status = "error" if failed else "active"
    source.status = status
    source.sync_cursor = previous_cursor if failed else snapshot.commit_sha
    if failed:
        _record_sync_failure(
            session,
            source,
            "SOURCE_SYNC_FAILED",
            "; ".join(failures) or "One or more source documents failed.",
            source.sync_cursor,
            failed,
        )
    session.commit()
    return GitHubSyncSummary(
        source_id=source.id,
        status=status,
        cursor=source.sync_cursor or "",
        files_seen=snapshot.files_seen,
        documents_created=created,
        documents_updated=updated,
        documents_unchanged=unchanged,
        documents_deleted=deleted,
        documents_failed=failed,
    )
