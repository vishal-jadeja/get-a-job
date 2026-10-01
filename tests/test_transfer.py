import base64
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from jobpilot.server import App, handler_class
from jobpilot.store import Store
from jobpilot.transfer import stage_backup, active_directory
from test_core import PROFILE, JOB


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = App(Store(self.root / 'source'))
        self.source.store.save_profile(PROFILE)
        self.source.store.save_resume('default.txt', base64.b64encode(b'Original resume').decode())
        self.source.store.upsert_jobs([JOB])
        self.source.workspace.save_resume('backend.txt', base64.b64encode(b'Career evidence').decode())
        self.target = App(Store(self.root / 'target'))

    def tearDown(self):
        self.tmp.cleanup()

    def encoded(self):
        return base64.b64encode(self.source.workspace.backup()).decode()

    def test_stage_preserves_files_and_history_without_activating(self):
        jid = self.source.store.jobs()[0]['id']
        self.source.store.action(jid, 'prepare')
        self.source.store.action(jid, 'approve')
        directory, preview = stage_backup(self.encoded(), self.target.data_root, self.target.store)
        self.assertEqual(preview['jobs'], 1)
        self.assertEqual(preview['resumes'], 1)
        restored = App(Store(directory))
        self.assertEqual(restored.store.job(jid)['status'], 'prepared')
        self.assertIsNone(restored.store.job(jid)['approval'])
        self.assertFalse(restored.store.setting('automation')['enabled'])
        self.assertNotEqual(restored.store.setting('token'), self.source.store.setting('token'))
        self.assertEqual(active_directory(self.target.data_root), self.target.data_root)
        self.assertEqual(self.target.store.jobs(), [])

    def test_submission_contacts_tasks_and_resume_survive(self):
        jid = self.source.store.jobs()[0]['id']
        self.source.store.action(jid, 'submitted_manual', 'Confirmed in fixture portal')
        self.source.workspace.save_record('contacts', {'name': 'Fixture recruiter', 'job_id': jid})
        self.source.workspace.save_record('tasks', {'title': 'Follow up', 'job_id': jid, 'due_on': '2026-10-15'})
        directory, _ = stage_backup(self.encoded(), self.target.data_root, self.target.store)
        restored = App(Store(directory))
        self.assertEqual(restored.store.job(jid)['status'], 'submitted')
        self.assertEqual(restored.store.job(jid)['submitted_at'], self.source.store.job(jid)['submitted_at'])
        self.assertEqual(restored.store.job(jid)['events'], self.source.store.job(jid)['events'])
        self.assertEqual((directory / 'resume.bin').read_bytes(), b'Original resume')
        self.assertEqual(restored.workspace.state()['contacts'][0]['name'], 'Fixture recruiter')
        self.assertEqual(restored.workspace.state()['tasks'][0]['title'], 'Follow up')

    def test_corrupt_resume_does_not_touch_current_workspace(self):
        original = zipfile.ZipFile(io.BytesIO(base64.b64decode(self.encoded())))
        content = io.BytesIO()
        with original, zipfile.ZipFile(content, 'w') as archive:
            for name in original.namelist():
                archive.writestr(name, b'changed' if name == 'resume.bin' else original.read(name))
        with self.assertRaisesRegex(ValueError, 'résumé is missing or damaged'):
            stage_backup(base64.b64encode(content.getvalue()).decode(), self.target.data_root, self.target.store)
        self.assertEqual(active_directory(self.target.data_root), self.target.data_root)

    def test_rejects_paths_and_unexpected_database_schema(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('../jobpilot.sqlite3', b'bad')
        with self.assertRaises(ValueError):
            stage_backup(base64.b64encode(archive.getvalue()).decode(), self.target.data_root, self.target.store)
        with self.source.store.db() as db:
            db.execute('CREATE VIEW surprise AS SELECT * FROM settings')
        with self.assertRaisesRegex(ValueError, 'format differs'):
            stage_backup(self.encoded(), self.target.data_root, self.target.store)
        self.assertEqual(list((self.target.data_root / 'restored').iterdir()), [])

    def test_http_preview_restore_token_rotation_and_restart(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class(self.target))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        token = self.target.store.setting('token')
        def request(path, data):
            req = Request(f'http://127.0.0.1:{server.server_port}/api/'+path,
                          data=json.dumps(data).encode(), headers={'Authorization': 'Bearer '+token})
            with urlopen(req) as response: return json.load(response)
        try:
            with self.assertRaises(HTTPError) as error:
                request('backup/restore', {'confirm': True})
            self.assertEqual(error.exception.code, 400)
            preview = request('backup/preview', {'base64': self.encoded()})
            self.assertEqual(self.target.store.jobs(), [])
            self.target.sync_lock.acquire()
            with self.assertRaises(HTTPError) as error:
                request('backup/restore', {'restore_id':preview['restore_id'], 'confirm':True})
            self.assertEqual(error.exception.code, 400)
            self.target.sync_lock.release()
            result = request('backup/restore', {'restore_id':preview['restore_id'], 'confirm':True})
            self.assertTrue(Path(result['previous_backup']).is_file())
            with self.assertRaises(HTTPError) as error:
                request('backup/restore', {'restore_id':preview['restore_id'], 'confirm':True})
            self.assertEqual(error.exception.code, 401)
            restarted = App(Store(active_directory(self.target.data_root)))
            self.assertEqual(len(restarted.store.jobs()), 1)
            self.assertEqual(restarted.store.setting('profile')['name'], PROFILE['name'])
            self.assertEqual(len(restarted.workspace.state()['resumes']), 1)
            self.assertFalse(restarted.gmail.status()['connected'])
        finally:
            server.shutdown();server.server_close()
