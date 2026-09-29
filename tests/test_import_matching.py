import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from jobpilot.resume_import import preview, propose
from jobpilot.matching import match
from jobpilot.requirements import analyze, location_match
from jobpilot.skills import extract_skills
from test_core import PROFILE, JOB

TEXT = '''Example Candidate
example@example.com | +91 9876543210 | linkedin.com/in/example | github.com/example
Technical Skills
Python, ReactJS, Postgres, Amazon Web Services, K8s
Professional Experience
  Developer | Example Co | 2022–2025
    - Built Python services with
      automated SQL reports.
Projects
  Example Project
    - Built a React dashboard.
Education
Bachelor of Engineering | Example University | 2022
'''


class ResumeImportTests(unittest.TestCase):
    def test_text_suggestions_preserve_wrapped_bullets_and_unknown_context(self):
        result = preview('resume.txt', base64.b64encode(TEXT.encode()).decode())
        fields = result['fields']
        self.assertEqual(fields['name'], 'Example Candidate')
        self.assertEqual(fields['email'], 'example@example.com')
        self.assertEqual(fields['phone'], '+91 9876543210')
        self.assertEqual(fields['website'], 'https://github.com/example')
        self.assertIn('- Built Python services with automated SQL reports.', fields['experience'])
        self.assertIn('postgresql', fields['skills'])
        self.assertNotIn('years_experience', fields)
        self.assertIn('Amazon Web Services', fields['resume_text'])

    def test_docx_paragraph_and_table_extraction(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+
                       ''.join('<w:p><w:r><w:t>'+line+'</w:t></w:r></w:p>' for line in ['Example Candidate','Skills','Python and SQL','Experience','Built Python services'])+'</w:body></w:document>')
        result = preview('resume.docx', base64.b64encode(data.getvalue()).decode())
        self.assertIn('Python and SQL', result['text'])
        self.assertIn('Built Python services', result['fields']['experience'])

    def test_invalid_files_and_image_only_text_fail_clearly(self):
        for name, value in [('a.pdf', b'not a pdf'), ('a.docx', b'not a zip'), ('a.exe', b'fake')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                preview(name, base64.b64encode(value).decode())
        with self.assertRaises(ValueError):
            propose('   ')

    def test_docx_external_entities_are_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<!DOCTYPE x [<!ENTITY z SYSTEM "file:///etc/passwd">]><x>&z;</x>')
        with self.assertRaises(ValueError):
            preview('resume.docx', base64.b64encode(data.getvalue()).decode())


class ImprovedMatchingTests(unittest.TestCase):
    def test_aliases_match_without_mutating_profile_claims(self):
        profile = {**PROFILE, 'skills': ['Postgres', 'ReactJS', 'Amazon Web Services']}
        job = {**JOB, 'description': 'Requirements\nPostgreSQL, React.js and AWS are required.'}
        result = match(job, profile)
        self.assertEqual(result['missing_skills'], [])
        self.assertEqual(result['qualification_percent'], 100)
        self.assertEqual(profile['skills'][0], 'Postgres')

    def test_required_gaps_weigh_more_than_preferences(self):
        profile = {**PROFILE, 'skills': ['Python'], 'experience': [], 'projects': []}
        a = match({**JOB, 'description': 'Python required. Kubernetes preferred.'}, profile)
        b = match({**JOB, 'description': 'Kubernetes required. Python preferred.'}, profile)
        self.assertGreater(a['score'], b['score'])

    def test_explicit_alternatives_count_as_one(self):
        result = analyze({**JOB, 'description': 'Python or Java required.'}, PROFILE)
        self.assertEqual(len(result['groups']), 1)
        self.assertEqual(result['groups'][0]['operator'], 'any')
        self.assertTrue(result['groups'][0]['met'])

    def test_experience_range_and_sponsorship_conflict(self):
        job = {**JOB, 'description': 'Minimum 3–5 years of professional experience. We cannot provide visa sponsorship.'}
        result = match(job, {**PROFILE, 'needs_sponsorship': 'yes'})
        self.assertFalse(result['eligible'])
        self.assertTrue(any(c['label']=='Experience' and c['status']=='gap' for c in result['eligibility_checks']))
        self.assertTrue(any('sponsorship' in b.lower() for b in result['blockers']))

    def test_location_country_alias_does_not_treat_in_preposition_as_india(self):
        self.assertTrue(location_match('Bengaluru, KA, IN', 'India'))
        self.assertFalse(location_match('Remote in US', 'India'))
        self.assertFalse(location_match('San Francisco, CA', 'Canada'))

    def test_common_go_word_is_not_a_programming_claim(self):
        self.assertNotIn('go', extract_skills('We go above and beyond.'))
        self.assertIn('go', extract_skills('Golang services'))


if __name__ == '__main__':
    unittest.main()
