import io
import base64
import sqlite3
import tempfile
import unittest
import zipfile

from jobpilot.store import Store
from jobpilot.workspace import Workspace
from test_core import PROFILE, JOB


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile(PROFILE)
        self.store.upsert_jobs([JOB])
        self.jid = self.store.jobs()[0]['id']
        self.workspace = Workspace(self.store)

    def test_metadata_persists_and_validates(self):
        self.workspace.save_metadata(self.jid, {'favorite': True, 'tags': ['Remote', 'Remote'], 'priority': 'high', 'deadline': '2026-12-01'})
        state = Workspace(Store(self.tmp.name)).state()
        self.assertTrue(state['metadata'][self.jid]['favorite'])
        self.assertEqual(state['metadata'][self.jid]['tags'], ['Remote'])
        for change in ({'priority': 'urgent!'}, {'deadline': '2026-02-30'}, {'tags': 'bad'}, {'favorite': 'false'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.workspace.save_metadata(self.jid, change)
        with self.assertRaises(ValueError):
            self.workspace.save_metadata('missing', {'favorite': True})

    def test_tasks_edit_complete_and_reopen(self):
        task = self.workspace.save_record('tasks', {'title': 'Follow up', 'kind': 'follow_up', 'due_on': '2026-12-01', 'job_id': self.jid})
        self.workspace.save_record('tasks', {'id': task['id'], 'done': True})
        self.assertTrue(self.workspace.state()['tasks'][0]['done'])
        self.workspace.save_record('tasks', {'id': task['id'], 'done': False})
        self.assertFalse(self.workspace.state()['tasks'][0]['done'])
        with self.assertRaises(ValueError):
            self.workspace.save_record('tasks', {'title': 'Bad', 'due_on': 'tomorrow'})

    def test_contacts_and_searches_survive_reopen(self):
        self.workspace.save_record('contacts', {'name': 'Recruiter', 'company': 'Example Co', 'email': 'recruiter@example.com'})
        self.workspace.save_record('searches', {'name': 'Python roles', 'filters': {'query': 'Python', 'favorite': True}})
        state = Workspace(Store(self.tmp.name)).state()
        self.assertEqual(state['contacts'][0]['name'], 'Recruiter')
        self.assertEqual(state['searches'][0]['filters']['query'], 'Python')
        with self.assertRaises(ValueError):
            self.workspace.save_record('contacts', {'name': 'Bad', 'url': 'javascript:alert(1)'})

    def test_editing_materials_invalidates_approval_and_preserves_versions(self):
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        self.workspace.save_materials(self.jid, {'resume': 'My <script>facts</script>', 'cover_letter': 'My letter'})
        job = self.store.job(self.jid)
        self.assertEqual(job['status'], 'prepared')
        self.assertIsNone(job['approval'])
        self.assertNotIn('<script>', job['materials']['resume_html'])
        self.assertEqual(len(self.workspace.material_versions(self.jid)), 2)
        self.store.action(self.jid, 'approve')
        self.store.action(self.jid, 'submitted', 'Portal confirmation')
        with self.assertRaises(ValueError):
            self.workspace.save_materials(self.jid, {'resume': 'Changed', 'cover_letter': 'Changed'})

    def test_calendar_escapes_text_and_excludes_completed(self):
        self.workspace.save_record('tasks', {'title': 'Interview, phase; 1', 'kind': 'interview', 'due_on': '2026-12-01', 'notes': 'First\nSecond'})
        self.workspace.save_record('tasks', {'title': 'Finished', 'due_on': '2026-12-01', 'done': True})
        calendar = self.workspace.calendar()
        self.assertIn('DTSTART;VALUE=DATE:20261201', calendar)
        self.assertIn(r'SUMMARY:Interview\, phase\; 1', calendar)
        self.assertNotIn('Finished', calendar)

    def test_backup_contains_restorable_database_without_connection_token(self):
        self.workspace.save_record('contacts', {'name': 'Recruiter'})
        backup = self.workspace.backup()
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            self.assertIn('jobpilot.sqlite3', archive.namelist())
            self.assertNotIn(self.store.setting('token').encode(), archive.read('jobpilot.sqlite3'))
            with tempfile.TemporaryDirectory() as target:
                archive.extract('jobpilot.sqlite3', target)
                restored = Store(target)
                self.assertEqual(Workspace(restored).state()['contacts'][0]['name'], 'Recruiter')
                self.assertNotEqual(restored.setting('token'), self.store.setting('token'))

    def test_queue_is_explicit_and_rejects_unapproved_jobs(self):
        with self.assertRaises(ValueError):
            self.workspace.save_queue([self.jid])
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        self.workspace.save_queue([self.jid])
        self.assertEqual([j['id'] for j in self.workspace.queue()], [self.jid])
        self.workspace.save_queue([])
        self.assertEqual(self.workspace.queue(), [])

    def test_resume_selection_invalidates_approval_and_survives_discovery(self):
        asset = self.workspace.save_resume('backend.txt', base64.b64encode(b'Backend resume').decode())
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        self.workspace.assign_resume(self.jid, asset['id'])
        job = self.store.job(self.jid)
        self.assertEqual(job['status'], 'discovered')
        self.assertIsNone(job['approval'])
        self.assertIsNone(job['materials'])
        self.store.upsert_jobs([JOB])
        self.assertEqual(self.store.job(self.jid)['resume_asset']['id'], asset['id'])
        self.assertEqual(base64.b64decode(self.workspace.resume(asset['id'])['base64']), b'Backend resume')
        self.assertNotIn('content', self.workspace.state()['resumes'][0])
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        self.store.action(self.jid, 'claim')
        with self.assertRaises(ValueError):
            self.workspace.assign_resume(self.jid, '')

    def test_manual_submission_archive_restore_preserves_outcome(self):
        with self.assertRaises(ValueError):
            self.store.action(self.jid, 'submitted_manual', '')
        self.store.action(self.jid, 'submitted_manual', 'Confirmation email received')
        submitted = self.store.job(self.jid)['submitted_at']
        self.store.action(self.jid, 'interview', 'Interview scheduled')
        self.store.action(self.jid, 'archive')
        with self.assertRaises(ValueError):
            self.store.action(self.jid, 'archive')
        self.store.action(self.jid, 'restore')
        self.assertEqual(self.store.job(self.jid)['status'], 'interview')
        self.assertEqual(self.store.job(self.jid)['submitted_at'], submitted)
        with self.assertRaises(ValueError):
            self.store.action(self.jid, 'submitted_manual', 'Duplicate')

    def test_restore_unsubmitted_job_requires_review(self):
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        self.store.action(self.jid, 'archive')
        self.store.action(self.jid, 'restore')
        self.assertEqual(self.store.job(self.jid)['status'], 'discovered')
        self.assertIsNone(self.store.job(self.jid)['approval'])

    def test_bundles_include_each_job_and_reject_unprepared_selection(self):
        with self.assertRaises(ValueError):
            self.workspace.bundles([self.jid])
        self.store.action(self.jid, 'prepare')
        with zipfile.ZipFile(io.BytesIO(self.workspace.bundles([self.jid]))) as archive:
            self.assertIn(self.jid + '/resume.html', archive.namelist())
            self.assertIn(self.jid + '/cover-letter.txt', archive.namelist())
            self.assertIn(b'Example Candidate', archive.read(self.jid + '/resume.txt'))


if __name__ == '__main__':
    unittest.main()
