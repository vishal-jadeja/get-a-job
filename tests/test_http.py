import json
import base64
import io
import zipfile
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from jobpilot.server import App, handler_class
from jobpilot.store import Store
from test_core import PROFILE, JOB


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.store=Store(cls.tmp.name)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_class(App(cls.store)))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.token=cls.store.setting('token')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()

    def request(self,path,data=None,headers=None):
        headers={'Authorization':'Bearer '+self.token,**(headers or {})}
        req=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try:
            with urlopen(req) as r:return r.status,r.read(),r.headers
        except HTTPError as e:
            try:return e.code,e.read(),e.headers
            finally:e.close()

    def test_authentication_and_origin_checks(self):
        self.assertEqual(self.request('/api/state',headers={'Authorization':''})[0],401)
        self.assertEqual(self.request('/api/state',headers={'Origin':'https://evil.example'})[0],401)
        self.assertEqual(self.request('/api/state',headers={'Host':'evil.example'})[0],403)

    def test_full_review_and_submission_recording_workflow(self):
        self.assertEqual(self.request('/api/profile',PROFILE)[0],200)
        self.assertEqual(self.request('/api/import',{'jobs':[JOB]})[0],200)
        state=json.loads(self.request('/api/state')[1]);jid=state['jobs'][0]['id']
        for action in ['prepare','approve']:
            self.assertEqual(self.request(f'/api/jobs/{jid}/action',{'action':action})[0],200)
        status,data,headers=self.request(f'/api/jobs/{jid}/bundle')
        self.assertEqual(status,200);self.assertTrue(data.startswith(b'PK'))
        self.assertEqual(self.request(f'/api/jobs/{jid}/claim',{})[0],200)
        self.assertEqual(self.request(f'/api/jobs/{jid}/claim',{})[0],400)
        self.assertEqual(self.request(f'/api/jobs/{jid}/action',{'action':'submitting'})[0],200)
        self.assertEqual(self.request(f'/api/jobs/{jid}/action',{'action':'submitted','detail':'Fixture confirmation'})[0],200)
        self.assertEqual(len(json.loads(self.request('/api/queue')[1])),0)
        self.assertIn(b'submitted',self.request('/api/export.csv')[1])

    def test_no_arbitrary_files_and_security_headers(self):
        self.assertEqual(self.request('/data/jobpilot.sqlite3')[0],404)
        self.assertEqual(self.request('/../../etc/passwd')[0],404)
        code,body,headers=self.request('/')
        self.assertEqual(code,200)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertIn(b'JobPilot',body)

    def test_export_does_not_disclose_extension_token(self):
        body=self.request('/api/export')[1]
        self.assertNotIn(self.token.encode(),body)

    def test_unknown_routes_and_bad_input(self):
        self.assertEqual(self.request('/api/not-found')[0],404)
        self.assertEqual(self.request('/api/import',{'jobs':[]})[0],400)
        self.assertEqual(self.request('/api/sources',{'kind':'unknown','board':'x'})[0],400)

    def test_workspace_planning_and_download_routes(self):
        self.assertEqual(self.request('/api/workspace/tasks', {'title': 'Private task'}, headers={'Authorization': ''})[0], 401)
        code, body, _ = self.request('/api/workspace/tasks', {'title': 'API interview', 'kind': 'interview', 'due_on': '2026-12-01', 'time': '14:30'})
        self.assertEqual(code, 200)
        task = json.loads(body)
        self.assertEqual(self.request('/api/workspace/tasks', {'id': task['id'], 'done': True})[0], 200)
        self.assertEqual(self.request('/api/workspace/tasks', {'title': 'Invalid', 'due_on': 'bad'})[0], 400)
        self.assertEqual(self.request('/api/workspace/contacts', {'name': 'Recruiter', 'email': 'recruiter@example.com'})[0], 200)
        self.assertEqual(self.request('/api/workspace/searches', {'name': 'Remote', 'filters': {'query': 'Remote'}})[0], 200)
        self.assertEqual(self.request('/api/workspace/goal', {'goal': 15})[0], 200)
        state = json.loads(self.request('/api/state')[1])
        self.assertEqual(state['workspace']['weekly_goal'], 15)
        code, calendar, _ = self.request('/api/calendar.ics')
        self.assertEqual(code, 200)
        self.assertTrue(calendar.startswith(b'BEGIN:VCALENDAR'))
        code, archive, _ = self.request('/api/backup.zip')
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(archive)) as backup:
            self.assertIn('jobpilot.sqlite3', backup.namelist())
        for asset in ['/workspace.js', '/workspace.css']:
            self.assertEqual(self.request(asset)[0], 200)

    def test_selected_resume_claim_and_material_edit_flow(self):
        self.request('/api/profile', PROFILE)
        job = {**JOB, 'url': 'https://jobs.example/http-resume', 'external_id': 'http-resume'}
        self.assertEqual(self.request('/api/import', {'jobs': [job]})[0], 200)
        jid = next(j['id'] for j in json.loads(self.request('/api/state')[1])['jobs'] if j['external_id'] == 'http-resume')
        code, body, _ = self.request('/api/workspace/resumes', {'name': 'backend.txt', 'base64': base64.b64encode(b'Backend evidence').decode()})
        self.assertEqual(code, 200)
        self.assertEqual(self.request(f'/api/jobs/{jid}/resume', {'resume_id': json.loads(body)['id']})[0], 200)
        self.request(f'/api/jobs/{jid}/action', {'action': 'prepare'})
        self.assertEqual(self.request(f'/api/jobs/{jid}/materials', {'resume': 'My experience', 'cover_letter': 'My letter'})[0], 200)
        self.assertEqual(len(json.loads(self.request(f'/api/jobs/{jid}/versions')[1])), 2)
        self.assertEqual(self.request('/api/bundles', {'ids': [jid]})[0], 200)
        self.assertEqual(self.request(f'/api/jobs/{jid}/action', {'action': 'approve'})[0], 200)
        self.assertEqual(self.request('/api/application-queue', {'ids': [jid]})[0], 200)
        self.assertEqual([j['id'] for j in json.loads(self.request('/api/queue')[1])], [jid])
        code, body, _ = self.request(f'/api/jobs/{jid}/claim', {})
        self.assertEqual(code, 200)
        self.assertEqual(base64.b64decode(json.loads(body)['resume']['base64']), b'Backend evidence')
        self.assertEqual(self.request(f'/api/jobs/{jid}/materials', {'resume': 'changed', 'cover_letter': 'changed'})[0], 400)

    def test_firecrawl_previews_and_key_are_not_exported(self):
        self.assertEqual(self.request('/api/integrations/firecrawl', {'key': 'fc-fixture-key'})[0], 200)
        for path in ['/api/state', '/api/export']:
            self.assertNotIn(b'fc-fixture-key', self.request(path)[1])
        with patch('jobpilot.server.firecrawl.extract', return_value=JOB):
            code, body, _ = self.request('/api/web/extract', {'url': JOB['url']})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)['job']['title'], JOB['title'])
        with patch('jobpilot.server.firecrawl.search', side_effect=ValueError('Rate limit reached')):
            self.assertEqual(self.request('/api/web/search', {'query': 'Python jobs'})[0], 400)


if __name__=='__main__':unittest.main()
