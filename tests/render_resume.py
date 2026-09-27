"""Render a fictional résumé for LaTeX integration/visual QA."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobpilot.tailoring import prepare_for_job
from jobpilot.latex_resume import compile_pdf, render_latex
from test_core import PROFILE, JOB

profile = {**PROFILE, 'name': 'Jordan Avery', 'phone': '+91 90000 00000', 'location': 'Bengaluru, India',
           'headline': 'Software engineer — Python, SQL & reliable web services',
           'experience': [
               'Example Systems | Software Engineer | 2022–2024 — Built Python services and SQL reporting workflows for an internal operations platform.',
               'Example Systems | Software Engineer | 2022–2024 — Added automated tests for API validation and asynchronous job processing.',
               'Sample Studio | Developer Intern | 2021–2022 — Built React dashboards and improved keyboard accessibility across forms.',
           ], 'projects': [
               'Service Monitor | Python, SQL | 2024 — Built a service-health dashboard with scheduled checks and incident history.',
               'Team Planner | React, JavaScript | 2023 — Created an accessible task planner with filtering and export features.',
           ], 'education': ['B.Tech. Computer Science | Example Institute | 2018–2022'],
           'skills': ['Python', 'SQL', 'React', 'JavaScript', 'Git', 'Automated testing']}
material = prepare_for_job(profile, JOB, [])
out = Path(__file__).resolve().parents[1] / 'output' / 'pdf'
out.mkdir(parents=True, exist_ok=True)
(out / 'sample-resume.tex').write_text(render_latex(material['resume']), encoding='utf-8')
(out / 'sample-resume.pdf').write_bytes(compile_pdf(material['resume']))
print(out / 'sample-resume.pdf')
