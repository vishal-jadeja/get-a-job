"""Explainable requirement tiers and explicit eligibility checks."""
import re
from .skills import canonical, extract_skills, has_skill

REQUIRED = re.compile(r'\b(required|requirements|must|minimum|essential|need to have)\b', re.I)
PREFERRED = re.compile(r'\b(preferred|nice.to.have|bonus|optional|useful|desirable|a plus)\b', re.I)
COUNTRIES = {'us': ['united states', 'usa', 'u.s.', 'us'], 'uk': ['united kingdom', 'uk', 'u.k.'],
             'india': ['india', 'in'], 'canada': ['canada', 'ca'], 'germany': ['germany', 'de'],
             'australia': ['australia', 'au'], 'singapore': ['singapore', 'sg']}


def title_words(text):
    text = text.lower().replace('full-stack', 'full stack').replace('fullstack', 'full stack')
    text = re.sub(r'\b(front.end|front end)\b', 'frontend', text)
    text = re.sub(r'\b(back.end|back end)\b', 'backend', text)
    text = re.sub(r'\b(developer|development|swe|sde)\b', 'engineer', text)
    return set(re.findall(r'[a-z0-9+#]+', text)) - {'and', 'the', 'of', 'in', 'for', 'with'}


def location_match(location, preference):
    def words(text):
        return set(re.findall(r'[a-z]+', text.casefold()))
    a, b = words(location), words(preference)
    if b and b.issubset(a):
        return True
    for code, names in COUNTRIES.items():
        matches = any((set(re.findall(r'[a-z]+', n)).issubset(a) if len(n) > 3 else
                       bool(re.search(r'(?<!\w)' + re.escape(n.upper()) + r'(?!\w)', location))) for n in names)
        if preference.casefold() in names and matches:
            # CA can mean California; only use country-code aliases at a delimiter/end.
            if code == 'canada' and a & {'ca'} and not ('canada' in a):
                return False
            return True
    return False


def analyze(job, profile):
    text = job.get('description', '')
    explicit = {canonical(s) for s in profile.get('skills', []) + profile.get('technologies', [])}
    evidence = '\n'.join(profile.get('experience', []) + profile.get('projects', []) + [profile.get('resume_text', '')])
    groups, years, section = [], [], 'mentioned'
    for line in text.splitlines():
        cleaned = re.sub(r'^[#*\-\s]+|[:\s]+$', '', line).strip()
        if len(cleaned) < 90 and (REQUIRED.search(cleaned) or PREFERRED.search(cleaned)) and not extract_skills(cleaned):
            section = 'preferred' if PREFERRED.search(cleaned) else 'required'
        elif len(cleaned) < 50 and re.search(r'^(responsibilities|benefits|about us|what we offer|the company)', cleaned, re.I):
            section = 'mentioned'
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])|;', cleaned):
            kind = 'preferred' if PREFERRED.search(sentence) else 'required' if REQUIRED.search(sentence) else section
            skills = extract_skills(sentence, profile.get('skills', []))
            # Treat a clear alternatives list as one requirement. Mixed AND/OR is
            # retained as separate mentions for the user to inspect.
            alternative = len(skills) > 1 and re.search(r'\bor\b', sentence, re.I) and not re.search(r'\band\b', sentence, re.I)
            for values in ([skills] if alternative else [[s] for s in skills]):
                covered = [s for s in values if s in explicit or has_skill(evidence, s)]
                groups.append({'skills': values, 'kind': kind, 'operator': 'any' if alternative else 'all',
                               'covered': covered, 'met': bool(covered), 'evidence': sentence[:500]})
            experience = re.search(r'\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\+?\s+years?\s+(?:of\s+)?(?:[\w/-]+\s+){0,4}experience\b', sentence, re.I)
            if experience:
                years.append({'years': int(experience[1]), 'kind': kind, 'evidence': sentence[:500]})
    # Repeated boilerplate must not multiply a requirement's weight.
    unique = {}
    rank = {'required': 3, 'mentioned': 2, 'preferred': 1}
    for group in groups:
        key = tuple(group['skills'])
        if key not in unique or rank[group['kind']] > rank[unique[key]['kind']]:
            unique[key] = group
    groups = list(unique.values())
    total = sum(rank[g['kind']] for g in groups)
    weighted = sum(rank[g['kind']] for g in groups if g['met']) / total if total else 0
    missing_required = [g for g in groups if g['kind'] == 'required' and not g['met']]
    required_years = max((x['years'] for x in years if x['kind'] != 'preferred'), default=None)
    checks, warnings = [], []
    if required_years is not None:
        actual = profile.get('years_experience')
        checks.append({'label': 'Experience', 'status': 'unknown' if actual is None else 'met' if actual >= required_years else 'gap',
                       'detail': f'Posting mentions at least {required_years} years; profile: {actual if actual is not None else "not specified"}. Review whether this is total or skill-specific experience.'})
    if re.search(r'\b(senior|staff|principal|lead|head|director)\b', job['title'], re.I):
        checks.append({'label': 'Seniority', 'status': 'review', 'detail': 'Senior/leadership title: review scope and responsibilities, not just years.'})
    if re.search(r'\b(?:no (?:visa )?sponsorship|(?:cannot|unable to|do not|does not) (?:provide |offer )?(?:visa )?sponsor(?:ship)?)\b', text, re.I):
        need = profile.get('needs_sponsorship', 'unknown')
        checks.append({'label': 'Sponsorship', 'status': 'gap' if need == 'yes' else 'met' if need == 'no' else 'unknown',
                       'detail': 'Posting says sponsorship is unavailable. Match this to your situation and the job country.'})
    if re.search(r'\b(?:authorized|authorised|authorization|authorisation|right to work|citizen|citizenship)\b', text, re.I):
        checks.append({'label': 'Work authorization', 'status': 'review', 'detail': 'Posting contains authorization/citizenship conditions. Verify the country and requirements; no legal eligibility is inferred.'})
    if re.search(r'\b(?:bachelor|master|ph\.?d|degree)\b', text, re.I):
        checks.append({'label': 'Education', 'status': 'review', 'detail': 'Education is mentioned. Check level, subject, and whether equivalent experience is accepted.'})
    if missing_required:
        warnings.append('Required skill evidence missing: ' + '; '.join(' or '.join(g['skills']) for g in missing_required))
    return {'groups': groups, 'weighted_coverage': weighted, 'missing_required': missing_required,
            'experience_requirements': years, 'required_years': required_years, 'eligibility_checks': checks, 'warnings': warnings}
