"""Free discovery from YC's public server-rendered engineering listings.

No authenticated directory, hidden APIs, or LinkedIn requests are used.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler
from .sources import NoRedirect, clean_url, tls_context, plain

BASE = 'https://www.ycombinator.com'
ENGINEERING = BASE + '/jobs/role/software-engineer'


def public_url(value):
    url = clean_url(urljoin(BASE, value))
    parts = urlsplit(url)
    if parts.hostname != 'www.ycombinator.com' or not (
        parts.path.startswith('/jobs/role/software-engineer') or
        re.fullmatch(r'/companies/[a-zA-Z0-9_-]+(?:/jobs/[a-zA-Z0-9_-]+)?', parts.path)
    ):
        raise ValueError('Use an official public YC company or engineering-job URL')
    return url


def fetch_page(url):
    url = public_url(url)
    req = Request(url, headers={'User-Agent': 'JobPilot/2.0 (personal job discovery)', 'Accept': 'text/html'})
    with build_opener(NoRedirect, HTTPSHandler(context=tls_context())).open(req, timeout=25) as response:
        raw = response.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError('YC page exceeded the 5 MB response limit')
    return raw.decode('utf-8')


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.props = None

    def handle_starttag(self, tag, attrs):
        value = dict(attrs).get('data-page')
        if value:
            data = json.loads(value)
            if isinstance(data, dict) and isinstance(data.get('props'), dict):
                self.props = data['props']


def page_props(html):
    parser = Page()
    parser.feed(html)
    if parser.props is None:
        raise ValueError('YC public page format changed or is unavailable; open the source manually')
    return parser.props


def normalize(row):
    if not isinstance(row, dict) or row.get('role') != 'eng' or not row.get('companyBatchName'):
        return None
    url = public_url(row.get('url', ''))
    if '/jobs/' not in urlsplit(url).path or '/companies/' not in urlsplit(url).path:
        return None
    full = str(row.get('description') or '').strip()
    summary = '\n'.join(filter(None, [str(row.get('companyOneLiner') or ''),
        'Specialty: ' + str(row.get('roleSpecificType') or 'Engineering'),
        'Listed skills: ' + ', '.join(str(s) for s in row.get('skills', [])),
        'Experience: ' + str(row.get('minExperience') or 'Not specified'),
        'Visa: ' + str(row.get('visa') or 'Check original posting'),
        'Compensation: ' + str(row.get('salaryRange') or 'Not listed')]))
    return {'title': str(row['title']), 'company': str(row['companyName']), 'url': url,
            'location': str(row.get('location') or ''), 'description': full or summary,
            'source': 'yc', 'board': 'engineering', 'external_id': str(row['id']),
            'posted_at': '', 'yc_batch': str(row.get('companyBatchName') or ''),
            'company_url': public_url(row.get('companyUrl') or url.split('/jobs/')[0]),
            'yc_activity': str(row.get('lastActive') or ''),
            'description_partial': not bool(full)}


def discover(fetch=fetch_page):
    props = page_props(fetch(ENGINEERING))
    if not isinstance(props.get('jobPostings'), list):
        raise ValueError('YC public engineering listings were not found')
    urls = [ENGINEERING]
    for item in props.get('sidebarLinks', []):
        if isinstance(item, list) and len(item) == 2:
            try:
                url = public_url(item[1])
                if url.startswith(ENGINEERING + '/') and url not in urls:
                    urls.append(url)
            except ValueError:
                pass
    jobs, errors, pages = {}, [], 0
    for url in urls[:12]:
        try:
            data = props if url == ENGINEERING else page_props(fetch(url))
            rows = data.get('jobPostings')
            if not isinstance(rows, list):
                raise ValueError('Public listings not present')
            for row in rows:
                try:
                    job = normalize(row)
                    if job:
                        jobs[job['external_id']] = job
                except (ValueError, KeyError, TypeError):
                    continue
            pages += 1
        except Exception as exc:
            errors.append(f'{url}: {str(exc)[:150]}')
    return {'jobs': list(jobs.values()), 'pages': pages, 'errors': errors,
            'coverage': 'Public YC engineering listing pages and their linked locations. Not the entire signed-in directory.'}


def detail(url, fetch=fetch_page):
    url = public_url(url)
    props = page_props(fetch(url))
    row = props.get('job')
    if not isinstance(row, dict) or not row.get('description'):
        raise ValueError('This YC job no longer exposes a complete description; check the source')
    job = normalize(row)
    if not job or job['url'] != url:
        raise ValueError('YC returned a different job or a non-engineering posting')
    company = props.get('company') or {}
    # Only extract public professional fields used by the networking feature.
    people = []
    for founder in company.get('founders', []):
        if founder.get('is_active') and founder.get('full_name') and founder.get('linkedin_url'):
            people.append({'name': founder['full_name'], 'role': founder.get('title') or 'Founder',
                           'url': founder['linkedin_url'], 'kind': 'founder',
                           'evidence': 'Listed as an active founder on the company’s public YC page.',
                           'source_url': url, 'verification': 'yc_public_page'})
    return job, {'name': job['company'], 'url': company.get('linkedin_url') or '',
                 'summary': plain(company.get('one_liner') or ''), 'source_url': url}, people


def trend(job):
    """A transparent prioritization hint, never a claim of startup popularity."""
    batch = re.fullmatch(r'([A-Z])(\d{2})', job.get('yc_batch', ''))
    batch_order = (2000 + int(batch[2])) * 10 + {'W': 1, 'P': 2, 'S': 3, 'F': 4}.get(batch[1], 0) if batch else 0
    match = re.fullmatch(r'(?:about\s+)?(\d+)\s+(minute|hour|day|week|month|year)s?(?:\s+ago)?', job.get('yc_activity', '').strip(), re.I)
    days = int(match[1]) * {'minute': 1/1440, 'hour': 1/24, 'day': 1, 'week': 7, 'month': 30, 'year': 365}[match[2].lower()] if match else 9999
    return (-batch_order, days, job.get('company', '').lower())
