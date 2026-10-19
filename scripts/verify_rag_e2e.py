import json, time
from fastapi.testclient import TestClient
from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app

engine = build_engine('sqlite+pysqlite:///:memory:')
create_schema(engine)
factory = build_session_factory(engine)
settings = Settings(environment='test', jwt_secret='test-secret-at-least-32-bytes-long', allow_registration=True, allow_legacy_team_creation=True, enable_indexing=True, es_url='http://127.0.0.1:59200', qdrant_url='http://127.0.0.1:56333', embedding_url='http://127.0.0.1:58001')
app = create_app(settings=settings, session_factory=factory)
with TestClient(app) as client:
    login = client.post('/api/v1/auth/login', json={'email':'admin@techvault.local','password':'ChangeMe-123!'})
    assert login.status_code == 200, login.text
    h={'Authorization':'Bearer '+login.json()['data']['access_token']}
    team = client.post('/api/v1/teams/create', json={'name':'E2E'}, headers=h).json()['data']
    kb = client.post('/api/v1/kbs/create', json={'team_id':team['id'],'name':'E2E KB'}, headers=h).json()['data']
    upload = client.post('/api/v1/docs/upload', data={'team_id':team['id'],'kb_id':kb['id']}, files={'file':('guide.md', b'# Virtual Threads\n\nVirtual threads are lightweight Java threads.\n\n## Scheduling\n\nThe JVM schedules virtual threads on carrier threads.\n')}, headers=h)
    print('upload', upload.status_code, upload.text[:300])
    assert upload.status_code == 202
    doc = upload.json()['data']['document']
    chunks = client.get('/api/v1/chunks', params={'team_id':team['id'],'document_id':doc['id']}, headers=h)
    print('chunks', chunks.status_code, len(chunks.json().get('data', [])))
    chat = client.post('/api/v1/chats/create', json={'team_id':team['id'],'title':'E2E chat','knowledge_base_ids':[kb['id']]}, headers=h).json()['data']
    ask = client.post('/api/v1/chats/ask', json={'team_id':team['id'],'chat_id':chat['id'],'question':'What are virtual threads?','stream':False}, headers=h)
    print('ask', ask.status_code, ask.text[:600])
    assert ask.status_code == 200, ask.text
    body = ask.json()['data']
    assert body['citations'], 'expected citations'
    print('e2e OK', body['status'], len(body['citations']))
