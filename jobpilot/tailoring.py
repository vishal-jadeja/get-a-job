"""Role-focused résumés from applicant-authored evidence, ranked for each posting."""
from .matching import tokens, contains
from .materials import prepare, fingerprint


def choose_variant(job, variants):
    choice = job.get('resume_variant_id', '')
    if choice == 'general':
        return None
    if choice:
        variant = next((v for v in variants if v['id'] == choice), None)
        if not variant:
            raise ValueError('Selected résumé profile no longer exists')
        return variant
    title = tokens(job['title'])
    ranked = []
    for variant in variants:
        scores = []
        for role in variant['target_roles'].split(','):
            words = tokens(role)
            if words:
                scores.append(len(words & title) / len(words))
        score = max(scores, default=0)
        if score >= 0.6:
            ranked.append((score, variant))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def prepare_for_job(profile, job, variants):
    variant = choose_variant(job, variants)
    effective = dict(profile)
    relevance = tokens(job.get('description', '') + ' ' + job['title'])
    for key in ('skills', 'experience', 'projects'):
        chosen = variant.get(key, []) if variant else []
        if any(item not in profile.get(key, []) for item in chosen):
            raise ValueError('Résumé profile references changed career evidence. Edit that résumé profile before preparing.')
        values = chosen or profile.get(key, [])
        if key == 'skills':
            values = sorted(values, key=lambda item: not contains(job.get('description', ''), item))
        else:
            values = sorted(values, key=lambda item: -len(tokens(item) & relevance))
        limit = (variant or {}).get({'skills': 'max_skills', 'experience': 'max_experience', 'projects': 'max_projects'}[key], {'skills':20,'experience':8,'projects':4}[key])
        effective[key] = values[:limit]
    if variant:
        effective['headline'] = variant['headline'] or profile.get('headline', '')
    materials = prepare(effective, job)
    # Approval covers the authoritative profile and posting, not the derived subset.
    materials['fingerprint'] = fingerprint(profile, job)
    materials['tailoring'] = {
        'variant_id': variant['id'] if variant else None,
        'variant_name': variant['name'] if variant else 'General career profile',
        'target_role': job['title'],
        'skills': effective['skills'],
        'experience_count': len(effective['experience']),
        'project_count': len(effective['projects']),
    }
    materials['note'] = 'Tailored from your saved facts for this posting. Review the résumé draft and choose the attachment you want the helper to upload.'
    return materials
