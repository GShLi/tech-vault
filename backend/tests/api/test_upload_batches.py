from dataclasses import replace

import pytest
from sqlalchemy import select

from backend.app.db.models import Document, IngestionRun, PreparedIngestion, UploadBatch, UploadBatchFile, IndexGenerationRecord
from backend.app.rag.domain.models import ValidationResult
from backend.tests.api.conftest import admin_headers_for, create_user_as_admin, login_headers


@pytest.fixture
def context(api_client):
    headers = admin_headers_for(api_client)
    team = api_client.post('/api/v1/teams/create', json={'name': 'Batch Team'}, headers=headers).json()['data']
    kb = api_client.post('/api/v1/kbs/create', json={'team_id': team['id'], 'name': 'Batch KB'}, headers=headers).json()['data']
    return headers, team, kb


def create(client, context, count=2, **extra):
    headers, team, kb = context
    body = {'team_id': team['id'], 'kb_id': kb['id'], 'client_id': 'request-1',
            'files': [{'client_id': str(i), 'file_name': f'java-{i}.md', 'size_bytes': len(content(i))} for i in range(count)], **extra}
    response = client.post('/api/v1/upload-batches/create', json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()['data'], body


def content(index):
    return f'# Java {index}\n\nJava records are immutable data carriers.\n'.encode()


def upload(client, context, batch, index):
    headers, team, kb = context
    return client.post('/api/v1/docs/upload', headers=headers,
        data={'team_id': team['id'], 'kb_id': kb['id'], 'batch_id': batch['id'], 'batch_file_id': str(index)},
        files={'file': (f'java-{index}.md', content(index), 'text/markdown')})


def seal(client, context, batch):
    return client.post('/api/v1/upload-batches/seal', headers=context[0],
                       json={'team_id': context[1]['id'], 'batch_id': batch['id']})


def test_manifest_and_file_retries_are_idempotent(api_client, api_app, context):
    batch, body = create(api_client, context)
    assert api_client.post('/api/v1/upload-batches/create', json=body, headers=context[0]).json()['data']['id'] == batch['id']
    first = upload(api_client, context, batch, 0)
    again = upload(api_client, context, batch, 0)
    assert first.status_code == again.status_code == 202
    assert first.json()['data']['ingestion_run_id'] == again.json()['data']['ingestion_run_id']
    with api_app.state.session_factory() as session:
        assert session.query(Document).count() == 1
        assert session.query(IngestionRun).one().status == 'queued'
    body['files'][0]['file_name'] = 'different.md'
    assert api_client.post('/api/v1/upload-batches/create', json=body, headers=context[0]).status_code == 409
    result = seal(api_client, context, batch)
    assert result.status_code == 202, result.text
    assert result.json()['data']['counts'] == {'completed': 1, 'upload_failed': 1}
    assert upload(api_client, context, batch, 1).status_code == 202
    assert seal(api_client, context, batch).json()['data']['counts'] == {'completed': 2}


def test_200_documents_publish_in_groups_and_reuse_vectors(api_client, api_app, context, monkeypatch):
    from backend.app.rag.embedding.service import EmbeddingClient, hash_embedding
    staged, embedded = {}, []
    class Writer:
        async def stage(self, generation, chunks): staged[generation] = len(chunks)
        async def validate(self, generation): return ValidationResult(True, (), staged[generation])
        async def activate(self, generation): pass
    monkeypatch.setattr('backend.app.rag.ingestion.processor.build_index_writers', lambda *_: [Writer()])
    def embed(self, texts):
        embedded.extend(texts)
        return [hash_embedding(text) for text in texts]
    monkeypatch.setattr(EmbeddingClient, 'embed', embed)
    api_app.state.settings = replace(api_app.state.settings, enable_indexing=True)
    batch, _ = create(api_client, context, 200)
    for index in range(200):
        response = upload(api_client, context, batch, index)
        assert response.status_code == 202, response.text
    result = seal(api_client, context, batch)
    assert result.status_code == 202, result.text
    assert result.json()['data']['counts'] == {'completed': 200}
    assert len(staged) == 10
    assert list(staged.values()) == list(range(20, 201, 20))
    assert len(embedded) == 200
    with api_app.state.session_factory() as session:
        assert session.query(PreparedIngestion).count() == 0
        assert session.scalar(select(IndexGenerationRecord).where(IndexGenerationRecord.status == 'active')).chunk_count == 200


def test_batch_permissions_and_limits(api_client, context):
    headers, team, kb = context
    batch, body = create(api_client, context)
    user = create_user_as_admin(api_client, headers, team['id'], 'batch-other@example.com')['user']
    other = login_headers(api_client, 'batch-other@example.com')
    api_client.post('/api/v1/kbs/members/update', headers=headers,
                    json={'team_id': team['id'], 'kb_id': kb['id'], 'user_ids': [user['id']]})
    response = api_client.get('/api/v1/upload-batches/detail', headers=other,
                              params={'team_id': team['id'], 'batch_id': batch['id']})
    assert response.status_code == 404
    # The uploader also loses batch access if removed from the knowledge base.
    assert api_client.get('/api/v1/upload-batches/detail', headers=headers,
                         params={'team_id': team['id'], 'batch_id': batch['id']}).status_code == 404


def test_count_size_and_file_manifest_validation(api_client, context):
    batch, body = create(api_client, context)
    oversized = {**body, 'client_id': 'too-many', 'files': [
        {'client_id': str(i), 'file_name': f'{i}.md', 'size_bytes': 1} for i in range(201)]}
    assert api_client.post('/api/v1/upload-batches/create', headers=context[0], json=oversized).status_code == 413
    oversized['files'] = [{'client_id': str(i), 'file_name': f'{i}.md', 'size_bytes': 50 * 1024 * 1024} for i in range(50)]
    assert api_client.post('/api/v1/upload-batches/create', headers=context[0], json=oversized).status_code == 413
    response = api_client.post('/api/v1/docs/upload', headers=context[0],
        data={'team_id': context[1]['id'], 'kb_id': context[2]['id'], 'batch_id': batch['id'], 'batch_file_id': '0'},
        files={'file': ('java-0.md', b'wrong size', 'text/markdown')})
    assert response.status_code == 409


def test_resume_prepared_checkpoint_and_skip_cancelled(api_client, api_app, context):
    from backend.app.rag.ingestion.processor import process_document
    batch, _ = create(api_client, context)
    upload(api_client, context, batch, 0)
    upload(api_client, context, batch, 1)
    with api_app.state.session_factory() as session:
        items = session.scalars(select(UploadBatchFile).order_by(UploadBatchFile.client_id)).all()
        doc, run = session.get(Document, items[0].document_id), session.get(IngestionRun, items[0].run_id)
        process_document(doc, run, session, api_app.state.settings, prepare_only=True)
        assert session.get(PreparedIngestion, run.id)
        # Removing the raw input demonstrates publication resumes from its checkpoint.
        doc.source_uri = '/does-not-exist'
        cancelled = session.get(IngestionRun, items[1].run_id)
        cancelled.status = cancelled.current_stage = 'cancelled'
        session.commit()
    result = seal(api_client, context, batch)
    assert result.json()['data']['counts'] == {'completed': 1, 'cancelled': 1}


def test_github_endpoints_are_removed(api_client):
    for path in ('/sources', '/sources/detail', '/sources/github/create', '/sources/sync', '/credentials', '/credentials/create'):
        response = api_client.post('/api/v1' + path) if path.endswith(('create', 'sync')) else api_client.get('/api/v1' + path)
        assert response.status_code == 404


def test_recent_tasks_and_document_search_are_kb_scoped(api_client, context):
    batch, _ = create(api_client, context)
    upload(api_client, context, batch, 0)
    headers, team, _kb = context
    other = api_client.post('/api/v1/kbs/create', headers=headers, json={'team_id': team['id'], 'name': 'Other'}).json()['data']
    assert api_client.get('/api/v1/ingestions', headers=headers, params={'team_id': team['id'], 'kb_id': other['id']}).json()['data'] == []
    rows = api_client.get('/api/v1/ingestions', headers=headers, params={'team_id': team['id'], 'kb_id': batch['kb_id']}).json()['data']
    assert rows[0]['file_name'] == 'java-0.md'
    assert api_client.get('/api/v1/docs', headers=headers, params={'team_id': team['id'], 'kb_id': batch['kb_id'], 'q': 'not-there'}).json()['data'] == []


def test_failed_publication_retries_are_bounded_and_reuse_prepared_chunks(api_client, api_app, context, monkeypatch):
    from backend.app.rag.embedding.service import EmbeddingClient, hash_embedding
    attempts, embedded = [], []
    def embed(self, texts):
        embedded.extend(texts)
        return [hash_embedding(text) for text in texts]
    def fail(*args):
        attempts.append(1)
        raise RuntimeError('index unavailable')
    monkeypatch.setattr(EmbeddingClient, 'embed', embed)
    monkeypatch.setattr('backend.app.modules.documents.batch_processing.publish_prepared', fail)
    batch, _ = create(api_client, context, 2)
    upload(api_client, context, batch, 0)
    upload(api_client, context, batch, 1)
    result = seal(api_client, context, batch)
    assert result.status_code == 202, result.text
    assert result.json()['data']['counts'] == {'failed': 2}
    assert len(attempts) == 4
    assert len(embedded) == 2
    with api_app.state.session_factory() as session:
        assert {item.processing_retries for item in session.scalars(select(UploadBatchFile))} == {4}
        assert session.query(PreparedIngestion).count() == 2
        assert session.query(IndexGenerationRecord).count() == 0
    from backend.app.rag.ingestion.processor import publish_prepared
    monkeypatch.setattr('backend.app.modules.documents.batch_processing.publish_prepared', publish_prepared)
    result = api_client.post('/api/v1/upload-batches/retry', headers=context[0],
                            json={'team_id': context[1]['id'], 'batch_id': batch['id']})
    assert result.json()['data']['counts'] == {'completed': 2}
    assert len(embedded) == 2


def test_derived_ingestion_data_expires_and_is_removed_on_document_purge(api_client, api_app, context):
    from datetime import timedelta
    from backend.app.db.models import EmbeddingCache, utc_now
    from backend.app.modules.documents.lifecycle import purge_document_record, purge_expired_documents_record
    batch, _ = create(api_client, context, 1)
    upload(api_client, context, batch, 0)
    seal(api_client, context, batch)
    with api_app.state.session_factory() as session:
        item = session.scalar(select(UploadBatchFile))
        document = session.get(Document, item.document_id)
        cache = session.scalar(select(EmbeddingCache))
        assert cache.team_id == context[1]['id']
        cache.created_at = utc_now() - timedelta(days=8)
        session.commit()
        purge_expired_documents_record(session, api_app.state.settings)
        assert session.query(EmbeddingCache).count() == 0
        session.add(EmbeddingCache(key='purge-fixture', team_id=context[1]['id'], vector='[]', token_count=0))
        session.add(PreparedIngestion(run_id=item.run_id, payload='{}'))
        document.deleted_at = utc_now()
        document.doc_status = 'deleted'
        session.commit()
        purge_document_record(session, document, api_app.state.settings)
        session.commit()
        assert session.query(PreparedIngestion).count() == 0
        assert session.query(EmbeddingCache).count() == 0
