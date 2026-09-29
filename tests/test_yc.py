import html
import json
import tempfile
import unittest
from jobpilot import yc
from jobpilot.store import Store
from jobpilot.matching import match
from test_core import PROFILE

ROW = {'id': 123, 'title': 'Backend Engineer', 'role': 'eng', 'url': '/companies/example/jobs/abc-backend',
       'companyName': 'Example', 'companyBatchName': 'S26', 'companyUrl': '/companies/example',
       'companyOneLiner': 'Example product', 'location': 'India', 'skills': ['Python', 'SQL'],
       'lastActive': '2 days', 'createdAt': '3 months'}


def page(props):
    return '<div data-page="' + html.escape(json.dumps({'props': props}), quote=True) + '"></div>'


class YCTests(unittest.TestCase):
    def test_batch_and_relative_activity_sort(self):
        newer = {'yc_batch': 'F26', 'yc_activity': '2 months'}
        earlier = {'yc_batch': 'W26', 'yc_activity': '1 day'}
        self.assertLess(yc.trend(newer), yc.trend(earlier))
        self.assertLess(yc.trend({**newer, 'yc_activity': 'about 8 hours'}), yc.trend({**newer, 'yc_activity': '1 day'}))

    def test_public_pages_deduplicate_and_skip_nonengineering(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return page({'jobPostings': [ROW, {**ROW, 'id': 2, 'role': 'sales'}],
                         'sidebarLinks': [['India', '/jobs/role/software-engineer/india'], ['Bad', 'https://evil.example/']]})
        result = yc.discover(fetch)
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['pages'], 2)
        self.assertEqual(result['jobs'][0]['posted_at'], '')
        self.assertTrue(result['jobs'][0]['description_partial'])

    def test_partial_failures_are_visible(self):
        def fetch(url):
            if url.endswith('/india'):
                raise ValueError('Unavailable')
            return page({'jobPostings': [ROW], 'sidebarLinks': [['India', '/jobs/role/software-engineer/india']]})
        result = yc.discover(fetch)
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(len(result['jobs']), 1)

    def test_restrict_fetch_destinations_and_report_changed_format(self):
        for url in ['https://evil.example/companies/x', '/account', 'https://www.ycombinator.com.evil.test/companies/x']:
            with self.assertRaises(ValueError):
                yc.public_url(url)
        with self.assertRaises(ValueError):
            yc.discover(lambda url: '<html>Sign in</html>')

    def test_details_preserve_provenance_and_only_public_fields(self):
        job, company, people = yc.detail(yc.BASE+ROW['url'], lambda _: page({'job': {**ROW, 'description': 'Python and SQL services'}, 'company': {
            'linkedin_url': 'https://www.linkedin.com/company/example', 'one_liner': 'Example',
            'founders': [{'full_name': 'Jane Example', 'is_active': True, 'linkedin_url': 'https://www.linkedin.com/in/jane-example', 'email': 'not-collected@example.com'}]}}))
        self.assertFalse(job['description_partial'])
        self.assertEqual(people[0]['kind'], 'founder')
        self.assertNotIn('email', people[0])
        self.assertEqual(company['source_url'], job['url'])

    def test_summary_cannot_prepare_and_does_not_overwrite_full_description(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.save_profile(PROFILE)
            partial = yc.normalize(ROW)
            store.upsert_jobs([partial])
            job = store.jobs()[0]
            self.assertIsNone(match(job, PROFILE)['qualification_percent'])
            with self.assertRaises(ValueError):
                store.action(job['id'], 'prepare')
            full = yc.normalize({**ROW, 'description': 'Python SQL services'})
            store.upsert_jobs([full])
            store.upsert_jobs([partial])
            loaded = store.job(job['id'])
            self.assertEqual(loaded['description'], full['description'])
            self.assertFalse(loaded['description_partial'])
            self.assertEqual(loaded['yc_batch'], 'S26')


if __name__ == '__main__':
    unittest.main()
