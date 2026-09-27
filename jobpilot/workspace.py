"""Persistent planning and document tools for a single-person job search."""
import html
import base64
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .materials import fingerprint
from .sources import clean_url
from .latex_resume import render_latex, compile_pdf, license_text
from .store import now


def text(value, limit=4000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'Use text of at most {limit:,} characters')
    return value.strip()


def day(value):
    value = text(value, 10)
    if value and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or date.fromisoformat(value).isoformat() != value):
        raise ValueError('Use a valid date in YYYY-MM-DD format')
    return value


def boolean(value):
    if not isinstance(value, bool):
        raise ValueError('Expected true or false')
    return value


class Workspace:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS job_metadata(job_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_records(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS material_versions(id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS material_job ON material_versions(job_id, id);
                CREATE TABLE IF NOT EXISTS resume_assets(id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL, created_at TEXT NOT NULL);
            ''')

    def state(self):
        with self.store.db() as db:
            metadata = {r['job_id']: json.loads(r['payload']) for r in db.execute('SELECT * FROM job_metadata')}
            records = list(db.execute('SELECT * FROM workspace_records ORDER BY rowid DESC'))
            resumes = [dict(row) for row in db.execute('SELECT id,name,sha256,created_at FROM resume_assets ORDER BY created_at DESC')]
            variants = [json.loads(row[0]) for row in db.execute('SELECT payload FROM resume_variants ORDER BY rowid')]
        result = {kind: [json.loads(r['payload']) for r in records if r['kind'] == kind] for kind in ('tasks', 'contacts', 'searches')}
        result.update(metadata=metadata, resumes=resumes, resume_variants=variants, weekly_goal=self.store.setting('weekly_goal') or 10,
                      queue_ids=self.store.setting('queue_ids'))
        return result

    def save_variant(self, data):
        profile = self.store.setting('profile')
        variant = {'id': text(data.get('id', ''), 64) or uuid.uuid4().hex}
        for key in ('name', 'target_roles', 'headline'):
            variant[key] = text(data.get(key, ''), 500)
        if not variant['name'] or not variant['target_roles']:
            raise ValueError('Name and target roles are required')
        for key in ('skills', 'experience', 'projects'):
            selected = data.get(key, [])
            if not isinstance(selected, list) or any(not isinstance(x, str) or x not in profile.get(key, []) for x in selected):
                raise ValueError('Select evidence from your saved career profile')
            variant[key] = list(dict.fromkeys(selected))
        for key, default in (('max_skills', 20), ('max_experience', 8), ('max_projects', 4)):
            variant[key] = int(data.get(key, default))
            if not 1 <= variant[key] <= 50:
                raise ValueError('Choose limits from 1 to 50')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if data.get('id') and not db.execute('SELECT 1 FROM resume_variants WHERE id=?', (variant['id'],)).fetchone():
                raise ValueError('Résumé profile not found')
            db.execute('INSERT OR REPLACE INTO resume_variants VALUES (?,?)', (variant['id'], json.dumps(variant)))
            for row in db.execute("SELECT id FROM jobs WHERE status IN ('prepared','approved','needs_review','in_progress')").fetchall():
                db.execute("UPDATE jobs SET materials=NULL,approval=NULL,status='discovered',lease_until=NULL,updated_at=? WHERE id=?", (now(), row[0]))
                self.store.event(db, row[0], 'invalidated', 'Résumé profiles changed; prepare and review fresh materials')
        return variant

    def assign_variant(self, jid, variant_id):
        variant_id = text(variant_id, 64)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if variant_id and variant_id != 'general' and not db.execute('SELECT 1 FROM resume_variants WHERE id=?', (variant_id,)).fetchone():
                raise ValueError('Résumé profile not found')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['submitted_at'] or row['status'] in ('in_progress', 'submitting', 'submission_unknown', 'archived'):
                raise ValueError('Only pending applications can change résumé profiles')
            job = json.loads(row['payload'])
            if job.get('resume_variant_id', '') == variant_id:
                return {'ok': True}
            job['resume_variant_id'] = variant_id
            db.execute("UPDATE jobs SET payload=?,materials=NULL,approval=NULL,status='discovered',updated_at=? WHERE id=?", (json.dumps(job), now(), jid))
            self.store.event(db, jid, 'resume_profile_changed', 'Prepare materials using the selected résumé profile')
        return {'ok': True}

    def save_resume(self, name, encoded):
        name = Path(text(name, 240)).name
        if Path(name).suffix.lower() not in ('.pdf', '.docx', '.txt'):
            raise ValueError('Upload a PDF, DOCX, or TXT résumé')
        try:
            content = base64.b64decode(encoded, validate=True)
        except Exception:
            raise ValueError('Invalid file encoding') from None
        if not 1 <= len(content) <= 5 * 1024 * 1024:
            raise ValueError('Résumé must be between 1 byte and 5 MB')
        digest = hashlib.sha256(content).hexdigest()
        rid = uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('INSERT INTO resume_assets VALUES (?,?,?,?,?)', (rid, name, digest, content, now()))
        return {'id': rid, 'name': name, 'sha256': digest}

    def resume(self, rid):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM resume_assets WHERE id=?', (rid,)).fetchone()
            if not row:
                raise ValueError('Résumé not found')
            return {'id': rid, 'name': row['name'], 'sha256': row['sha256'], 'base64': base64.b64encode(row['content']).decode()}

    def assign_resume(self, jid, rid):
        asset = self.resume(rid) if rid else None
        if asset:
            asset.pop('base64')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['submitted_at'] or row['status'] in ('in_progress', 'submitting', 'submission_unknown'):
                raise ValueError('Cannot change the attachment of a running or submitted application')
            job = json.loads(row['payload'])
            if job.get('resume_asset') == asset:
                return {'ok': True}
            job['resume_asset'] = asset
            db.execute("UPDATE jobs SET payload=?,materials=NULL,approval=NULL,status=?,updated_at=? WHERE id=?",
                       (json.dumps(job), 'archived' if row['status'] == 'archived' else 'discovered', now(), jid))
            self.store.event(db, jid, 'attachment_changed', 'Prepare and review materials for the selected résumé')
        return {'ok': True}

    def save_metadata(self, jid, data):
        self.store.job(jid)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM job_metadata WHERE job_id=?', (jid,)).fetchone()
            result = json.loads(row[0]) if row else {'favorite': False, 'priority': 'normal', 'tags': [], 'salary': '', 'deadline': '', 'prep_notes': ''}
            for key in ('favorite', 'priority', 'tags', 'salary', 'deadline', 'prep_notes'):
                if key not in data:
                    continue
                value = data[key]
                if key == 'favorite':
                    value = boolean(value)
                elif key == 'priority':
                    if value not in ('low', 'normal', 'high'):
                        raise ValueError('Choose low, normal, or high priority')
                elif key == 'tags':
                    if not isinstance(value, list) or len(value) > 20:
                        raise ValueError('Use at most 20 tags')
                    value = list(dict.fromkeys(text(x, 40) for x in value if x))
                elif key == 'deadline':
                    value = day(value)
                else:
                    value = text(value, 20000 if key == 'prep_notes' else 200)
                result[key] = value
            db.execute('INSERT OR REPLACE INTO job_metadata VALUES (?, ?)', (jid, json.dumps(result)))
        return result

    def save_record(self, kind, data):
        if kind not in ('tasks', 'contacts', 'searches'):
            raise ValueError('Unknown record type')
        defaults = {
            'tasks': {'title': '', 'kind': 'follow_up', 'due_on': '', 'time': '', 'job_id': '', 'notes': '', 'done': False},
            'contacts': {'name': '', 'company': '', 'email': '', 'url': '', 'notes': '', 'job_id': ''},
            'searches': {'name': '', 'filters': {}},
        }[kind]
        rid = text(data.get('id', ''), 64) or uuid.uuid4().hex
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workspace_records WHERE id=? AND kind=?', (rid, kind)).fetchone()
            if data.get('id') and not row:
                raise ValueError('Record not found')
            record = json.loads(row['payload']) if row else {**defaults, 'id': rid, 'created_at': now()}
            for key in defaults:
                if key in data:
                    record[key] = data[key]
            for key in defaults:
                if key not in ('done', 'filters'):
                    record[key] = text(record[key], 12000 if key == 'notes' else 500)
            if not record.get('title', record.get('name')):
                raise ValueError('A title or name is required')
            if kind == 'tasks':
                record['due_on'] = day(record['due_on'])
                record['done'] = boolean(record['done'])
                if record['kind'] not in ('follow_up', 'interview', 'application', 'other'):
                    raise ValueError('Unknown task type')
                if record['time'] and (not record['due_on'] or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', record['time'])):
                    raise ValueError('Set a date and a valid local time (HH:MM)')
            if record.get('job_id') and not db.execute('SELECT 1 FROM jobs WHERE id=?', (record['job_id'],)).fetchone():
                raise ValueError('Job not found')
            if kind == 'contacts':
                if record['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', record['email']):
                    raise ValueError('Enter a valid email address')
                if record['url']:
                    record['url'] = clean_url(record['url'])
            if kind == 'searches':
                filters = record['filters']
                if not isinstance(filters, dict):
                    raise ValueError('Invalid saved filters')
                allowed = {'query', 'status', 'eligible', 'favorite', 'source', 'sort', 'tag'}
                record['filters'] = {k: boolean(v) if k in ('eligible', 'favorite') else text(v, 300)
                                     for k, v in filters.items() if k in allowed}
            record['updated_at'] = now()
            db.execute('INSERT OR REPLACE INTO workspace_records VALUES (?, ?, ?)', (rid, kind, json.dumps(record)))
        return record

    def remove_record(self, kind, rid):
        if kind not in ('tasks', 'contacts', 'searches'):
            raise ValueError('Unknown record type')
        with self.store.db() as db:
            db.execute('DELETE FROM workspace_records WHERE kind=? AND id=?', (kind, rid))
        return {'ok': True}

    def save_materials(self, jid, data):
        resume = text(data.get('resume', ''), 60000)
        cover = text(data.get('cover_letter', ''), 30000)
        if not resume or not cover:
            raise ValueError('Résumé and cover letter cannot be empty')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if not row or row['status'] not in ('prepared', 'approved', 'needs_review') or not row['materials']:
                raise ValueError('Prepare the application first; running or submitted materials cannot be edited')
            materials = json.loads(row['materials'])
            if materials['fingerprint'] != fingerprint(self.store.setting('profile'), json.loads(row['payload'])):
                raise ValueError('Profile or posting changed; prepare fresh materials first')
            if not db.execute('SELECT 1 FROM material_versions WHERE job_id=?', (jid,)).fetchone():
                db.execute('INSERT INTO material_versions(job_id,payload,created_at) VALUES (?,?,?)', (jid, row['materials'], now()))
            materials.update(resume=resume, cover_letter=cover,
                             resume_html='<!doctype html><html><head><meta charset="utf-8"><title>Résumé</title><style>body{font:11pt/1.5 Arial;margin:18mm;white-space:pre-wrap;overflow-wrap:anywhere}@page{size:A4;margin:18mm}</style></head><body>' + html.escape(resume) + '</body></html>',
                             note='Edited by you. Review every claim and the original attachment before approving.')
            materials['resume_latex'] = render_latex(resume)
            materials.pop('resume_pdf', None)
            encoded = json.dumps(materials)
            db.execute('INSERT INTO material_versions(job_id,payload,created_at) VALUES (?,?,?)', (jid, encoded, now()))
            db.execute("UPDATE jobs SET materials=?,approval=NULL,status='prepared',updated_at=? WHERE id=?", (encoded, now(), jid))
            self.store.event(db, jid, 'materials_edited', 'Saved a new draft revision; approval cleared')
        return self.store.job(jid)

    def generate_pdf(self, jid):
        job = self.store.job(jid)
        material = job['materials']
        if not material:
            raise ValueError('Prepare the application first')
        source_hash = hashlib.sha256(material['resume'].encode()).hexdigest()
        cached = material.get('resume_pdf')
        if cached and cached.get('source_hash') == source_hash:
            return self.resume(cached['id'])
        content = compile_pdf(material['resume'])
        asset = {'id': uuid.uuid4().hex, 'name': f'resume-{jid}.pdf', 'sha256': hashlib.sha256(content).hexdigest()}
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT materials FROM jobs WHERE id=?', (jid,)).fetchone()
            current = json.loads(row[0]) if row and row[0] else None
            if not current or current['resume'] != material['resume']:
                raise ValueError('Résumé changed during compilation. Generate the PDF again from the latest draft.')
            db.execute('INSERT INTO resume_assets VALUES (?,?,?,?,?)', (asset['id'], asset['name'], asset['sha256'], content, now()))
            current['resume_pdf'] = {**asset, 'source_hash': source_hash}
            db.execute('UPDATE jobs SET materials=? WHERE id=?', (json.dumps(current), jid))
        return {**asset, 'base64': base64.b64encode(content).decode()}

    def use_generated_pdf(self, jid):
        asset = self.generate_pdf(jid)
        asset.pop('base64')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
            if row['status'] not in ('prepared', 'approved', 'needs_review'):
                raise ValueError('Only pending, reviewed applications can change attachments')
            job = json.loads(row['payload'])
            material = json.loads(row['materials'])
            if material.get('resume_pdf', {}).get('id') != asset['id']:
                raise ValueError('Draft changed; generate a fresh PDF first')
            profile = json.loads(db.execute("SELECT value FROM settings WHERE key='profile'").fetchone()[0])
            if material['fingerprint'] != fingerprint(profile, job):
                raise ValueError('Profile changed; prepare fresh materials first')
            job['resume_asset'] = asset
            material['fingerprint'] = fingerprint(profile, job)
            db.execute("UPDATE jobs SET payload=?,materials=?,approval=NULL,status='prepared',updated_at=? WHERE id=?",
                       (json.dumps(job), json.dumps(material), now(), jid))
            self.store.event(db, jid, 'generated_resume_selected', 'Tailored LaTeX PDF selected; review and approve before applying')
        return self.store.job(jid)

    def material_versions(self, jid):
        self.store.job(jid)
        with self.store.db() as db:
            return [{'id': r['id'], 'created_at': r['created_at'], **json.loads(r['payload'])}
                    for r in db.execute('SELECT * FROM material_versions WHERE job_id=? ORDER BY id DESC', (jid,))]

    def save_queue(self, ids):
        if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(x, str) for x in ids):
            raise ValueError('Choose up to 100 approved applications')
        ids = list(dict.fromkeys(ids))
        approved = {j['id'] for j in self.store.jobs() if j['status'] == 'approved'}
        if any(jid not in approved for jid in ids):
            raise ValueError('Only approved applications can enter the queue')
        self.store.set_setting('queue_ids', ids)
        return {'ids': ids}

    def queue(self):
        ids = self.store.setting('queue_ids')
        jobs = {j['id']: j for j in self.store.jobs() if j['status'] == 'approved'}
        return list(jobs.values()) if ids is None else [jobs[jid] for jid in ids if jid in jobs]

    def calendar(self):
        def escape(value):
            return value.replace('\\', '\\\\').replace('\r', '').replace('\n', '\\n').replace(';', '\\;').replace(',', '\\,')
        lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//JobPilot//Planner//EN', 'CALSCALE:GREGORIAN']
        for task in self.state()['tasks']:
            if task['done'] or not task['due_on']:
                continue
            lines += ['BEGIN:VEVENT', 'UID:' + task['id'] + '@jobpilot.local', 'DTSTAMP:' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')]
            if task['time']:
                start = datetime.fromisoformat(task['due_on'] + 'T' + task['time'])
                lines += ['DTSTART:' + start.strftime('%Y%m%dT%H%M%S'), 'DTEND:' + (start + timedelta(hours=1)).strftime('%Y%m%dT%H%M%S')]
            else:
                lines += ['DTSTART;VALUE=DATE:' + task['due_on'].replace('-', ''),
                          'DTEND;VALUE=DATE:' + (date.fromisoformat(task['due_on']) + timedelta(days=1)).strftime('%Y%m%d')]
            lines += ['SUMMARY:' + escape(task['title']), 'DESCRIPTION:' + escape(task['notes']), 'END:VEVENT']
        lines.append('END:VCALENDAR')
        # RFC 5545 folding uses octets, not characters; keep UTF-8 codepoints intact.
        folded = []
        for line in lines:
            part = ''
            for char in line:
                if len((part + char).encode('utf-8')) > 74:
                    folded.append(part)
                    part = ' '
                part += char
            folded.append(part)
        return '\r\n'.join(folded) + '\r\n'

    def bundles(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(x, str) for x in ids):
            raise ValueError('Select 1–100 prepared applications')
        jobs = [self.store.job(jid) for jid in dict.fromkeys(ids)]
        if any(not job['materials'] for job in jobs):
            raise ValueError('Prepare every selected application before downloading')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
            for job in jobs:
                for name, key in (('resume.txt', 'resume'), ('resume.html', 'resume_html'), ('cover-letter.txt', 'cover_letter')):
                    archive.writestr(job['id'] + '/' + name, job['materials'][key])
                archive.writestr(job['id'] + '/resume.tex', render_latex(job['materials']['resume']))
                archive.writestr(job['id'] + '/LICENSE-jake.txt', license_text())
                if job['materials'].get('resume_pdf'):
                    asset = self.resume(job['materials']['resume_pdf']['id'])
                    archive.writestr(job['id'] + '/resume.pdf', base64.b64decode(asset['base64']))
                archive.writestr(job['id'] + '/job.json', json.dumps({k: job[k] for k in ('title', 'company', 'url', 'description')}, indent=2))
        return buf.getvalue()

    def backup(self):
        buf = io.BytesIO()
        with tempfile.TemporaryDirectory(prefix='backup-', dir=self.store.directory) as directory:
            target = Path(directory) / 'jobpilot.sqlite3'
            dest = sqlite3.connect(target)
            try:
                with self.store.db() as source:
                    source.backup(dest)
                profile_row = dest.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
                profile = json.loads(profile_row[0]) if profile_row else {}
                dest.execute('PRAGMA secure_delete=ON')
                dest.execute("DELETE FROM settings WHERE key='token'")
                dest.commit()
                dest.execute('VACUUM')
            finally:
                dest.close()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(target, 'jobpilot.sqlite3')
                resume = self.store.directory / 'resume.bin'
                if profile.get('resume_file'):
                    content = resume.read_bytes()
                    if hashlib.sha256(content).hexdigest() != profile['resume_file']['sha256']:
                        raise ValueError('Résumé changed during backup. Please try again.')
                    archive.writestr('resume.bin', content)
                archive.writestr('RESTORE.txt', 'Stop JobPilot. Extract into a NEW private folder. Run python -m jobpilot --data "path/to/folder". Reconnect the helper using the newly generated token. This backup contains private career information.\n')
        return buf.getvalue()
