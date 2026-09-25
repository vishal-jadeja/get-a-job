import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
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
        except HTTPError as e:return e.code,e.read(),e.headers

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


if __name__=='__main__':unittest.main()
