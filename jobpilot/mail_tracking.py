"""Local email classification and reviewable application-outcome suggestions."""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from .matching import contains, tokens
from .store import now

STAGES = {
    'rejected': r'not (?:be )?(?:moving|move|proceeding|proceed) forward|moving forward with other candidates|unfortunately.{0,100}(?:application|position)|regret to inform|application.{0,50}(?:unsuccessful|not selected)',
    'offer': r'offer of employment|pleased to (?:extend|offer you)|formal (?:job )?offer|employment offer',
    'interview': r'(?:schedule|arrange|invite you to).{0,40}(?:interview|technical screen)|interview availability|invitation to interview|next (?:interview )?round',
    'submitted': r'(?:received|submitted).{0,60}(?:your )?application|application.{0,60}(?:received|submitted)|thank(?:s| you) for applying',
}


def classify(message, jobs):
    text = message['subject'] + '\n' + message.get('text', '')
    # Ignore common quoted-reply tails, which often contain an earlier stage.
    text = re.split(r'\n(?:On .{5,200}wrote:|[- ]*Original Message[- ]*|>\s*)', text, maxsplit=1)[0][:30000]
    stage, reason = None, ''
    for status, pattern in STAGES.items():
        found = re.search(pattern, text, re.I | re.S)
        if found:
            stage, reason = status, found[0][:220]
            break
    if stage is None:
        return None
    candidates = []
    for job in jobs:
        company = contains(text + ' ' + message.get('sender', ''), job['company'])
        exact_url = job['url'].rstrip('/') in text
        title = contains(text, job['title'])
        words = tokens(job['title']) - {'senior', 'junior', 'staff', 'lead'}
        overlap = len(words & tokens(text)) / max(1, len(words))
        if exact_url or company and (title or overlap >= 0.6):
            candidates.append({'id': job['id'], 'title': job['title'], 'company': job['company'],
                               'confidence': 'high' if exact_url or company and title else 'review',
                               'reason': 'Exact posting URL in email' if exact_url else 'Company and role text match'})
    return {'suggested_status': stage, 'reason': reason, 'candidates': candidates[:10],
            'suggested_job_id': candidates[0]['id'] if len(candidates) == 1 else '',
            'confidence': candidates[0]['confidence'] if len(candidates) == 1 else 'ambiguous' if candidates else 'unmatched'}


class MailTracker:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.progress = {'running': False, 'message': 'Gmail has not been synced', 'imported': 0}
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS mail_events(
                id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
                job_id TEXT,created_at TEXT NOT NULL,reviewed_at TEXT)''')
        if store.setting('gmail_sync') is None:
            store.set_setting('gmail_sync', {'enabled': False, 'interval_minutes': 30, 'query': '', 'last_run': None})

    def state(self):
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM mail_events ORDER BY created_at DESC LIMIT 200').fetchall()
        return {'events': [{**json.loads(r['payload']), 'id': r['id'], 'review_status': r['status'], 'job_id': r['job_id']} for r in rows],
                'progress': self.progress, 'settings': self.store.setting('gmail_sync')}

    def ingest(self, account, messages):
        jobs = self.store.jobs()
        count = 0
        for message in messages:
            result = classify(message, jobs)
            if result is None:
                continue
            key = hashlib.sha256((account + ':' + message['id']).encode()).hexdigest()
            payload = {**result, 'message_id': message['id'], 'account': account,
                       'subject': message['subject'], 'sender': message['sender'], 'url': message['url'],
                       'received_at': message.get('received_at', ''), 'excerpt': message.get('text', '')[:1500]}
            with self.store.db() as db:
                cursor = db.execute('INSERT OR IGNORE INTO mail_events(id,payload,created_at) VALUES(?,?,?)', (key, json.dumps(payload), now()))
                count += cursor.rowcount
        return count

    def review(self, eid, action, job_id='', status=''):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            event = db.execute('SELECT * FROM mail_events WHERE id=?', (eid,)).fetchone()
            if not event or event['status'] != 'pending':
                raise ValueError('This email suggestion was already reviewed or was not found')
            if action == 'dismiss':
                db.execute("UPDATE mail_events SET status='dismissed',reviewed_at=? WHERE id=?", (now(), eid))
                return {'ok': True}
            if action != 'accept' or status not in STAGES:
                raise ValueError('Choose a valid outcome to record')
            job = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job:
                raise ValueError('Choose the matching application')
            if job['status'] in ('in_progress', 'submitting', 'archived'):
                raise ValueError('Finish the running attempt or restore the archived job before applying this update')
            previous = job['status']
            if status == 'submitted' and job['submitted_at']:
                raise ValueError('This application is already recorded as submitted; dismiss the duplicate receipt')
            if previous in ('interview', 'offer', 'rejected'):
                allowed = {'interview': {'interview', 'offer', 'rejected'}, 'offer': {'offer', 'rejected'}, 'rejected': {'rejected'}}
                if status not in allowed[previous]:
                    raise ValueError('This would regress the application stage. Review it manually instead.')
            data = json.loads(event['payload'])
            confirmed_at = now()
            try:
                received = datetime.fromtimestamp(int(data['received_at'])/1000, timezone.utc)
                if received <= datetime.now(timezone.utc):
                    confirmed_at = received.isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                pass
            if not job['submitted_at']:
                db.execute('UPDATE jobs SET submitted_at=? WHERE id=?', (confirmed_at, job_id))
                self.store.event(db, job_id, 'submitted_manual', 'Confirmed from reviewed Gmail evidence; timestamp is email receipt time, not a verified submit-click time.')
            db.execute('UPDATE jobs SET status=?,updated_at=?,lease_until=NULL WHERE id=?', (status, now(), job_id))
            detail = 'Reviewed Gmail: ' + data['subject'] + ' | ' + data['url']
            self.store.event(db, job_id, status if status != 'submitted' else 'email_confirmation', detail)
            db.execute("UPDATE mail_events SET status='accepted',job_id=?,reviewed_at=? WHERE id=?", (job_id, now(), eid))
        return {'ok': True}

    def sync(self, gmail):
        if not self.lock.acquire(blocking=False):
            return False
        if not gmail.status()['connected']:
            self.lock.release()
            raise ValueError('Connect Gmail first')
        self.progress = {'running': True, 'message': 'Reading matching Gmail messages…', 'imported': 0}
        def run():
            try:
                from .gmail import DEFAULT_QUERY
                settings = self.store.setting('gmail_sync')
                count = self.ingest(gmail.status()['email'], gmail.messages(settings['query'] or DEFAULT_QUERY, limit=50))
                self.progress.update(imported=count, message=f'{count} new email updates ready for review')
            except Exception as exc:
                self.progress.update(message=str(exc)[:300])
            finally:
                settings = self.store.setting('gmail_sync')
                settings['last_run'] = now()
                self.store.set_setting('gmail_sync', settings)
                self.progress['running'] = False
                self.lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True
