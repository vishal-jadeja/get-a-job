import io
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from jobpilot.latex_resume import render_latex, escape_latex
from jobpilot.store import Store
from jobpilot.workspace import Workspace
from test_core import PROFILE, JOB


class LatexTests(unittest.TestCase):
    def test_special_characters_cannot_become_tex_commands(self):
        unsafe = r'50% & C# $100 {proof} a_b \input{private.txt}'
        escaped = escape_latex(unsafe)
        self.assertIn(r'50\% \& C\# \$100 \{proof\} a\_b', escaped)
        self.assertNotIn(r'\input{private.txt}', escaped)
        self.assertIn(r'\textbackslash{}input\{private.txt\}', escaped)

    def test_jake_template_has_sections_attribution_and_only_provided_facts(self):
        source = render_latex('Alex Example\n\nalex@example.com\n\nSKILLS\nPython, SQL\n\nSELECTED EXPERIENCE\n• Example Co | Engineer | 2022–2024 — Built Python APIs.')
        self.assertIn(r'\documentclass[letterpaper,11pt]{article}', source)
        self.assertIn('Copyright (c) 2020 Jake Gutierrez', source)
        self.assertIn(r'\section{Experience}', source)
        self.assertIn(r'\resumeSubheading{Example Co}{Engineer}{2022--2024}', source)
        self.assertNotIn('Jake Ryan', source)
        self.assertNotIn('Kubernetes', source)


class PdfWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.workspace = Workspace(self.store)
        self.store.save_profile(PROFILE)
        self.store.upsert_jobs([JOB])
        self.jid = self.store.jobs()[0]['id']
        self.store.action(self.jid, 'prepare')

    def test_generated_pdf_can_be_selected_without_losing_edited_material(self):
        self.workspace.save_materials(self.jid, {'resume': 'Alex\n\na@example.com\n\nSKILLS\nPython', 'cover_letter': 'Edited letter'})
        before = self.store.job(self.jid)['materials']['resume']
        with patch('jobpilot.workspace.compile_pdf', return_value=b'%PDF-1.7\nfixture'):
            self.workspace.generate_pdf(self.jid)
        with patch('jobpilot.workspace.compile_pdf', side_effect=AssertionError('Cached PDF should be reused')):
            self.workspace.use_generated_pdf(self.jid)
        job = self.store.job(self.jid)
        self.assertEqual(job['materials']['resume'], before)
        self.assertEqual(job['status'], 'prepared')
        self.assertIsNone(job['approval'])
        self.assertTrue(job['resume_asset']['name'].endswith('.pdf'))
        self.store.action(self.jid, 'approve')
        with zipfile.ZipFile(io.BytesIO(self.workspace.bundles([self.jid]))) as archive:
            self.assertIn(self.jid + '/resume.tex', archive.namelist())
            self.assertIn(self.jid + '/resume.pdf', archive.namelist())
            self.assertIn(self.jid + '/LICENSE-jake.txt', archive.namelist())

    def test_edit_clears_cached_pdf_and_compilation_failure_does_not_change_state(self):
        with patch('jobpilot.workspace.compile_pdf', return_value=b'%PDF-1.7\nfixture'):
            self.workspace.generate_pdf(self.jid)
        self.workspace.save_materials(self.jid, {'resume': 'New draft', 'cover_letter': 'New letter'})
        self.assertNotIn('resume_pdf', self.store.job(self.jid)['materials'])
        with patch('jobpilot.workspace.compile_pdf', side_effect=ValueError('Compiler unavailable')), self.assertRaises(ValueError):
            self.workspace.use_generated_pdf(self.jid)
        self.assertEqual(self.store.job(self.jid)['status'], 'prepared')
        self.assertNotIn('resume_asset', self.store.job(self.jid))

    def test_draft_changed_during_compilation_is_not_cached(self):
        def compile_changed(resume):
            self.workspace.save_materials(self.jid, {'resume': 'New draft', 'cover_letter': 'New letter'})
            return b'%PDF-1.7\nfixture'
        with patch('jobpilot.workspace.compile_pdf', side_effect=compile_changed), self.assertRaises(ValueError):
            self.workspace.generate_pdf(self.jid)
        self.assertNotIn('resume_pdf', self.store.job(self.jid)['materials'])


if __name__ == '__main__':
    unittest.main()
