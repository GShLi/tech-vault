"""Live Java corpus acceptance checks. Credentials are prompted, never recorded.

Run with --phase setup|upload|inspect|query. Results are append-only JSONL.
This creates real resources in the selected environment; use a dedicated database.
"""
import argparse
import getpass
import hashlib
import json
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


class Acceptance:
    def __init__(self, args):
        self.args = args
        args.output.mkdir(parents=True, exist_ok=True)
        self.state_path = args.output / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.client = httpx.Client(base_url=args.base_url, timeout=180, trust_env=False)

    def save(self):
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    def record(self, name, passed, **details):
        entry = {'at': datetime.now(timezone.utc).isoformat(), 'case': name,
                 'result': 'PASS' if passed else 'FAIL', **details}
        with (self.args.output / 'results.jsonl').open('a') as out:
            out.write(json.dumps(entry, ensure_ascii=False) + '\n')
        print(name, entry['result'], json.dumps(details, ensure_ascii=False)[:500], flush=True)

    def request(self, method, path, **kwargs):
        start = time.perf_counter()
        response = self.client.request(method, '/api/v1' + path, **kwargs)
        self.elapsed = round((time.perf_counter() - start) * 1000, 2)
        return response

    def login(self):
        password = os.getenv('TECHVAULT_TEST_PASSWORD') or getpass.getpass('Account password: ')
        response = self.request('POST', '/auth/login', json={'email': self.args.email, 'password': password})
        self.record('account_login', response.status_code == 200, status=response.status_code, latency_ms=self.elapsed)
        response.raise_for_status()
        data = response.json()['data']
        self.client.headers['Authorization'] = 'Bearer ' + data['access_token']
        self.state['user_id'] = data['user']['id']
        self.state['email'] = self.args.email
        self.save()

    def setup(self):
        response = self.request('GET', '/auth/me')
        self.record('account_context', response.status_code == 200, response=response.json())
        data = response.json()['data']
        memberships = data.get('memberships', [])
        self.state['team_id'] = self.args.team_id or next(m['team_id'] for m in memberships if m['role'] == 'leader')
        if not self.state.get('kb_id'):
            response = self.request('POST', '/kbs/create', json={
                'team_id': self.state['team_id'], 'name': 'Java 官方文档 · 生产验收 2026-10-21',
                'description': 'Java 21 / Virtual Threads / Records / Sealed Classes；真实依赖验收与故障记录。',
            })
            self.record('create_knowledge_base', response.status_code == 201, response=response.json(), latency_ms=self.elapsed)
            response.raise_for_status()
            self.state['kb_id'] = response.json()['data']['id']
            self.save()
        for path in ['/kbs', '/docs', '/ingestions']:
            response = httpx.get(self.args.base_url + '/api/v1' + path, params={'team_id': self.state['team_id']}, trust_env=False)
            self.record('anonymous_denied_' + path, response.status_code == 401, status=response.status_code)
        response = self.request('GET', '/ready')
        expected = 503 if self.args.expect_embedding_unavailable else 200
        self.record('readiness', response.status_code == expected,
                    expected_status=expected, status=response.status_code, response=response.json())
        for filename, content, mime in [
            ('java.exe', b'not executable', 'application/octet-stream'),
            ('java.pdf', b'%PDF-not-valid', 'text/plain'),
            ('../escape.md', b'# Java\n\npath test', 'text/markdown'),
        ]:
            response = self.request('POST', '/docs/upload', data={'team_id': self.state['team_id'], 'kb_id': self.state['kb_id']},
                                    files={'file': (filename, content, mime)})
            self.record('reject_' + filename, response.status_code == 400, status=response.status_code, response=response.json())
        for path in ['/providers', '/model-policy']:
            response = self.request('GET', path, params={'team_id': self.state['team_id']})
            payload = response.json()
            # Provider lists expose only masks by contract; never persist any key field.
            def clean(value):
                if isinstance(value, dict):
                    return {k: clean(v) for k, v in value.items() if not any(t in k.lower() for t in ['key', 'token', 'secret', 'password'])}
                if isinstance(value, list):
                    return [clean(v) for v in value]
                return value
            self.record('configuration_' + path, response.status_code == 200, response=clean(payload))

    def upload(self):
        manifest = json.loads((self.args.corpus / 'manifest.json').read_text())
        self.state.setdefault('documents', [])
        existing = {d['file'] for d in self.state['documents']}
        for item in manifest:
            if item['file'] in existing or (self.args.file and item['file'] != self.args.file):
                continue
            path = self.args.corpus / item['file']
            mime = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            with path.open('rb') as stream:
                response = self.request('POST', '/docs/upload', data={
                    'team_id': self.state['team_id'], 'kb_id': self.state['kb_id'],
                    'product': 'Java', 'version_values': '21', 'data_classification': 'public',
                }, files={'file': (path.name, stream, mime)})
            self.record('upload_' + path.name, response.status_code == 202, status=response.status_code,
                        latency_ms=self.elapsed, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), response=response.json())
            if response.status_code == 202:
                data = response.json()['data']
                self.state['documents'].append({'file': path.name, 'upload': data, 'source': item['source']})
                self.save()

    def inspect(self):
        for item in self.state.get('documents', []):
            data = item['upload']
            doc_id = data['document']['id']
            response = self.request('GET', '/docs/detail', params={'team_id': self.state['team_id'], 'document_id': doc_id})
            payload = response.json()
            self.record('document_' + item['file'], response.status_code == 200 and payload.get('data', {}).get('doc_status') == 'active', response=payload)
            item['detail'] = payload.get('data', {})
            response = self.request('GET', '/chunks', params={'team_id': self.state['team_id'], 'document_id': doc_id, 'limit': 100})
            payload = response.json()
            data = payload.get('data', [])
            rows = data if isinstance(data, list) else data.get('items', [])
            self.record('chunks_' + item['file'], response.status_code == 200 and bool(rows),
                        status=response.status_code, count=len(rows), response=payload)
            response = self.request('GET', '/docs/detail', params={'team_id': '0' * 26, 'document_id': doc_id})
            self.record('foreign_team_denied_' + item['file'], response.status_code in [403, 404], status=response.status_code)
        self.save()

    def query(self):
        response = self.request('GET', '/providers', params={'team_id': self.state['team_id']})
        payload = response.json()['data']
        providers = payload if isinstance(payload, list) else payload.get('items', [])
        models = [{'provider_id': p['id'], 'model_id': model}
                  for p in providers if p.get('status', 'active') == 'active'
                  for model in p['model_ids']]
        if self.args.provider_id:
            models = [m for m in models if m['provider_id'] == self.args.provider_id]
        if not models:
            raise RuntimeError('No active model matches the requested provider')
        selected = models[0]
        if not self.state.get('chat_id'):
            response = self.request('POST', '/chats/create', json={'team_id': self.state['team_id'],
                'title': 'Java 官方文档验收', 'knowledge_base_ids': [self.state['kb_id']]})
            response.raise_for_status()
            self.state['chat_id'] = response.json()['data']['id']
            self.save()
        questions = [
            'According to JEP 444, should virtual threads be pooled? Explain why and cite the document.',
            'Java record 的组件会自动生成哪些方法？record Point(int x, int y) 的访问器叫什么？请引用资料。',
            'Java sealed class 的直接子类必须使用哪些修饰符？请提供来源。',
            '这些 Java 文档是否说明了公司 2027 年的薪酬预算？没有依据请明确说明。',
        ]
        for question in questions:
            response = self.request('POST', '/chats/ask', json={
                'team_id': self.state['team_id'], 'chat_id': self.state['chat_id'],
                'question': question, 'provider_id': selected['provider_id'], 'model_id': selected['model_id'],
                'filters': {'knowledge_base_ids': [self.state['kb_id']]}, 'stream': False,
            })
            payload = response.json() if 'json' in response.headers.get('content-type', '') else {'text': response.text[:2000]}
            self.record('question', response.status_code == 200, question=question, latency_ms=self.elapsed,
                        status=response.status_code, response=payload)
            if response.status_code == 200:
                answer = payload.get('data', {})
                inline = set(re.findall(r'\[(c\d+)\]', answer.get('content', '')))
                available = {c['citation_id'] for c in answer.get('citations', [])}
                refused = answer.get('status') == 'refused'
                self.record('citation_integrity',
                            not (inline - available) and (bool(available) or refused),
                            question=question, inline_ids=sorted(inline),
                            citation_ids=sorted(available), status=answer.get('status'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['setup', 'upload', 'inspect', 'query'], required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--email', required=True)
    parser.add_argument('--team-id')
    parser.add_argument('--provider-id')
    parser.add_argument('--expect-embedding-unavailable', action='store_true',
                        help='Only set when intentionally checking readiness with the model service stopped')
    parser.add_argument('--file')
    parser.add_argument('--output', type=Path, default=Path('artifacts/java-acceptance-2026-10-21'))
    parser.add_argument('--corpus', type=Path, default=Path('data/java-acceptance/corpus'))
    args = parser.parse_args()
    suite = Acceptance(args)
    suite.login()
    getattr(suite, args.phase)()


if __name__ == '__main__':
    main()
