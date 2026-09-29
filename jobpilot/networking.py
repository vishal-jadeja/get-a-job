"""Public professional contact candidates and evidence-grounded outreach drafts."""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit, quote
from . import firecrawl, yc
from .matching import contains, tokens
from .sources import clean_url
from .store import now


def linkedin_url(value, kind):
    url = clean_url(value)
    p = urlsplit(url)
    if not (p.hostname == 'linkedin.com' or p.hostname.endswith('.linkedin.com')):
        raise ValueError('Not a LinkedIn URL')
    pattern = r'/company/[^/]+' if kind == 'company' else r'/in/[^/]+'
    if not re.fullmatch(pattern + r'/?', p.path):
        raise ValueError('Not a public company/profile URL')
    return urlunsplit(('https', 'www.linkedin.com', p.path.rstrip('/'), '', ''))


def context_key(job):
    # Company names alone can collide. ATS/company identity separates employers.
    company_identity = job.get('company_url') or (job.get('source', '') + ':' + job.get('board', ''))
    text = job['company'].strip().lower() + '|' + company_identity + '|' + job['title'].strip().lower()
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def search_links(job):
    company = re.sub(r'["\r\n]', ' ', job['company'])[:120]
    role = re.sub(r'["\r\n]', ' ', job['title'])[:120]
    queries = {'company': f'site:linkedin.com/company/ "{company}"',
               'peers': f'site:linkedin.com/in/ "{company}" "{role}"',
               'recruiters': f'site:linkedin.com/in/ "{company}" (recruiter OR "talent acquisition" OR "human resources")'}
    return {k: {'query': q, 'url': 'https://www.google.com/search?q=' + quote(q)} for k, q in queries.items()}


def candidate(row, job, kind):
    try:
        url = linkedin_url(row.get('url', ''), 'company' if kind == 'company' else 'person')
    except (ValueError, TypeError):
        return None
    title = str(row.get('title') or '')[:500]
    evidence = str(row.get('description') or '')[:1600]
    # Search ranking alone is not evidence of a current company association.
    if not contains(title + ' ' + evidence, job['company']):
        return None
    if kind == 'company':
        return {'name': title.replace('| LinkedIn', '').strip(), 'url': url, 'evidence': evidence,
                'source_url': url, 'verification': 'public_search_result'}
    parts = re.split(r'\s+[|–—-]\s+', title.replace(' | LinkedIn', ''))
    name = parts[0].strip()
    if len(parts) < 2 or not 2 <= len(name.split()) <= 6 or len(name) > 100 or re.search(r'linkedin|profiles|jobs|people', name, re.I):
        return None
    role = ' — '.join(parts[1:])[:250]
    if kind == 'recruiter':
        relevant = re.search(r'\b(recruit\w*|talent|human resources|hr|people operations)\b', role + ' ' + evidence, re.I)
    else:
        relevant = (tokens(job['title']) - {'senior', 'junior', 'staff', 'lead', 'principal'}) & tokens(role + ' ' + evidence)
    if not relevant:
        return None
    return {'name': name, 'role': role, 'url': url, 'kind': kind, 'evidence': evidence or title,
            'source_url': url, 'verification': 'public_search_result'}


def short(text, limit):
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= limit:
        return text
    return text[:limit-1].rsplit(' ', 1)[0] + '…'


def drafts(profile, job, person=None):
    person = person or {}
    name = short(person.get('name', '').split(' ')[0] or 'there', 24)
    text = job['title'] + ' ' + job.get('description', '')
    skills = [s for s in profile.get('skills', []) if contains(text, s)]
    evidence = profile.get('experience', []) + profile.get('projects', [])
    ranked = sorted(evidence, key=lambda x: -len(tokens(x) & tokens(text)))
    selected = next((x for x in ranked if tokens(x) & tokens(text)), '')
    role, company = short(job['title'], 55), short(job['company'], 40)
    fit = ' My background includes ' + short(', '.join(skills[:3]), 55) + '.' if skills else ''
    connection = f'Hi {name}, I’m interested in the {role} role at {company}.{fit} Open to connecting about the team?'
    if len(connection) > 300:
        connection = f'Hi {name}, I’m interested in {short(role, 40)} at {short(company, 25)}.{fit} Open to connecting?'
    ask = 'Could you share the best way to reach the hiring team?' if person.get('kind') == 'recruiter' else 'Would you be open to sharing what the team values in this role?'
    message = f'Hi {name}, I’m interested in the {role} opening at {company}.{fit}'
    if selected:
        message += f' Relevant experience from my profile: “{short(selected, 220)}”'
    message += ' ' + ask
    return {'connection': connection, 'message': message, 'job_url': job['url'], 'skills': skills[:3],
            'evidence': selected, 'warning': '' if skills or selected else 'Add relevant career evidence before describing your fit.',
            'note': 'Draft only. Verify the person’s current employer and edit before sending. No messages are sent by JobPilot.'}


