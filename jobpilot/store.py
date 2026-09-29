import base64
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .matching import match
from .materials import prepare, fingerprint
from .roles import suggest_roles
from .sources import clean_url, validate_source
from .tailoring import prepare_for_job

DEFAULT_PROFILE = {"name": "", "first_name": "", "last_name": "", "email": "", "phone": "", "location": "", "headline": "", "linkedin": "", "website": "",
                   "skills": [], "technologies": [], "experience": [], "projects": [], "education": [],
                   "certifications": [], "achievements": [], "languages": [], "resume_text": "", "roles": [],
                   "locations": [], "excluded_companies": [], "excluded_keywords": [], "required_keywords": [],
                   "years_experience": None, "needs_sponsorship": "unknown", "min_score": 45, "max_age_days": 45, "answers": {}}
DEFAULT_SOURCES = [
    {"kind": "yc", "board": "engineering", "company": "YC engineering startups", "enabled": True},
    {"kind": "greenhouse", "board": "stripe", "company": "Stripe", "enabled": True},
    {"kind": "greenhouse", "board": "cloudflare", "company": "Cloudflare", "enabled": True},
    {"kind": "greenhouse", "board": "hubspot", "company": "HubSpot", "enabled": True},
    {"kind": "greenhouse", "board": "canonical", "company": "Canonical", "enabled": True},
    {"kind": "lever", "board": "palantir", "company": "Palantir", "enabled": True},
    {"kind": "lever", "board": "spotify", "company": "Spotify", "enabled": True},
    {"kind": "ashby", "board": "notion", "company": "Notion", "enabled": True},
    {"kind": "ashby", "board": "deel", "company": "Deel", "enabled": True},
    {"kind": "ashby", "board": "linear", "company": "Linear", "enabled": True},
]
STATUSES = {"discovered", "prepared", "approved", "in_progress", "needs_review", "submitting", "submission_unknown", "submitted", "interview", "offer", "rejected", "archived"}


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "jobpilot.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, url TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                  status TEXT NOT NULL DEFAULT 'discovered', materials TEXT, approval TEXT, notes TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, submitted_at TEXT, lease_until TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, board TEXT NOT NULL,
                  company TEXT NOT NULL, enabled INTEGER NOT NULL, last_sync TEXT, count INTEGER DEFAULT 0, error TEXT,
                  UNIQUE(kind, board));
                CREATE TABLE IF NOT EXISTS resume_variants(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
            for key, value in (("profile", DEFAULT_PROFILE), ("token", secrets.token_urlsafe(32)),
                               ("automation", {"enabled": False, "interval_hours": 6, "prepare_matches": False, "batch_size": 20, "last_run": None})):
                db.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (key, json.dumps(value)))
            for source in DEFAULT_SOURCES:
                db.execute("INSERT OR IGNORE INTO sources(kind,board,company,enabled) VALUES(:kind,:board,:company,:enabled)", source)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key):
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key, value):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def event(self, db, job_id, kind, detail=""):
        db.execute("INSERT INTO events(job_id,kind,detail,created_at) VALUES(?,?,?,?)", (job_id, kind, str(detail)[:4000], now()))

    def save_profile(self, incoming):
        profile = dict(DEFAULT_PROFILE)
        for key, default in DEFAULT_PROFILE.items():
            value = incoming.get(key, default)
            if isinstance(default, list):
                if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                    raise ValueError(f"{key} must be a list of text values")
                profile[key] = list(dict.fromkeys(x.strip()[:3000] for x in value[:300] if x.strip()))
            elif key == "answers":
                if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
                    raise ValueError("Answers must map exact question text to your answer")
                profile[key] = {str(k)[:500]: v[:4000] for k, v in value.items()}
            elif key == "years_experience":
                profile[key] = None if value in (None, "") else float(value)
                if profile[key] is not None and not 0 <= profile[key] <= 80:
                    raise ValueError("Experience must be between 0 and 80 years")
            elif isinstance(default, int):
                profile[key] = int(value)
            else:
                profile[key] = str(value or "")[:30000]
        if not 0 <= profile["min_score"] <= 100 or not 1 <= profile["max_age_days"] <= 365:
            raise ValueError("Score must be 0–100 and maximum age 1–365 days")
        if profile['needs_sponsorship'] not in ('yes', 'no', 'unknown'):
            raise ValueError('Sponsorship preference must be yes, no, or unknown')
        if profile["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", profile["email"]):
            raise ValueError("Enter a valid email address")
        profile["skills"] = list(dict.fromkeys(profile["skills"] + profile["technologies"]))
        old = self.setting("profile")
        if old.get("resume_file"):
            profile["resume_file"] = old["resume_file"]
        suggestions = suggest_roles(profile)
        if not profile["roles"]:
            profile["roles"] = [x["role"] for x in suggestions[:5]]
        self.set_setting("profile", profile)
        if old != profile:
            self.invalidate_approvals("Profile changed; prepare and review updated materials")
        return {"profile": profile, "suggestions": suggestions}

    def invalidate_approvals(self, reason):
        with self.db() as db:
            for row in db.execute("SELECT id FROM jobs WHERE status IN ('prepared','approved','needs_review','in_progress')").fetchall():
                db.execute("UPDATE jobs SET status='discovered',approval=NULL,materials=NULL,lease_until=NULL,updated_at=? WHERE id=?", (now(), row[0]))
                self.event(db, row[0], "invalidated", reason)

    def save_resume(self, name, encoded):
        if Path(name).suffix.lower() not in {".pdf", ".docx", ".txt"}:
            raise ValueError("Upload a PDF, DOCX, or TXT résumé")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("Invalid file encoding") from exc
        if not raw or len(raw) > 5 * 1024 * 1024:
            raise ValueError("Résumé must be between 1 byte and 5 MB")
        profile = self.setting("profile")
        profile["resume_file"] = {"name": Path(name).name, "sha256": hashlib.sha256(raw).hexdigest()}
        path = self.directory / "resume.bin"
        path.write_bytes(raw)
        path.chmod(0o600)
        self.set_setting("profile", profile)
        self.invalidate_approvals("Résumé file changed")
        return profile["resume_file"]

    def sources(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sources ORDER BY company")]

    def save_source(self, data):
        source = validate_source(data)
        with self.db() as db:
            db.execute("INSERT INTO sources(kind,board,company,enabled) VALUES(:kind,:board,:company,:enabled) ON CONFLICT(kind,board) DO UPDATE SET company=excluded.company,enabled=excluded.enabled", source)
        return self.sources()

    def upsert_jobs(self, jobs):
        normalized = []
        for job in jobs:
            if not isinstance(job, dict):
                raise ValueError("Each job must be a JSON object")
            if not str(job.get("title", "")).strip() or not str(job.get("company", "")).strip():
                raise ValueError("Every job needs a title and company")
            remote = bool(job.get("remote"))
            partial = bool(job.get('description_partial', False))
            yc_fields = {k: str(job.get(k, '') or '')[:500] for k in ('yc_batch', 'yc_activity', 'company_url')}
            job = {k: str(job.get(k, "") or "")[:60000] for k in
                   ("title", "company", "location", "url", "description", "source", "board", "external_id", "posted_at")}
            job["url"] = clean_url(job["url"])
            job["remote"] = remote
            if job['source'] == 'yc':
                from .yc import public_url
                if yc_fields['company_url']:
                    yc_fields['company_url'] = public_url(yc_fields['company_url'])
                job.update(yc_fields, description_partial=partial)
            normalized.append(job)
        added = 0
        with self.db() as db:
            for job in normalized:
                # ATS identity dedup survives source URL changes; URL dedup covers manual imports.
                identity = job["source"] + ":" + job["board"] + ":" + job["external_id"] if job["external_id"] and job["board"] else job["url"]
                jid = hashlib.sha256(identity.encode()).hexdigest()[:20]
                existing = db.execute("SELECT * FROM jobs WHERE id=? OR url=?", (jid, job["url"])).fetchone()
                if existing:
                    previous = json.loads(existing["payload"])
                    if job.get('description_partial') and previous.get('source') == 'yc' and not previous.get('description_partial', True):
                        # Listing refreshes must not overwrite hydrated descriptions.
                        job['description'] = previous['description']
                        job['description_partial'] = False
                    if previous.get('resume_asset'):
                        job['resume_asset'] = previous['resume_asset']
                    if previous.get('resume_variant_id'):
                        job['resume_variant_id'] = previous['resume_variant_id']
                    # Do not destroy ATS metadata on a duplicate manual import.
                    if not job["external_id"] and previous.get("external_id"):
                        continue
                    changed = any(previous.get(k) != job.get(k) for k in ("title", "description", "url", "location", "company"))
                    db.execute("UPDATE jobs SET payload=?,url=?,updated_at=? WHERE id=?", (json.dumps(job), job["url"], now(), existing["id"]))
                    if changed and existing["status"] in {"prepared", "approved", "needs_review", "in_progress"}:
                        db.execute("UPDATE jobs SET status='discovered',materials=NULL,approval=NULL,lease_until=NULL WHERE id=?", (existing["id"],))
                        self.event(db, existing["id"], "invalidated", "Posting changed; review again")
                else:
                    db.execute("INSERT INTO jobs(id,url,payload,created_at,updated_at) VALUES(?,?,?,?,?)", (jid, job["url"], json.dumps(job), now(), now()))
                    self.event(db, jid, "discovered", job["source"] or "manual import")
                    added += 1
        return added

    def jobs(self):
        profile = self.setting("profile")
        with self.db() as db:
            rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
            # Use the full ledger, not the dashboard's 100-event activity window.
            # Archiving or later rejection must not erase a recorded interview.
            outcomes = {}
            for event in db.execute("SELECT DISTINCT job_id,kind FROM events WHERE kind IN ('interview','offer','rejected')"):
                outcomes.setdefault(event["job_id"], []).append(event["kind"])
        result = []
        for row in rows:
            item = json.loads(row["payload"])
            item.update({k: row[k] for k in ("id", "status", "notes", "created_at", "updated_at", "submitted_at")})
            item["match"] = match(item, profile)
            item["has_materials"] = bool(row["materials"])
            item["outcomes"] = sorted(outcomes.get(row["id"], []))
            result.append(item)
        return sorted(result, key=lambda j: (-j["match"]["score"], j["title"]))

    def job(self, jid):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise ValueError("Job not found")
            result = dict(row)
            result.update(json.loads(row["payload"]))
            result["materials"] = json.loads(row["materials"]) if row["materials"] else None
            result["events"] = [dict(x) for x in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id DESC", (jid,))]
            result.pop("payload", None)
            result["match"] = match(result, self.setting("profile"))
            return result

    def action(self, jid, action, detail=""):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row:
                raise ValueError("Job not found")
            job, status = json.loads(row["payload"]), row["status"]
            profile = self.setting("profile")
            new_status = status
            if action == "prepare":
                if job.get('description_partial'):
                    raise ValueError('Load the complete YC posting before preparing this application')
                if status not in {"discovered", "prepared", "needs_review"}:
                    raise ValueError("This application cannot be prepared in its current state")
                variants = [json.loads(r[0]) for r in db.execute('SELECT payload FROM resume_variants ORDER BY rowid')]
                materials = prepare_for_job(profile, job, variants)
                db.execute("UPDATE jobs SET materials=?,approval=NULL WHERE id=?", (json.dumps(materials), jid))
                new_status = "prepared"
            elif action == "approve":
                if status not in {"prepared", "needs_review"} or not row["materials"]:
                    raise ValueError("Prepare and review the application first")
                materials = json.loads(row["materials"])
                if materials["fingerprint"] != fingerprint(profile, job):
                    raise ValueError("Profile or job changed; prepare again")
                if not match(job, profile)["eligible"]:
                    raise ValueError("Job conflicts with your filters; adjust the filters before approving")
                db.execute("UPDATE jobs SET approval=? WHERE id=?", (materials["fingerprint"], jid))
                new_status = "approved"
            elif action == "claim":
                if status != "approved":
                    raise ValueError("Application is not approved or has already been claimed")
                if row["approval"] != fingerprint(profile, job):
                    raise ValueError("Approval is stale; prepare and approve again")
                new_status = "in_progress"
                db.execute("UPDATE jobs SET lease_until=? WHERE id=?", ((datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(), jid))
            elif action == "submitting":
                if status != "in_progress" or row["approval"] != fingerprint(profile, job):
                    raise ValueError("Submission requires a current, claimed approval")
                new_status = "submitting"
            elif action in {"submitted", "submitted_manual"}:
                allowed = {"submitting", "in_progress", "needs_review", "approved", "submission_unknown"}
                if action == "submitted_manual":
                    allowed |= {"discovered", "prepared"}
                if status not in allowed:
                    raise ValueError("Application has already been recorded or is not ready")
                if not str(detail).strip():
                    raise ValueError("Record the confirmation or explain how submission was verified")
                new_status = "submitted"
                db.execute("UPDATE jobs SET submitted_at=?,lease_until=NULL WHERE id=?", (now(), jid))
            elif action == "needs_review":
                if status not in {"in_progress", "approved"}:
                    raise ValueError("Application is not running")
                new_status = "needs_review"
            elif action == "submission_unknown":
                if status != "submitting":
                    raise ValueError("No submission attempt is in progress")
                new_status = "submission_unknown"
            elif action in {"interview", "offer", "rejected"}:
                if status not in {"submitted", "interview", "offer", "rejected"}:
                    raise ValueError("Record a confirmed application before updating its outcome")
                new_status = action
            elif action == "archive":
                if status == 'archived':
                    raise ValueError('Application is already archived')
                if status in {"in_progress", "submitting", "submission_unknown"}:
                    raise ValueError("Resolve the running or uncertain attempt first")
                new_status = "archived"
                detail = json.dumps({"previous_status": status})
            elif action == "restore":
                if status != "archived":
                    raise ValueError("Only archived applications can be restored")
                if row["submitted_at"]:
                    archived = db.execute("SELECT detail FROM events WHERE job_id=? AND kind='archive' ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
                    try:
                        previous = json.loads(archived[0]).get("previous_status") if archived else None
                    except (ValueError, TypeError):
                        previous = None
                    new_status = previous if previous in {"submitted", "interview", "offer", "rejected"} else "submitted"
                else:
                    new_status = "discovered"
                    db.execute("UPDATE jobs SET materials=NULL,approval=NULL,lease_until=NULL WHERE id=?", (jid,))
            elif action == "note":
                db.execute("UPDATE jobs SET notes=? WHERE id=?", (str(detail)[:12000], jid))
            else:
                raise ValueError("Unknown action")
            db.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", (new_status, now(), jid))
            self.event(db, jid, action, detail)
        return self.job(jid)

    def recover(self):
        with self.db() as db:
            for row in db.execute("SELECT id,status FROM jobs WHERE status IN ('in_progress','submitting') AND lease_until < ?", (now(),)).fetchall():
                status = "submission_unknown" if row["status"] == "submitting" else "needs_review"
                db.execute("UPDATE jobs SET status=?,lease_until=NULL WHERE id=?", (status, row["id"]))
                self.event(db, row["id"], status, "Browser session expired; verify the application before continuing")

    def bootstrap(self):
        self.recover()
        with self.db() as db:
            events = [dict(x) for x in db.execute("SELECT events.*,json_extract(jobs.payload,'$.company') company,json_extract(jobs.payload,'$.title') title FROM events LEFT JOIN jobs ON jobs.id=events.job_id ORDER BY events.id DESC LIMIT 100")]
        return {"profile": self.setting("profile"), "suggestions": suggest_roles(self.setting("profile")),
                "jobs": self.jobs(), "sources": self.sources(), "events": events, "automation": self.setting("automation")}
