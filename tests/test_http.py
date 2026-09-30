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
        cls.store.set_setting('networking', {'automatic': False, 'max_per_run': 5})
        cls.app = App(cls.store)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_class(cls.app))
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

    def test_zz_resume_preview_and_reviewed_merge(self):
        from test_import_matching import TEXT
        self.store.save_profile(PROFILE)
        code, body, _ = self.request('/api/resume/preview', {'name':'resume.txt','base64':base64.b64encode(TEXT.encode()).decode()})
        self.assertEqual(code, 200)
        self.assertEqual(self.store.setting('profile')['name'], PROFILE['name'])
        fields = json.loads(body)['fields']
        code, body, _ = self.request('/api/resume/merge', {'fields':{'skills':fields['skills'], 'projects':fields['projects']}})
        self.assertEqual(code, 200)
        self.assertIn(PROFILE['projects'][0], json.loads(body)['profile']['projects'])
        from jobpilot.skills import canonical
        merged = json.loads(body)['profile']['skills']
        self.assertEqual(len(merged), len({canonical(s) for s in merged}))
        self.assertEqual(self.request('/api/resume/merge', {'fields':{'needs_sponsorship':'yes'}})[0], 400)

    def test_zz_gmail_configuration_and_email_review_endpoints(self):
        from test_gmail import CLIENT, message
        self.store.save_profile(PROFILE)
        self.assertEqual(self.request('/api/gmail/configure',CLIENT,headers={'Authorization':''})[0], 401)
        self.assertEqual(self.request('/api/gmail/configure',CLIENT)[0], 200)
        code, body, _ = self.request('/api/gmail/connect',{})
        self.assertEqual(code, 200)
        self.assertIn('gmail.readonly', json.loads(body)['url'])
        self.assertNotIn('fixture-client-secret', self.request('/api/state')[1].decode())
        self.assertEqual(self.request('/api/gmail/sync',{})[0], 400)
        job = {**JOB,'url':'https://jobs.example/mail-api','external_id':'mail-api','company':'Mail Example'}
        self.store.upsert_jobs([job]); saved=next(j for j in self.store.jobs() if j['external_id']=='mail-api')
        self.app.mail.ingest('fixture@example.com',[message('api-mail',subject='Software Engineer at Mail Example',text='Thank you for applying for Software Engineer at Mail Example.')])
        event=json.loads(self.request('/api/mail')[1])['events'][0]
        self.assertEqual(self.request('/api/mail/review',{'id':event['id'],'action':'accept','job_id':saved['id'],'status':'submitted'})[0],200)
        self.assertEqual(self.store.job(saved['id'])['status'],'submitted')
        self.assertEqual(self.request('/api/mail/review',{'id':event['id'],'action':'dismiss'})[0],400)
        self.assertEqual(self.request('/api/gmail/disconnect',{})[0],200)

    def test_networking_candidates_drafts_and_contact_save(self):
        self.store.save_profile(PROFILE)
        job = {**JOB, 'url': 'https://jobs.example/networking', 'external_id': 'networking-fixture'}
        self.store.upsert_jobs([job])
        job = next(j for j in self.store.jobs() if j['url'] == 'https://jobs.example/networking')
        results = [{'url': 'https://www.linkedin.com/in/jane-networking-fixture',
                    'title': 'Jane Example - Software Engineer at Example Co', 'description': 'Public engineering profile at Example Co'}]
        with patch.object(self.app.networking, 'search', return_value=results):
            self.app.networking.lookup(job)
        code, body, _ = self.request(f"/api/jobs/{job['id']}/networking")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual(data['people'][0]['name'], 'Jane Example')
        payload = {'person_url': data['people'][0]['url']}
        code, body, _ = self.request(f"/api/jobs/{job['id']}/outreach", payload)
        self.assertEqual(code, 200)
        self.assertIn('Python', json.loads(body)['message'])
        first = json.loads(self.request(f"/api/jobs/{job['id']}/save-contact", payload)[1])
        second = json.loads(self.request(f"/api/jobs/{job['id']}/save-contact", payload)[1])
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['job_id'], job['id'])
        self.assertEqual(self.request(f"/api/jobs/{job['id']}/outreach", {'person_url': 'https://linkedin.com/in/unknown'})[0], 400)
        self.assertEqual(self.request('/api/networking/settings', {'automatic': False, 'max_per_run': 21})[0], 400)

    def test_yc_full_posting_route_retains_job_identity(self):
        from test_yc import ROW
        from jobpilot import yc
        job = yc.normalize(ROW)
        self.store.upsert_jobs([job])
        saved = next(j for j in self.store.jobs() if j['url'] == job['url'])
        full = {**job, 'description': 'Complete Python and SQL requirements', 'description_partial': False}
        with patch('jobpilot.server.yc.detail', return_value=(full, {}, [])):
            code, body, _ = self.request(f"/api/jobs/{saved['id']}/yc-details", {})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['id'], saved['id'])
        self.assertFalse(json.loads(body)['description_partial'])

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
