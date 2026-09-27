import unittest
import tempfile
from jobpilot.tailoring import choose_variant, prepare_for_job
from jobpilot.materials import fingerprint
from test_core import PROFILE, JOB
from jobpilot.store import Store
from jobpilot.workspace import Workspace


class TailoringTests(unittest.TestCase):
    def setUp(self):
        self.profile = {**PROFILE, 'skills': ['Python', 'SQL', 'React'],
                        'experience': ['Built React interfaces with accessibility tests.', 'Built Python and SQL services with automated tests.'],
                        'projects': ['React customer dashboard', 'Python reporting service']}
        self.variants = [
            {'id': 'backend', 'name': 'Backend résumé', 'target_roles': 'Backend Engineer, Python Developer', 'headline': 'Python engineer',
             'skills': ['Python', 'SQL'], 'experience': [self.profile['experience'][1]], 'projects': [self.profile['projects'][1]], 'max_skills': 8, 'max_experience': 4, 'max_projects': 2},
            {'id': 'frontend', 'name': 'Frontend résumé', 'target_roles': 'Frontend Engineer, React Developer', 'headline': 'Frontend engineer',
             'skills': ['React'], 'experience': [self.profile['experience'][0]], 'projects': [self.profile['projects'][0]], 'max_skills': 8, 'max_experience': 4, 'max_projects': 2},
        ]

    def test_different_roles_produce_different_evidence_preserving_resumes(self):
        backend = prepare_for_job(self.profile, {**JOB, 'title': 'Senior Backend Engineer', 'description': 'Python SQL services'}, self.variants)
        frontend = prepare_for_job(self.profile, {**JOB, 'title': 'Frontend Engineer', 'description': 'React accessibility'}, self.variants)
        self.assertEqual(backend['tailoring']['variant_id'], 'backend')
        self.assertEqual(frontend['tailoring']['variant_id'], 'frontend')
        self.assertIn(self.profile['experience'][1], backend['resume'])
        self.assertNotIn(self.profile['experience'][0], backend['resume'])
        self.assertIn(self.profile['experience'][0], frontend['resume'])
        self.assertNotIn(self.profile['experience'][1], frontend['resume'])

    def test_requirements_rank_evidence_without_inventing_skills(self):
        job = {**JOB, 'description': 'Python SQL Kubernetes'}
        result = prepare_for_job(self.profile, job, [])
        self.assertLess(result['resume'].index('Built Python'), result['resume'].index('Built React'))
        self.assertNotIn('Kubernetes', result['resume'])
        self.assertEqual(result['fingerprint'], fingerprint(self.profile, job))

    def test_override_and_general_fallback(self):
        self.assertEqual(choose_variant({**JOB, 'resume_variant_id': 'frontend'}, self.variants)['id'], 'frontend')
        self.assertIsNone(choose_variant({**JOB, 'resume_variant_id': 'general'}, self.variants))
        self.assertIsNone(choose_variant({**JOB, 'title': 'Data Analyst'}, self.variants))

    def test_removed_evidence_requires_review(self):
        with self.assertRaises(ValueError):
            prepare_for_job({**self.profile, 'experience': []}, {**JOB, 'resume_variant_id': 'backend'}, self.variants)


class VariantPersistenceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.store.save_profile(PROFILE)
        self.store.upsert_jobs([JOB])
        self.jid = self.store.jobs()[0]['id']
        self.workspace = Workspace(self.store)

    def test_role_resume_changes_invalidate_pending_approval(self):
        self.store.action(self.jid, 'prepare')
        self.store.action(self.jid, 'approve')
        variant = self.workspace.save_variant({'name': 'Engineering', 'target_roles': 'Software Engineer', 'skills': ['Python']})
        self.assertEqual(self.store.job(self.jid)['status'], 'discovered')
        self.store.action(self.jid, 'prepare')
        job = self.store.job(self.jid)
        self.assertEqual(job['materials']['tailoring']['variant_id'], variant['id'])
        self.store.action(self.jid, 'approve')
        self.workspace.assign_variant(self.jid, 'general')
        self.assertIsNone(self.store.job(self.jid)['approval'])
        self.store.upsert_jobs([JOB])
        self.assertEqual(self.store.job(self.jid)['resume_variant_id'], 'general')


if __name__ == '__main__':
    unittest.main()
