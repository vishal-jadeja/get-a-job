import argparse
import base64
import csv
import io
import json
import mimetypes
import os
import secrets
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from .sources import discover
from .store import Store, now
from .workspace import Workspace
from . import firecrawl
from . import latex_resume
from . import yc
from .networking import Networking, drafts
from . import resume_import
from .gmail import Gmail, DEFAULT_QUERY
from .mail_tracking import MailTracker

ROOT = Path(__file__).resolve().parent.parent


class App:
    def __init__(self, store):
        self.store = store
        self.workspace = Workspace(store)
        self.gmail = Gmail(store.directory)
        self.mail = MailTracker(store)
        self.firecrawl_key = os.environ.get('FIRECRAWL_API_KEY', '')
        self.networking = Networking(store, key_provider=lambda: self.firecrawl_key)
        self.yc_lock = threading.Lock()
        self.yc_status = store.setting('yc_status') or {'running': False, 'message': 'YC discovery has not run', 'pages': 0, 'companies': 0}
        self.yc_status['running'] = False
        self.firecrawl_lock = threading.Lock()
        self.pdf_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.sync_status = {"running": False, "message": "Ready to discover jobs", "added": 0}

    def sync(self, prepare_matches=False):
        if self.yc_lock.locked():
            return False
        if not self.sync_lock.acquire(blocking=False):
            return False
        self.sync_status = {"running": True, "message": "Reading public job boards…", "added": 0}
        def run():
            added, errors, total = 0, [], 0
            try:
                sources = [s for s in self.store.sources() if s["enabled"]]
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(yc.discover) if s['kind'] == 'yc' else pool.submit(discover, s): s for s in sources}
                    for future in as_completed(futures):
                        source = futures[future]
                        try:
                            result = future.result()
                            if source['kind'] == 'yc':
                                jobs = result['jobs']
                                self.record_yc(result)
                                errors.extend(result['errors'])
                            else:
                                jobs = result
                            added += self.store.upsert_jobs(jobs)
                            total += len(jobs)
                            with self.store.db() as db:
                                db.execute("UPDATE sources SET last_sync=?,count=?,error=NULL WHERE id=?", (now(), len(jobs), source["id"]))
                        except Exception as exc:
                            error = f"{source['company']}: {str(exc)[:180]}"
                            errors.append(error)
                            with self.store.db() as db:
                                db.execute("UPDATE sources SET last_sync=?,error=? WHERE id=?", (now(), error, source["id"]))
                        self.sync_status.update(added=added, message=f"Read {total} jobs · {added} new · {len(errors)} source errors")
                self.hydrate_yc_matches()
                automation = self.store.setting("automation")
                if prepare_matches:
                    limit = automation["batch_size"]
                    count = 0
                    for job in self.store.jobs():
                        if count >= limit:
                            break
                        if job["status"] == "discovered" and job["match"]["eligible"] and job["match"]["score"] >= self.store.setting("profile")["min_score"]:
                            try:
                                self.store.action(job["id"], "prepare")
                                count += 1
                            except ValueError as exc:
                                errors.append(str(exc))
                                break
                automation["last_run"] = now()
                self.store.set_setting("automation", automation)
                self.sync_status = {"running": False, "added": added, "total": total, "errors": errors,
                                    "message": f"Discovery complete · {added} new jobs · {len(errors)} errors"}
                self.auto_network()
            except Exception as exc:
                self.sync_status = {"running": False, "added": added, "message": "Discovery failed", "errors": [str(exc)]}
            finally:
                self.sync_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def auto_network(self):
        if self.store.setting('networking')['automatic']:
            jobs = [j for j in self.store.jobs() if j['match']['eligible'] and j['match']['score'] >= self.store.setting('profile')['min_score']]
            self.networking.start(jobs)

    def record_yc(self, result):
        self.yc_status = {'running': False, 'checked_at': now(), 'pages': result['pages'],
                          'listed_urls': [j['url'] for j in result['jobs']],
                          'companies': len({j['company'] for j in result['jobs']}),
                          'jobs': len(result['jobs']), 'errors': result['errors'], 'coverage': result['coverage'],
                          'message': f"Found {len(result['jobs'])} public YC engineering postings"}
        self.store.set_setting('yc_status', self.yc_status)
        with self.store.db() as db:
            db.execute("UPDATE sources SET last_sync=?,count=?,error=? WHERE kind='yc' AND board='engineering'",
                       (self.yc_status['checked_at'], len(result['jobs']),
                        '; '.join(result['errors'])[:2000] or None))

    def hydrate_yc_matches(self):
        profile = self.store.setting('profile')
        if not profile.get('roles'):
            return
        from .matching import match
        selected = []
        for job in self.store.jobs():
            if job.get('source') != 'yc' or not job.get('description_partial'):
                continue
            if job['url'] not in self.yc_status.get('listed_urls', []):
                continue
            fit = match({**job, 'description_partial': False}, profile)
            if fit['eligible'] and fit['score'] >= profile['min_score']:
                selected.append(job)
            if len(selected) >= 10:
                break
        for job in selected:
            try:
                full, _, _ = yc.detail(job['url'])
                self.store.upsert_jobs([full])
            except Exception as exc:
                self.yc_status.setdefault('errors', []).append('Full posting: ' + str(exc)[:150])

    def discover_yc(self):
        if self.sync_lock.locked() or not self.yc_lock.acquire(blocking=False):
            return False
        self.yc_status = {**self.yc_status, 'running': True, 'message': 'Reading public YC engineering listings…'}
        def run():
            try:
                result = yc.discover()
                added = self.store.upsert_jobs(result['jobs'])
                self.record_yc(result)
                self.yc_status['running'] = True
                self.yc_status['message'] = 'Loading complete requirements for up to 10 profile matches…'
                self.hydrate_yc_matches()
                self.yc_status.update(running=False, message=f"Found {len(result['jobs'])} public YC engineering postings")
                self.yc_status['added'] = added
                self.store.set_setting('yc_status', self.yc_status)
                self.auto_network()
            except Exception as exc:
                self.yc_status.update(running=False, message='YC discovery failed: ' + str(exc)[:200])
            finally:
                self.yc_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def scheduler(self):
        while True:
            time.sleep(30)
            mail_settings = self.store.setting('gmail_sync')
            last_mail = mail_settings.get('last_run')
            if mail_settings['enabled'] and self.gmail.status()['connected'] and (not last_mail or
                    (datetime.now(timezone.utc)-datetime.fromisoformat(last_mail)).total_seconds() >= mail_settings['interval_minutes']*60):
                self.mail.sync(self.gmail)
            config = self.store.setting("automation")
            if not config["enabled"]:
                continue
            last = config.get("last_run")
            due = not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= config["interval_hours"] * 3600
            if due:
                self.sync(config["prepare_matches"])


