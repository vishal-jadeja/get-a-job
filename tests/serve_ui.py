"""Disposable fixture server for manual/browser QA. No real applicant data."""
import sys
import base64
import tempfile
from pathlib import Path
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobpilot.server import App, handler_class
from jobpilot.store import Store
from test_core import PROFILE, JOB
from test_yc import ROW
from jobpilot.yc import normalize


def main():
    with tempfile.TemporaryDirectory(prefix='jobpilot-ui-') as directory:
        store = Store(directory)
        store.save_profile(PROFILE)
        store.upsert_jobs([
            JOB,
            {**JOB, 'title': 'Backend Engineer', 'company': 'Northstar Labs', 'url': 'https://jobs.example/northstar', 'external_id': 'second'},
            {**JOB, 'title': 'Platform Engineer', 'company': 'Orbit Systems', 'url': 'https://jobs.example/orbit', 'external_id': 'third'},
        ])
        app = App(store)
        store.set_setting('networking', {'automatic': False, 'max_per_run': 5})
        # Deterministic public-contact fixture; no external lookup is performed.
        app.networking.search = lambda *args: [
            {'url': 'https://www.linkedin.com/company/example-fixture', 'title': 'Example Co | LinkedIn', 'description': 'Fictional company fixture'},
            {'url': 'https://www.linkedin.com/in/jane-example-fixture', 'title': 'Jane Example - Software Engineer at Example Co', 'description': 'Fictional public-profile fixture for Example Co'},
            {'url': 'https://www.linkedin.com/in/sam-example-fixture', 'title': 'Sam Example - Technical Recruiter at Example Co', 'description': 'Fictional recruiting-profile fixture for Example Co'},
        ]
        app.networking.lookup(next(j for j in store.jobs() if j['company'] == 'Example Co'))
        yc_job = normalize({**ROW, 'companyName': 'YC Example (fictional fixture)'})
        store.upsert_jobs([yc_job])
        app.record_yc({'jobs': [yc_job], 'pages': 1, 'errors': [], 'coverage': 'Fictional UI fixture'})
        from test_gmail import message
        app.mail.ingest('fixture@example.com', [message('ui-receipt'), message('ui-interview',
            text='We invite you to an interview for Software Engineer at Example Co.')])
        from test_import_matching import TEXT
        store.save_resume('fixture-resume.txt', base64.b64encode(TEXT.encode()).decode())
        app.workspace.save_resume('backend-resume.txt', base64.b64encode(b'Example Candidate - Python and SQL services').decode())
        jobs = store.jobs()
        app.workspace.save_metadata(jobs[0]['id'], {'favorite': True, 'priority': 'high', 'tags': ['Remote'], 'deadline': '2026-10-05'})
        app.workspace.save_record('tasks', {'title': 'Research the engineering team', 'job_id': jobs[0]['id'], 'due_on': '2026-10-01', 'kind': 'application'})
        with ThreadingHTTPServer(('127.0.0.1', 18765), handler_class(app)) as server:
            print('Disposable JobPilot QA: http://127.0.0.1:18765', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == '__main__':
    main()
