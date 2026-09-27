"""Optional, user-triggered Firecrawl v2 discovery; never sends applicant data."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .sources import clean_url, NoRedirect, plain

FIELDS = ('title', 'company', 'location', 'description', 'posted_at')
SCHEMA = {
    'type': 'object',
    'properties': {key: {'type': ['string', 'null'], 'description': 'As shown in the job posting; null if absent.'} for key in FIELDS},
    'required': ['title', 'company', 'description'],
}


def request(endpoint, payload, api_key=''):
    if endpoint not in ('scrape', 'search'):
        raise ValueError('Unsupported Firecrawl operation')
    headers = {'Content-Type': 'application/json', 'User-Agent': 'JobPilot/2.0'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = Request('https://api.firecrawl.dev/v2/' + endpoint, data=json.dumps(payload).encode(), headers=headers)
    try:
        with build_opener(NoRedirect).open(req, timeout=55) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('Firecrawl returned too much content; paste this posting manually')
            result = json.loads(raw)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        messages = {401: 'Firecrawl requires a valid API key. Configure it in Automation.',
                    402: 'Your Firecrawl account has insufficient credits.',
                    403: 'Firecrawl could not access this resource. Open the posting and import it manually.',
                    429: 'Firecrawl rate limit reached. Wait before trying again or configure your API key.'}
        raise ValueError(messages.get(code, f'Firecrawl request failed (HTTP {code}). Try again later or import manually.')) from None
    except (URLError, TimeoutError):
        raise ValueError('Firecrawl could not be reached. Check your connection or import manually.') from None
    if not isinstance(result, dict) or result.get('success') is not True or not isinstance(result.get('data'), dict):
        raise ValueError('Firecrawl did not return usable data. Try another posting or import manually.')
    return result['data']


def extract(url, api_key='', transport=request):
    url = clean_url(url)
    result = transport('scrape', {
        'url': url, 'onlyMainContent': True, 'timeout': 45000,
        'formats': [{'type': 'json', 'schema': SCHEMA,
                     'prompt': 'Extract the single job posting on this page. Preserve job requirements faithfully. Do not infer missing facts or a publication date from an update date. Return null for missing fields.'}],
    }, api_key)
    data = result.get('json')
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) and data[k].strip() for k in ('title', 'company', 'description')):
        raise ValueError('No complete single-job posting was found. Paste the details manually.')
    job = {key: plain(data.get(key, ''))[:60000] if isinstance(data.get(key), str) else '' for key in FIELDS}
    # Keep the actual requested URL, never a model-invented apply destination.
    job.update(url=url, source='firecrawl')
    return job


def search(query, api_key='', transport=request):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 500:
        raise ValueError('Use a search query between 2 and 500 characters')
    data = transport('search', {'query': query.strip(), 'limit': 10, 'sources': ['web'], 'timeout': 45000}, api_key)
    rows = data.get('web', [])
    if not isinstance(rows, list):
        raise ValueError('Firecrawl returned an invalid search response')
    result = []
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        try:
            url = clean_url(row.get('url', ''))
        except ValueError:
            continue
        result.append({'url': url, 'title': str(row.get('title', 'Untitled'))[:500],
                       'description': str(row.get('description', ''))[:3000]})
    return result
