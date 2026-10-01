"""Validate portable backups in an isolated directory before activating them."""
import base64
import hashlib
import io
import json
import secrets
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

MAX_ZIP = 64 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024


def active_directory(root):
    root = Path(root).resolve()
    pointer = root / 'active-workspace.json'
    if not pointer.exists():
        return root
    name = json.loads(pointer.read_text())['directory']
    directory = (root / name).resolve()
    if not directory.is_relative_to(root / 'restored') or not (directory / 'jobpilot.sqlite3').is_file():
        raise ValueError('Invalid active workspace path')
    return directory


def stage_backup(encoded, root, reference_store):
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError('Choose a JobPilot backup ZIP') from None
    if not content or len(content) > MAX_ZIP:
        raise ValueError('Backup ZIP must be no larger than 64 MB')
    target_root = Path(root) / 'restored'
    target_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = Path(tempfile.mkdtemp(prefix='workspace-', dir=target_root))
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or set(names) - {'jobpilot.sqlite3', 'resume.bin', 'RESTORE.txt'} or 'jobpilot.sqlite3' not in names:
                raise ValueError('Not a supported JobPilot backup ZIP')
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                raise ValueError('Expanded backup exceeds 256 MB')
            for name in ('jobpilot.sqlite3', 'resume.bin'):
                if name in names:
                    path = target / name
                    path.write_bytes(archive.read(name))
                    path.chmod(0o600)
        with sqlite3.connect(target / 'jobpilot.sqlite3') as db, reference_store.db() as reference:
            db.execute('PRAGMA trusted_schema=OFF')
            schema = lambda conn: dict(conn.execute("SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
            if schema(db) != schema(reference):
                raise ValueError('Backup database format differs. Use the same JobPilot version on both computers.')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Backup database is damaged')
            for table, column in [('settings', 'value'), ('jobs', 'payload'), ('resume_variants', 'payload'), ('job_metadata', 'payload'), ('workspace_records', 'payload'), ('material_versions', 'payload'), ('networking_cache', 'payload')]:
                for value, in db.execute(f'SELECT {column} FROM {table}'):
                    json.loads(value)
            profile = json.loads(db.execute("SELECT value FROM settings WHERE key='profile'").fetchone()[0])
            resume = profile.get('resume_file')
            if resume and ('resume.bin' not in names or hashlib.sha256((target / 'resume.bin').read_bytes()).hexdigest() != resume['sha256']):
                raise ValueError('Default résumé is missing or damaged')
            for name, digest, blob in db.execute('SELECT name,sha256,content FROM resume_assets'):
                if hashlib.sha256(blob).hexdigest() != digest:
                    raise ValueError('A résumé library file is damaged')
            jobs = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
            resumes = db.execute('SELECT count(*) FROM resume_assets').fetchone()[0]
            # Never resume an old computer's background work or submission approvals.
            for key in ('automation', 'gmail_sync'):
                row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
                value = json.loads(row[0]); value['enabled'] = False
                db.execute('UPDATE settings SET value=? WHERE key=?', (json.dumps(value), key))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('token',?)", (json.dumps(secrets.token_urlsafe(32)),))
            db.execute("INSERT OR REPLACE INTO settings VALUES ('queue_ids','[]')")
            db.execute("UPDATE jobs SET status=CASE WHEN status='submitting' THEN 'submission_unknown' WHEN status='in_progress' THEN 'needs_review' WHEN status='approved' THEN 'prepared' ELSE status END,approval=NULL,lease_until=NULL")
        return target, {'name': profile.get('name', ''), 'jobs': jobs, 'resumes': resumes, 'default_resume': (resume or {}).get('name', '')}
    except Exception as exc:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(exc, ValueError):
            raise
        raise ValueError('Backup is invalid or damaged') from None
