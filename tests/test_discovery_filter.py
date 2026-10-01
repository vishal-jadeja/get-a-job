import unittest
from jobpilot.discovery_filter import relevant_engineering

PROFILE = {'roles': ['Software Engineer', 'Backend Engineer', 'AI Engineer'],
           'skills': ['Python', 'SQL'], 'years_experience': 2, 'min_score': 45}


class DiscoveryFilterTests(unittest.TestCase):
    def job(self, title='Backend Engineer', **kwargs):
        return dict(title=title, company='Example', description='Required: Python and SQL', location='', **kwargs)

    def test_relevant_and_unrelated_titles(self):
        self.assertTrue(relevant_engineering(self.job(), PROFILE))
        for title in ['Sales Engineer', 'Technical Recruiter', 'Hardware Engineer', 'Account Executive', 'Software Engineering Manager', 'Senior Backend Engineer']:
            self.assertFalse(relevant_engineering(self.job(title), PROFILE), title)

    def test_required_experience_and_profile_filters(self):
        job = self.job()
        job['description'] += '\nMinimum 5 years of experience required.'
        self.assertFalse(relevant_engineering(job, PROFILE))
        self.assertFalse(relevant_engineering(self.job(), {**PROFILE, 'excluded_companies': ['Example']}))
        self.assertFalse(relevant_engineering(self.job(), {**PROFILE, 'locations': ['India']}))

    def test_evidence_and_partial_descriptions(self):
        job = self.job('Software Engineer')
        job['description'] = ''
        self.assertFalse(relevant_engineering(job, PROFILE))
        self.assertTrue(relevant_engineering({**job, 'description_partial': True}, PROFILE))
        self.assertFalse(relevant_engineering(self.job(), {**PROFILE, 'roles': []}))