class Networking:
    def __init__(self, store, key_provider=lambda: '', search=firecrawl.search):
        self.store, self.key_provider, self.search = store, key_provider, search
        self.lock = threading.Lock()
        self.progress = {'running': False, 'message': 'Ready', 'completed': 0}
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS networking_cache(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL,checked_at TEXT NOT NULL)')
        if store.setting('networking') is None:
            store.set_setting('networking', {'automatic': True, 'max_per_run': 5})

    def cached(self, job):
        with self.store.db() as db:
            row = db.execute('SELECT payload,checked_at FROM networking_cache WHERE cache_key=?', (context_key(job),)).fetchone()
        if not row:
            return None
        data = json.loads(row['payload'])
        ttl = timedelta(hours=1) if data.get('status') == 'error' else timedelta(days=7)
        data['stale'] = datetime.now(timezone.utc) - datetime.fromisoformat(row['checked_at']) > ttl
        return data

    def view(self, job):
        return {**(self.cached(job) or {'status': 'not_researched', 'companies': [], 'people': [], 'errors': [], 'checked_at': None}),
                'search_links': search_links(job), 'drafts': drafts(self.store.setting('profile'), job)}

    def lookup(self, job):
        result = {'status': 'ready', 'companies': [], 'people': [], 'errors': [], 'checked_at': now()}
        if job.get('source') == 'yc':
            try:
                complete, company, founders = yc.detail(job['url'])
                self.store.upsert_jobs([complete])
                if company['url']:
                    company['url'] = linkedin_url(company['url'], 'company')
                    company['verification'] = 'yc_public_page'
                    result['companies'].append(company)
                for person in founders:
                    try:
                        person['url'] = linkedin_url(person['url'], 'person')
                        result['people'].append(person)
                    except ValueError:
                        pass
            except Exception as exc:
                result['errors'].append('YC details: ' + str(exc)[:180])
        for kind, query in search_links(job).items():
            try:
                rows = self.search(query['query'], self.key_provider())
                category = {'peers': 'peer', 'recruiters': 'recruiter'}.get(kind, kind)
                target = result['companies'] if kind == 'company' else result['people']
                count = 0
                for row in rows:
                    item = candidate(row, job, category)
                    if item and item['url'] not in {x['url'] for x in target}:
                        target.append(item)
                        count += 1
                        if count >= (2 if kind == 'company' else 3):
                            break
            except Exception as exc:
                result['errors'].append('Public search: ' + str(exc)[:220])
                break  # Do not repeatedly consume a rejected/rate-limited service.
        result['people'] = sorted(result['people'], key=lambda p: {'recruiter': 0, 'peer': 1, 'founder': 2}[p['kind']])[:8]
        if result['errors']:
            result['status'] = 'partial' if result['people'] or result['companies'] else 'error'
            previous = self.cached(job)
            if previous and not result['people'] and not result['companies'] and (previous.get('people') or previous.get('companies')):
                result.update(people=previous['people'], companies=previous['companies'], status='partial', previous_results_at=previous['checked_at'])
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO networking_cache VALUES(?,?,?)', (context_key(job), json.dumps(result), result['checked_at']))
            self.store.event(db, job.get('id'), 'networking', f"{len(result['people'])} public contact candidates; {result['status']}")
        return result

    def start(self, jobs, force=False, limit=None):
        if not self.lock.acquire(blocking=False):
            return False
        config = self.store.setting('networking')
        chosen, seen = [], set()
        for job in jobs:
            key = context_key(job)
            cached = self.cached(job)
            if key in seen or (not force and cached and not cached['stale']):
                continue
            seen.add(key)
            chosen.append(job)
            if len(chosen) >= (limit or config['max_per_run']):
                break
        if not chosen:
            self.lock.release()
            return False
        self.progress = {'running': True, 'message': 'Finding public professional contacts…', 'completed': 0}
        def run():
            try:
                for i, job in enumerate(chosen):
                    self.progress.update(message='Researching ' + job['company'])
                    result = self.lookup(job)
                    self.progress.update(completed=i+1)
                    if any(x.startswith('Public search:') for x in result['errors']):
                        self.progress.update(message=result['errors'][-1])
                        return
                self.progress.update(message=f'Networking research complete for {len(chosen)} company/role groups')
            except Exception as exc:
                self.progress.update(message='Networking research failed: ' + str(exc)[:200])
            finally:
                self.progress['running'] = False
                self.lock.release()
        threading.Thread(target=run, daemon=True).start()
        return True
