"""Transparent heuristics, not a prediction of hiring probability."""
import re
from datetime import datetime, timezone
from .skills import extract_skills, canonical, has_skill
from .requirements import analyze, title_words, location_match


def contains(text, phrase):
    return bool(re.search(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)", text, re.I)) if phrase.strip() else False


def tokens(text):
    return set(re.findall(r"[\w+#.]+", text.lower())) - {"and", "the", "a", "of", "in", "to", "with", "for"}


def match(job, profile):
    title, body = job["title"], job.get("description", "")
    text = title + " " + body
    reasons, blockers, warnings = [], [], []
    roles = profile.get("roles", [])
    skills = profile.get("skills", [])
    matched = [s for s in skills if has_skill(text, s)]
    mentioned = extract_skills(text, skills)
    evidence_text = "\n".join(skills + profile.get("experience", []) + profile.get("projects", []) + [profile.get("resume_text", "")])
    explicit = {canonical(s) for s in skills}
    covered = [s for s in mentioned if s in explicit or has_skill(evidence_text, s)]
    requirements = analyze(job, profile)
    qualification = round(100 * len(covered) / len(mentioned)) if mentioned else None
    if not roles or not skills:
        warnings.append("Add target roles and skills to get a useful match score.")
    role_score = max((len(title_words(r) & title_words(title)) / max(1, len(title_words(r))) for r in roles), default=0)
    score = round(45 * role_score + 40 * requirements['weighted_coverage'])
    reasons.append(f"Title overlap: {round(100 * role_score)}%")
    reasons.append(f"Evidence for {len(covered)} of {len(mentioned)} recognized skills in this posting")
    reasons.append(f"Weighted requirement coverage: {round(requirements['weighted_coverage']*100)}% (required 3×, general 2×, preferred 1×)")
    warnings.extend(requirements['warnings'])
    for company in profile.get("excluded_companies", []):
        if contains(job["company"], company):
            blockers.append("Excluded company: " + company)
    for phrase in profile.get("excluded_keywords", []):
        if contains(text, phrase):
            blockers.append("Excluded phrase: " + phrase)
    for phrase in profile.get("required_keywords", []):
        if not contains(text, phrase):
            blockers.append("Required phrase missing: " + phrase)
    locations = profile.get("locations", [])
    location = job.get("location", "")
    if locations:
        # Remote does not imply worldwide eligibility. Only match the advertised location.
        if any(location_match(location, loc) for loc in locations):
            score += 10
            reasons.append("Advertised location matches a preference")
        else:
            blockers.append("Advertised location does not match your location filters")
    elif location:
        warnings.append("Location eligibility has not been checked; set preferred locations.")
    if "remote" in location.lower() or job.get("remote"):
        warnings.append("Remote roles may restrict countries or time zones; check the posting.")
    years = profile.get("years_experience")
    required_years = requirements['required_years']
    if years is not None and required_years is not None and required_years > years:
        warnings.append(f"Posting mentions {required_years} years of experience; profile has {years}.")
        score = max(0, score - 10)
    for check in requirements['eligibility_checks']:
        if check['status'] == 'gap':
            warnings.append(check['detail'])
            if check['label'] == 'Sponsorship':
                blockers.append('You need sponsorship, but the posting explicitly says it is unavailable')
    posted = job.get("posted_at", "")
    if posted:
        try:
            dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - dt.replace(tzinfo=dt.tzinfo or timezone.utc)).days
            if 0 <= age <= 7:
                score += 5
                reasons.append("Published within the last seven days")
            if age > profile.get("max_age_days", 45):
                blockers.append(f"Posting is {age} days old")
        except ValueError:
            warnings.append("Publication date could not be verified")
    else:
        warnings.append("Publication date unavailable")
    if not body.strip():
        warnings.append("No job description available")
    if job.get('description_partial'):
        blockers.append('Load the complete YC posting before assessing fit or preparing an application')
        qualification = None
        warnings.append('Only listing-summary skills are available; the match score is provisional')
    return {"score": min(score, 100), "eligible": not blockers, "reasons": reasons,
            "blockers": blockers, "warnings": warnings, "matched_skills": matched,
            "qualification_percent": qualification, "covered_skills": covered,
            "requirements": requirements['groups'], "eligibility_checks": requirements['eligibility_checks'],
            "missing_skills": [s for s in mentioned if s not in covered],
            "unmentioned_skills": [s for s in skills if s not in matched]}