def handler_class(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Never log personal profiles, auth headers, or document bodies.
            pass

        def send(self, value, status=200, content_type="application/json; charset=utf-8", filename=None):
            body = json.dumps(value).encode() if content_type.startswith("application/json") else (value.encode() if isinstance(value, str) else value)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            origin = self.headers.get("Origin", "")
            if origin.startswith("chrome-extension://"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def authenticated(self):
            origin = self.headers.get("Origin", "")
            valid_origin = not origin or origin in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"} or origin.startswith("chrome-extension://")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return valid_origin and secrets.compare_digest(token, app.store.setting("token"))

        def do_OPTIONS(self):
            if not self.allowed_host() or not self.headers.get("Origin", "").startswith("chrome-extension://"):
                return self.send({"error": "Forbidden"}, 403)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def dispatch(self, method):
            try:
                if not self.allowed_host():
                    return self.send({"error": "Invalid local host"}, 403)
                path = urlsplit(self.path).path
                if method == 'GET' and path == '/oauth/gmail/callback':
                    params = parse_qs(urlsplit(self.path).query)
                    try:
                        app.gmail.callback(params.get('state', [''])[0], params.get('code', [''])[0], params.get('error', [''])[0])
                        message = 'Gmail connected with read-only access. Return to JobPilot to sync application emails.'
                    except ValueError as exc:
                        message = str(exc)
                    import html
                    return self.send('<!doctype html><meta charset="utf-8"><title>JobPilot Gmail connection</title><h1>JobPilot</h1><p>'+html.escape(message)+'</p><a href="/#mail">Return to email tracking</a>', content_type='text/html; charset=utf-8')
                if not path.startswith("/api/"):
                    if method != "GET":
                        return self.send({"error": "Not found"}, 404)
                    if path == "/":
                        page = (ROOT / "static/index.html").read_text(encoding="utf-8").replace("__TOKEN__", app.store.setting("token"))
                        return self.send(page, content_type="text/html; charset=utf-8")
                    assets = {"/app.js": "static/app.js", "/intelligence.js": "static/intelligence.js", "/networking.js": "static/networking.js", "/workspace.js": "static/workspace.js", "/workspace.css": "static/workspace.css", "/styles.css": "static/styles.css", "/icon.svg": "static/icon.svg"}
                    if path in assets:
                        file = ROOT / assets[path]
                        return self.send(file.read_bytes(), content_type=mimetypes.guess_type(file.name)[0] or "text/plain")
                    return self.send({"error": "Not found"}, 404)
                if not self.authenticated():
                    return self.send({"error": "Unauthorized. Reconnect the browser helper or reload the dashboard."}, 401)
                data = {}
                if method == "POST":
                    length = int(self.headers.get("Content-Length", 0))
                    if length < 0 or length > 8 * 1024 * 1024:
                        return self.send({"error": "Request too large"}, 413)
                    data = json.loads(self.rfile.read(length) or "{}")
                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object")
                if method == "GET" and path == "/api/state":
                    state = app.store.bootstrap()
                    state["sync"] = app.sync_status
                    state["workspace"] = app.workspace.state()
                    state["integrations"] = {'firecrawl': {'configured': bool(app.firecrawl_key)}, 'latex': {'available': bool(latex_resume.compiler())}}
                    state['networking'] = {'settings': app.store.setting('networking'), 'progress': app.networking.progress}
                    state['yc'] = app.yc_status
                    state['gmail'] = app.gmail.status()
                    return self.send(state)
                if method == 'POST' and path == '/api/resume/preview':
                    if data.get('use_saved'):
                        file = app.store.setting('profile').get('resume_file')
                        if not file:
                            raise ValueError('Upload a résumé first')
                        return self.send(resume_import.preview(file['name'], base64.b64encode((app.store.directory/'resume.bin').read_bytes()).decode()))
                    return self.send(resume_import.preview(data['name'], data['base64']))
                if method == 'POST' and path == '/api/resume/merge':
                    fields = data.get('fields')
                    allowed = {'name','email','phone','linkedin','website','skills','technologies','experience','projects','education','certifications','achievements','languages','resume_text'}
                    if not isinstance(fields, dict) or not fields or set(fields)-allowed:
                        raise ValueError('Select résumé fields to merge')
                    profile = app.store.setting('profile')
                    for key, value in fields.items():
                        if isinstance(profile.get(key), list):
                            if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                                raise ValueError('List fields must contain text entries')
                            profile[key] = list(dict.fromkeys(profile[key]+value))
                        elif not isinstance(value, str):
                            raise ValueError('Use text for contact fields')
                        elif key == 'resume_text' and profile.get(key):
                            if value not in profile[key]:
                                profile[key] += '\n\n' + value
                        else:
                            profile[key] = value
                    return self.send(app.store.save_profile(profile))
                if method == 'GET' and path == '/api/mail':
                    return self.send({**app.mail.state(), 'gmail': app.gmail.status(), 'default_query': DEFAULT_QUERY})
                if method == 'POST' and path == '/api/gmail/configure':
                    return self.send(app.gmail.configure(data))
                if method == 'POST' and path == '/api/gmail/connect':
                    return self.send({'url': app.gmail.connect_url(self.server.server_port)})
                if method == 'POST' and path == '/api/gmail/disconnect':
                    settings = app.store.setting('gmail_sync'); settings['enabled'] = False
                    app.store.set_setting('gmail_sync', settings)
                    return self.send(app.gmail.disconnect())
                if method == 'POST' and path == '/api/gmail/sync':
                    return self.send({'started': app.mail.sync(app.gmail)}, 202)
                if method == 'POST' and path == '/api/gmail/settings':
                    interval = int(data.get('interval_minutes', 30))
                    query = data.get('query', '')
                    if not isinstance(data.get('enabled'), bool) or not 15 <= interval <= 1440 or not isinstance(query, str) or len(query) > 1000:
                        raise ValueError('Use a 15–1440 minute interval and a query of at most 1,000 characters')
                    settings = {**app.store.setting('gmail_sync'), 'enabled': data['enabled'], 'interval_minutes': interval, 'query': query}
                    app.store.set_setting('gmail_sync', settings)
                    return self.send(settings)
                if method == 'POST' and path == '/api/mail/review':
                    return self.send(app.mail.review(data['id'], data['action'], data.get('job_id', ''), data.get('status', '')))
                if method == 'POST' and path == '/api/yc/discover':
                    return self.send({'started': app.discover_yc()}, 202)
                if method == 'GET' and path == '/api/research/status':
                    return self.send({'yc': app.yc_status, 'networking': app.networking.progress})
                if method == 'POST' and path == '/api/networking/settings':
                    if not isinstance(data.get('automatic'), bool):
                        raise ValueError('Choose automatic research on or off')
                    limit = int(data.get('max_per_run', 5))
                    if not 1 <= limit <= 20:
                        raise ValueError('Choose 1–20 company/role lookups per run')
                    config = {'automatic': data['automatic'], 'max_per_run': limit}
                    app.store.set_setting('networking', config)
                    return self.send(config)
                if method == "POST" and path == "/api/integrations/firecrawl":
                    key = data.get('key', '')
                    if not isinstance(key, str) or len(key) > 500 or any(ord(c) < 32 or ord(c) > 126 for c in key):
                        raise ValueError('Enter a valid API key')
                    app.firecrawl_key = key.strip()
                    return self.send({'configured': bool(app.firecrawl_key)})
                if method == "POST" and path in {"/api/web/extract", "/api/web/search"}:
                    if not app.firecrawl_lock.acquire(blocking=False):
                        return self.send({'error': 'A Firecrawl request is already running. Wait for it to finish.'}, 409)
                    try:
                        if path.endswith('/extract'):
                            return self.send({'job': firecrawl.extract(data['url'], app.firecrawl_key)})
                        return self.send({'results': firecrawl.search(data['query'], app.firecrawl_key)})
                    finally:
                        app.firecrawl_lock.release()
                if method == "POST" and path == "/api/workspace/metadata":
                    return self.send(app.workspace.save_metadata(data['job_id'], data))
                if method == "POST" and path == "/api/workspace/resumes":
                    return self.send(app.workspace.save_resume(data['name'], data['base64']))
                if method == "POST" and path == "/api/workspace/resume-variants":
                    return self.send(app.workspace.save_variant(data))
                if method == "POST" and path in {"/api/workspace/tasks", "/api/workspace/contacts", "/api/workspace/searches"}:
                    return self.send(app.workspace.save_record(path.rsplit('/', 1)[1], data))
                if method == "POST" and path == "/api/workspace/remove":
                    return self.send(app.workspace.remove_record(data['kind'], data['id']))
                if method == "POST" and path == "/api/workspace/goal":
                    goal = int(data['goal'])
                    if not 1 <= goal <= 500:
                        raise ValueError('Choose a weekly goal from 1 to 500')
                    app.store.set_setting('weekly_goal', goal)
                    return self.send({'goal': goal})
                if method == "POST" and path == "/api/application-queue":
                    return self.send(app.workspace.save_queue(data['ids']))
                if method == "GET" and path == "/api/calendar.ics":
                    return self.send(app.workspace.calendar(), content_type='text/calendar; charset=utf-8', filename='jobpilot-planner.ics')
                if method == "GET" and path == "/api/backup.zip":
                    return self.send(app.workspace.backup(), content_type='application/zip', filename='jobpilot-backup.zip')
                if method == "POST" and path == "/api/bundles":
                    return self.send(app.workspace.bundles(data['ids']), content_type='application/zip', filename='application-materials.zip')
                if method == "GET" and path == "/api/sync":
                    return self.send(app.sync_status)
                if method == "POST" and path == "/api/profile":
                    return self.send(app.store.save_profile(data))
                if method == "POST" and path == "/api/resume":
                    return self.send(app.store.save_resume(data["name"], data["base64"]))
                if method == "POST" and path == "/api/sources":
                    return self.send(app.store.save_source(data))
                if method == "POST" and path == "/api/discover":
                    return self.send({"started": app.sync(bool(data.get("prepare_matches")))}, 202)
                if method == "POST" and path == "/api/automation":
                    interval, size = float(data.get("interval_hours", 6)), int(data.get("batch_size", 20))
                    if not 1 <= interval <= 168 or not 1 <= size <= 100:
                        raise ValueError("Use 1–168 hours and batches of 1–100 applications")
                    config = {"enabled": bool(data.get("enabled")), "prepare_matches": bool(data.get("prepare_matches")),
                              "interval_hours": interval, "batch_size": size, "last_run": app.store.setting("automation")["last_run"]}
                    app.store.set_setting("automation", config)
                    return self.send(config)
                if method == "POST" and path == "/api/import":
                    jobs = data.get("jobs", [])
                    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 5000:
                        raise ValueError("Import 1–5,000 job records")
                    added = app.store.upsert_jobs(jobs)
                    if app.store.setting('networking')['automatic']:
                        from .sources import clean_url
                        imported_urls = {clean_url(j['url']) for j in jobs}
                        app.networking.start([j for j in app.store.jobs() if j['url'] in imported_urls])
                    return self.send({"added": added})
                if method == "POST" and path == "/api/batch":
                    if not isinstance(data.get('ids'), list) or any(not isinstance(x, str) for x in data['ids']):
                        raise ValueError('Choose a list of job IDs')
                    ids = list(dict.fromkeys(data.get("ids", [])))
                    action = data.get("action")
                    if not 1 <= len(ids) <= 100 or action not in {"prepare", "approve", "archive", "restore"}:
                        raise ValueError("Choose 1–100 jobs and prepare, approve, archive, or restore")
                    results = []
                    for jid in ids:
                        try:
                            app.store.action(jid, action)
                            results.append({"id": jid, "ok": True})
                        except ValueError as exc:
                            results.append({"id": jid, "ok": False, "error": str(exc)})
                    return self.send({"results": results})
                if method == "GET" and path == "/api/export":
                    return self.send({**app.store.bootstrap(), 'workspace': app.workspace.state()}, filename="jobpilot-export.json")
                if method == "GET" and path == "/api/export.csv":
                    stream = io.StringIO()
                    fields = ["id", "title", "company", "location", "url", "status", "match_percent", "skill_coverage_percent", "source", "created_at", "submitted_at", "notes", "priority", "salary", "deadline", "tags"]
                    metadata = app.workspace.state()['metadata']
                    writer = csv.DictWriter(stream, fields)
                    writer.writeheader()
                    for job in app.store.jobs():
                        job.update(match_percent=job["match"]["score"], skill_coverage_percent=job["match"]["qualification_percent"])
                        job.update(metadata.get(job['id'], {}))
                        job['tags'] = ', '.join(job.get('tags', []))
                        row = {k: job.get(k, "") for k in fields}
                        # Avoid spreadsheet formula injection from posting text.
                        row = {k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for k, v in row.items()}
                        writer.writerow(row)
                    return self.send(stream.getvalue(), content_type="text/csv; charset=utf-8", filename="applications.csv")
                if method == "GET" and path == "/api/extension.zip":
                    buf = io.BytesIO()
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                        for file in (ROOT / "extension").glob("*"):
                            if file.is_file():
                                z.writestr(file.name, file.read_bytes())
                    return self.send(buf.getvalue(), content_type="application/zip", filename="jobpilot-helper.zip")
                if method == "GET" and path == "/api/queue":
                    return self.send(app.workspace.queue())
                parts = path.split("/")
                if len(parts) in (4, 5) and parts[2] == "jobs":
                    jid = parts[3]
                    if len(parts) == 5 and parts[4] == 'networking':
                        job = app.store.job(jid)
                        if method == 'POST':
                            return self.send({'started': app.networking.start([job], force=True, limit=1)}, 202)
                        return self.send(app.networking.view(job))
                    if method == 'POST' and len(parts) == 5 and parts[4] == 'yc-details':
                        old = app.store.job(jid)
                        if old['source'] != 'yc':
                            raise ValueError('This is not a YC posting')
                        job, _, _ = yc.detail(old['url'])
                        app.store.upsert_jobs([job])
                        updated = app.store.job(jid)
                        if app.store.setting('networking')['automatic']:
                            app.networking.start([updated])
                        return self.send(updated)
                    if method == 'POST' and len(parts) == 5 and parts[4] == 'outreach':
                        job = app.store.job(jid)
                        cached = app.networking.cached(job) or {}
                        person = next((p for p in cached.get('people', []) if p['url'] == data.get('person_url')), None)
                        if data.get('contact_id'):
                            contact = next((c for c in app.workspace.state()['contacts'] if c['id'] == data['contact_id'] and c['job_id'] == jid), None)
                            if not contact:
                                raise ValueError('Choose a saved contact linked to this job')
                            person = {'name': contact['name']}
                        if data.get('person_url') and not person:
                            raise ValueError('Research this contact before drafting a message')
                        return self.send(drafts(app.store.setting('profile'), job, person))
                    if method == 'POST' and len(parts) == 5 and parts[4] == 'save-contact':
                        job = app.store.job(jid)
                        cached = app.networking.cached(job) or {}
                        person = next((p for p in cached.get('people', []) if p['url'] == data.get('person_url')), None)
                        if not person:
                            raise ValueError('Choose a researched contact candidate')
                        existing = next((p for p in app.workspace.state()['contacts'] if p['url'] == person['url'] and p['job_id'] == jid), None)
                        if existing:
                            return self.send(existing)
                        return self.send(app.workspace.save_record('contacts', {'name': person['name'], 'company': job['company'],
                            'url': person['url'], 'job_id': jid, 'notes': person['role'] + '\nSource: ' + person['source_url'] + '\n' + person['evidence'] + '\nVerify current employment before contacting.'}))
                    if method == "GET" and len(parts) == 4:
                        return self.send(app.store.job(jid))
                    if method == "POST" and len(parts) == 5 and parts[4] == "action":
                        return self.send(app.store.action(jid, data["action"], data.get("detail", "")))
                    if method == "POST" and len(parts) == 5 and parts[4] == "materials":
                        return self.send(app.workspace.save_materials(jid, data))
                    if method == "POST" and len(parts) == 5 and parts[4] == "resume":
                        return self.send(app.workspace.assign_resume(jid, data.get('resume_id', '')))
                    if method == "POST" and len(parts) == 5 and parts[4] == "resume-variant":
                        return self.send(app.workspace.assign_variant(jid, data.get('variant_id', '')))
                    if method == "GET" and len(parts) == 5 and parts[4] == "versions":
                        return self.send(app.workspace.material_versions(jid))
                    if method == "GET" and len(parts) == 5 and parts[4] == "resume.tex":
                        job = app.store.job(jid)
                        if not job['materials']:
                            raise ValueError('Prepare this application first')
                        return self.send(latex_resume.render_latex(job['materials']['resume']), content_type='application/x-tex; charset=utf-8', filename=f'resume-{jid}.tex')
                    if len(parts) == 5 and ((method == 'GET' and parts[4] == 'resume.pdf') or (method == 'POST' and parts[4] in ('use-generated-pdf', 'generate-pdf'))):
                        if not app.pdf_lock.acquire(blocking=False):
                            return self.send({'error': 'A résumé PDF is being compiled. Please wait, then try again.'}, 409)
                        try:
                            if parts[4] == 'use-generated-pdf':
                                return self.send(app.workspace.use_generated_pdf(jid))
                            asset = app.workspace.generate_pdf(jid)
                            if method == 'POST':
                                return self.send({k: v for k, v in asset.items() if k != 'base64'})
                            return self.send(base64.b64decode(asset['base64']), content_type='application/pdf', filename=asset['name'])
                        finally:
                            app.pdf_lock.release()
                    if method == "GET" and len(parts) == 5 and parts[4] == "bundle":
                        job = app.store.job(jid)
                        if not job["materials"]:
                            raise ValueError("Prepare this application first")
                        buf = io.BytesIO()
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                            for name, key in (("resume.txt", "resume"), ("resume.html", "resume_html"), ("cover-letter.txt", "cover_letter")):
                                z.writestr(name, job["materials"][key])
                            z.writestr('resume.tex', latex_resume.render_latex(job['materials']['resume']))
                            z.writestr('LICENSE-jake.txt', latex_resume.license_text())
                            if job['materials'].get('resume_pdf'):
                                asset = app.workspace.resume(job['materials']['resume_pdf']['id'])
                                z.writestr('resume.pdf', base64.b64decode(asset['base64']))
                            z.writestr("job.json", json.dumps({k: job[k] for k in ("title", "company", "url", "description", "match")}, indent=2))
                        return self.send(buf.getvalue(), content_type="application/zip", filename=f"application-{jid}.zip")
                    if method == "POST" and len(parts) == 5 and parts[4] == "claim":
                        job = app.store.action(jid, "claim")
                        profile = app.store.setting("profile")
                        resume = None
                        if job.get('resume_asset'):
                            resume = app.workspace.resume(job['resume_asset']['id'])
                        elif profile.get("resume_file"):
                            resume = {**profile["resume_file"], "base64": base64.b64encode((app.store.directory / "resume.bin").read_bytes()).decode()}
                        return self.send({"job": job, "profile": profile, "resume": resume})
                return self.send({"error": "Not found"}, 404)
            except (ValueError, KeyError, TypeError) as exc:
                self.send({"error": str(exc)}, 400)
            except Exception:
                self.send({"error": "An internal error occurred; your stored applications are preserved."}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="JobPilot — free, local job-search workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default=str(ROOT / "data"))
    args = parser.parse_args()
    app = App(Store(args.data))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_class(app))
    threading.Thread(target=app.scheduler, daemon=True).start()
    print(f"JobPilot is running at http://127.0.0.1:{args.port}", flush=True)
    print("Keep this process running for scheduled discovery. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
