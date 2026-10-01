"""Conservative engineering discovery based on the saved career profile."""
import re
from .matching import match
from .requirements import title_words


def relevant_engineering(job, profile):
    title = job.get('title', '')
    words = title_words(title)
    # Shared generic words such as 'engineer' must not admit sales/hardware roles.
    if re.search(r'\b(sales|recruit\w*|marketing|account executive|customer success|support|mechanical|electrical|hardware|civil|manufacturing)\b', title, re.I):
        return False
    if not (words & {'engineer', 'programmer'} or re.search(r'\b(swe|sde)\b', title, re.I)):
        return False
    families = {'software', 'backend', 'frontend', 'full', 'stack', 'ai', 'ml', 'machine', 'learning', 'devops', 'platform', 'infrastructure', 'reliability', 'deployed'}
    targets = set().union(*(title_words(role) for role in profile.get('roles', [])))
    if not words & targets & families:
        return False
    years = profile.get('years_experience')
    if years is not None:
        if years < 5 and re.search(r'\b(senior|sr\.?|staff|principal|lead|manager|director|head|vp)\b', title, re.I):
            return False
    # YC summaries remain provisional until a full description is loaded.
    fit = match({**job, 'description_partial': False}, profile)
    if any(check['label'] == 'Experience' and check['status'] == 'gap' for check in fit['eligibility_checks']):
        return False
    return fit['eligible'] and fit['score'] >= profile.get('min_score', 45) and (
        bool(job.get('description_partial')) or bool(fit['covered_skills']))
