import base64
import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from urllib.parse import parse_qs, urlsplit
from jobpilot.gmail import Gmail, SCOPE, TOKEN, API, body_text, normalize_message
from jobpilot.mail_tracking import MailTracker, classify
from jobpilot.store import Store
from jobpilot.workspace import Workspace
from test_core import PROFILE, JOB

CLIENT = {'installed': {'client_id': 'fixture.apps.googleusercontent.com', 'client_secret': 'fixture-client-secret'}}


def message(mid='abc123', subject='Your Software Engineer application at Example Co', text='Thank you for applying to Example Co for the Software Engineer position.'):
    return {'id': mid, 'subject': subject, 'text': text, 'sender': 'Example Co Careers <careers@example.com>',
            'received_at': '1750000000000', 'url': 'https://mail.google.com/mail/u/0/#all/'+mid}


class GmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.calls = []
        def transport(url, data=None, token=None):
            self.calls.append((url, data, token))
            if url == TOKEN:
                return {'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'expires_in': 3600, 'scope': SCOPE}
            if url == API+'profile':
                return {'emailAddress': 'candidate@example.com'}
            if url.startswith(API+'messages?'):
                return {'messages': [{'id': 'one'}, {'id': 'two'}]}
            return {'id': url.split('/messages/')[1].split('?')[0], 'internalDate': '1750000000000', 'payload': {
                'mimeType': 'text/plain', 'headers': [{'name': 'Subject', 'value': 'Application received'}],
                'body': {'data': base64.urlsafe_b64encode(b'Thank you for applying').decode()}}}
        self.gmail = Gmail(self.tmp.name, transport)
        self.gmail.configure(CLIENT)

    def connect(self):
        query = parse_qs(urlsplit(self.gmail.connect_url(8765)).query)
        self.gmail.callback(query['state'][0], 'fixture-code')
        return query

    def test_desktop_flow_uses_readonly_pkce_state_and_loopback(self):
        query = parse_qs(urlsplit(self.gmail.connect_url(8765)).query)
        self.assertEqual(query['scope'], [SCOPE])
        self.assertEqual(query['redirect_uri'], ['http://127.0.0.1:8765/oauth/gmail/callback'])
        expected = base64.urlsafe_b64encode(hashlib.sha256(self.gmail.pending['verifier'].encode()).digest()).decode().rstrip('=')
        self.assertEqual(query['code_challenge'], [expected])
        with self.assertRaises(ValueError): self.gmail.callback('wrong-state', 'code')
        self.assertEqual(self.calls, [])
        self.gmail.callback(query['state'][0], 'fixture-code')
        with self.assertRaises(ValueError): self.gmail.callback(query['state'][0], 'fixture-code')
        self.assertEqual(self.gmail.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('fixture-refresh', json.dumps(self.gmail.status()))

    def test_expired_denied_and_wrong_client_requests_do_not_read_mail(self):
        with self.assertRaises(ValueError): self.gmail.configure({'web': CLIENT['installed']})
        query = parse_qs(urlsplit(self.gmail.connect_url(8765)).query)
        self.gmail.pending['expires'] = 0
        with self.assertRaises(ValueError): self.gmail.callback(query['state'][0], 'code')
        query = parse_qs(urlsplit(self.gmail.connect_url(8765)).query)
        with self.assertRaises(ValueError): self.gmail.callback(query['state'][0], '', 'access_denied')
        self.assertEqual(self.calls, [])

    def test_message_limits_and_disconnect(self):
        self.connect()
        result = list(self.gmail.messages('newer_than:7d application', limit=1))
        self.assertEqual(len(result), 1)
        self.assertTrue(any('q=newer_than' in c[0] for c in self.calls))
        self.assertFalse(any('/send' in c[0] or '/modify' in c[0] or '/attachments' in c[0] for c in self.calls))
        self.gmail.disconnect()
        self.assertFalse(self.gmail.status()['connected'])
        self.assertNotIn('fixture-refresh', self.gmail.path.read_text())
        with self.assertRaises(ValueError): list(self.gmail.messages())

    def test_refresh_token_survives_restart_but_not_backup(self):
        self.connect()
        restored = Gmail(self.tmp.name, self.gmail.transport)
        self.assertTrue(restored.status()['connected'])
        restored.token()
        self.assertEqual(self.calls[-1][1]['grant_type'], 'refresh_token')
        store = Store(self.tmp.name)
        with zipfile.ZipFile(io.BytesIO(Workspace(store).backup())) as archive:
            self.assertNotIn('gmail-credentials.json', archive.namelist())
            self.assertTrue(all(b'fixture-refresh' not in archive.read(n) for n in archive.namelist()))

    def test_plain_alternative_preferred_and_attachments_ignored(self):
        enc = lambda s: base64.urlsafe_b64encode(s.encode()).decode()
        payload = {'mimeType':'multipart/alternative','parts':[
            {'mimeType':'text/html','body':{'data':enc('<p>HTML version</p>')}},
            {'mimeType':'text/plain','body':{'data':enc('Plain version')}},
        ]}
        self.assertEqual(body_text(payload), 'Plain version')
        self.assertEqual(body_text({'mimeType':'text/plain','filename':'private.txt','body':{'data':enc('secret')}}), '')


class MailTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name); self.store.save_profile(PROFILE); self.store.upsert_jobs([JOB])
        self.job = self.store.jobs()[0]; self.mail = MailTracker(self.store)

    def ingest(self, item):
        self.mail.ingest('candidate@example.com', [item])
        return next(e for e in self.mail.state()['events'] if e['message_id'] == item['id'])

    def test_receipt_needs_review_and_duplicates_are_ignored(self):
        event = self.ingest(message())
        self.assertEqual(self.store.job(self.job['id'])['status'], 'discovered')
        self.assertEqual(self.mail.ingest('candidate@example.com', [message()]), 0)
        self.assertEqual(event['suggested_job_id'], self.job['id'])
        self.mail.review(event['id'], 'accept', self.job['id'], 'submitted')
        self.assertEqual(self.store.job(self.job['id'])['status'], 'submitted')
        with self.assertRaises(ValueError): self.mail.review(event['id'], 'accept', self.job['id'], 'submitted')

    def test_rejection_and_archived_stages_do_not_regress(self):
        self.store.action(self.job['id'], 'submitted_manual', 'Fixture confirmation')
        self.store.action(self.job['id'], 'rejected', 'Fixture rejection')
        event = self.ingest(message('interview', text='We invite you to an interview for Software Engineer at Example Co.'))
        with self.assertRaises(ValueError): self.mail.review(event['id'], 'accept', self.job['id'], 'interview')
        self.store.action(self.job['id'], 'archive')
        with self.assertRaises(ValueError): self.mail.review(event['id'], 'accept', self.job['id'], 'rejected')
        self.assertEqual(self.mail.state()['events'][0]['review_status'], 'pending')

    def test_same_company_same_title_requires_manual_selection(self):
        self.store.upsert_jobs([{**JOB,'url':'https://jobs.example/second','external_id':'different'}])
        result = classify(message(), self.store.jobs())
        self.assertEqual(result['confidence'], 'ambiguous')
        self.assertEqual(result['suggested_job_id'], '')

    def test_marketing_and_quoted_old_status_are_not_used(self):
        self.assertIsNone(classify(message(subject='Our team benefits',text='At Example Co we offer health insurance and flexible hours.'), self.store.jobs()))
        result = classify(message(text='We invite you to an interview at Example Co for Software Engineer.\nOn Monday someone wrote:\nUnfortunately your application was rejected.'), self.store.jobs())
        self.assertEqual(result['suggested_status'], 'interview')

    def test_dismiss_and_account_deduplication(self):
        event = self.ingest(message())
        self.mail.review(event['id'], 'dismiss')
        self.assertEqual(self.store.job(self.job['id'])['status'], 'discovered')
        self.assertEqual(self.mail.ingest('different@example.com', [message()]), 1)


if __name__ == '__main__': unittest.main()
