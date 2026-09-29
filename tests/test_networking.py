import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from jobpilot.networking import Networking, candidate, drafts, linkedin_url, context_key
from jobpilot.store import Store
from test_core import PROFILE, JOB


class NetworkingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.save_profile(PROFILE)
        self.store.upsert_jobs([JOB])
        self.job = self.store.jobs()[0]

    def test_candidates_need_company_and_role_evidence(self):
        row = {'url': 'https://in.linkedin.com/in/jane-example?trk=test',
               'title': 'Jane Example - Software Engineer at Example Co | LinkedIn',
               'description': 'Example Co engineering team'}
        person = candidate(row, self.job, 'peer')
        self.assertEqual(person['name'], 'Jane Example')
        self.assertEqual(person['url'], 'https://www.linkedin.com/in/jane-example')
        self.assertEqual(person['verification'], 'public_search_result')
        self.assertIsNone(candidate({**row, 'title': 'Jane Example - Engineer at Other Co', 'description': ''}, self.job, 'peer'))
        self.assertIsNone(candidate(row, self.job, 'recruiter'))
        self.assertIsNone(candidate({**row, 'url': 'https://linkedin.com.evil.test/in/jane'}, self.job, 'peer'))

    def test_recruiter_category_and_company_links(self):
        row = {'url': 'https://www.linkedin.com/in/raj-example', 'title': 'Raj Example - Talent Acquisition at Example Co', 'description': ''}
        self.assertEqual(candidate(row, self.job, 'recruiter')['kind'], 'recruiter')
        self.assertEqual(linkedin_url('https://linkedin.com/company/example-co/', 'company'), 'https://www.linkedin.com/company/example-co')
        with self.assertRaises(ValueError):
            linkedin_url('https://linkedin.com/search/results/people', 'person')

    def test_drafts_only_use_saved_evidence_and_are_short(self):
        result = drafts(PROFILE, JOB, {'name': 'Jane Example', 'kind': 'peer'})
        self.assertLessEqual(len(result['connection']), 300)
        self.assertLessEqual(len(result['message']), 650)
        self.assertIn('Python', result['message'])
        self.assertNotIn('Kubernetes', result['message'])
        self.assertIn(result['evidence'], PROFILE['experience'] + PROFILE['projects'])
        self.assertIn('Hi Jane', result['connection'])
        empty = drafts({}, JOB)
        self.assertTrue(empty['warning'])
        self.assertNotIn('background includes', empty['message'])

    def test_search_queries_never_include_applicant_data(self):
        queries = []
        def search(query, key):
            queries.append(query)
            return []
        network = Networking(self.store, search=search)
        network.lookup(self.job)
        self.assertEqual(len(queries), 3)
        self.assertTrue(all(JOB['company'] in q for q in queries))
        self.assertNotIn(PROFILE['email'], ' '.join(queries))
        self.assertNotIn(PROFILE['experience'][0], ' '.join(queries))
        self.assertEqual(network.cached(self.job)['status'], 'ready')
        self.assertFalse(network.start([self.job]))

    def test_provider_failure_stops_and_records_fallback(self):
        queries = []
        def search(query, key):
            queries.append(query)
            raise ValueError('Rate limit reached')
        network = Networking(self.store, search=search)
        result = network.lookup(self.job)
        self.assertEqual(len(queries), 1)
        self.assertEqual(result['status'], 'error')
        self.assertEqual(len(network.view(self.job)['search_links']), 3)
        self.assertFalse(network.cached(self.job)['stale'])

    def test_failed_refresh_preserves_previous_contact_candidates(self):
        network = Networking(self.store, search=lambda q, key: [{'url': 'https://www.linkedin.com/in/jane-example', 'title': 'Jane Example - Software Engineer at Example Co', 'description': ''}])
        self.assertTrue(network.lookup(self.job)['people'])
        def fail(*args):
            raise ValueError('Unavailable')
        network.search = fail
        result = network.lookup(self.job)
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(result['people'])
        self.assertTrue(result['previous_results_at'])

    def test_cache_persists_and_expiration_is_explicit(self):
        network = Networking(self.store, search=lambda *args: [])
        network.lookup(self.job)
        self.assertTrue(Networking(self.store).cached(self.job))
        with self.store.db() as db:
            db.execute('UPDATE networking_cache SET checked_at=?', ((datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),))
        self.assertTrue(network.cached(self.job)['stale'])
        self.assertNotEqual(context_key(self.job), context_key({**self.job, 'board': 'different-employer'}))


if __name__ == '__main__':
    unittest.main()
