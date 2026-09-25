import argparse
import base64
import csv
import io
import json
import mimetypes
import secrets
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .sources import discover
from .store import Store, now

ROOT = Path(__file__).resolve().parent.parent


class App:
    def __init__(self, store):
        self.store = store
        self.sync_lock = threading.Lock()
        self.sync_status = {"running": False, "message": "Ready to discover jobs", "added": 0}

    def sync(self, prepare_matches=False):
        if not self.sync_lock.acquire(blocking=False):
            return False
        self.sync_status = {"running": True, "message": "Reading public job boards…", "added": 0}
        def run():
            added, errors, total = 0, [], 0
            try:
                sources = [s for s in self.store.sources() if s["enabled"]]
                with ThreadPoolExecutor(max_workers=3) as pool:
                    futures = {pool.submit(discover, s): s for s in sources}
                    for future in as_completed(futures):
                        source = futures[future]
                        try:
                            jobs = future.result()
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
            except Exception as exc:
                self.sync_status = {"running": False, "added": added, "message": "Discovery failed", "errors": [str(exc)]}
            finally:
                self.sync_lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True

    def scheduler(self):
        while True:
            time.sleep(30)
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
                if not path.startswith("/api/"):
                    if method != "GET":
                        return self.send({"error": "Not found"}, 404)
                    if path == "/":
                        page = (ROOT / "static/index.html").read_text().replace("__TOKEN__", app.store.setting("token"))
                        return self.send(page, content_type="text/html; charset=utf-8")
                    assets = {"/app.js": "static/app.js", "/styles.css": "static/styles.css", "/icon.svg": "static/icon.svg"}
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
                    return self.send(state)
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
                    return self.send({"added": app.store.upsert_jobs(jobs)})
                if method == "POST" and path == "/api/batch":
                    ids = list(dict.fromkeys(data.get("ids", [])))
                    action = data.get("action")
                    if not 1 <= len(ids) <= 100 or action not in {"prepare", "approve", "archive"}:
                        raise ValueError("Choose 1–100 jobs and prepare, approve, or archive")
                    results = []
                    for jid in ids:
                        try:
                            app.store.action(jid, action)
                            results.append({"id": jid, "ok": True})
                        except ValueError as exc:
                            results.append({"id": jid, "ok": False, "error": str(exc)})
                    return self.send({"results": results})
                if method == "GET" and path == "/api/export":
                    return self.send(app.store.bootstrap(), filename="jobpilot-backup.json")
                if method == "GET" and path == "/api/export.csv":
                    stream = io.StringIO()
                    fields = ["id", "title", "company", "location", "url", "status", "match_percent", "skill_coverage_percent", "source", "created_at", "submitted_at", "notes"]
                    writer = csv.DictWriter(stream, fields)
                    writer.writeheader()
                    for job in app.store.jobs():
                        job.update(match_percent=job["match"]["score"], skill_coverage_percent=job["match"]["qualification_percent"])
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
                    return self.send([j for j in app.store.jobs() if j["status"] == "approved"])
                parts = path.split("/")
                if len(parts) in (4, 5) and parts[2] == "jobs":
                    jid = parts[3]
                    if method == "GET" and len(parts) == 4:
                        return self.send(app.store.job(jid))
                    if method == "POST" and len(parts) == 5 and parts[4] == "action":
                        return self.send(app.store.action(jid, data["action"], data.get("detail", "")))
                    if method == "GET" and len(parts) == 5 and parts[4] == "bundle":
                        job = app.store.job(jid)
                        if not job["materials"]:
                            raise ValueError("Prepare this application first")
                        buf = io.BytesIO()
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                            for name, key in (("resume.txt", "resume"), ("resume.html", "resume_html"), ("cover-letter.txt", "cover_letter")):
                                z.writestr(name, job["materials"][key])
                            z.writestr("job.json", json.dumps({k: job[k] for k in ("title", "company", "url", "description", "match")}, indent=2))
                        return self.send(buf.getvalue(), content_type="application/zip", filename=f"application-{jid}.zip")
                    if method == "POST" and len(parts) == 5 and parts[4] == "claim":
                        job = app.store.action(jid, "claim")
                        profile = app.store.setting("profile")
                        resume = None
                        if profile.get("resume_file"):
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
