"""Transparent heuristics, not a prediction of hiring probability."""
import re
from datetime import datetime, timezone


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
    matched = [s for s in skills if contains(text, s)]
    from .roles import ROLE_SKILLS
    vocabulary = sorted(set(s for group in ROLE_SKILLS.values() for s in group) | set(s.lower() for s in skills))
    mentioned = [s for s in vocabulary if contains(text, s)]
    evidence_text = "\n".join(skills + profile.get("experience", []) + profile.get("projects", []) + [profile.get("resume_text", "")])
    covered = [s for s in mentioned if contains(evidence_text, s)]
    qualification = round(100 * len(covered) / len(mentioned)) if mentioned else None
    if not roles or not skills:
        warnings.append("Add target roles and skills to get a useful match score.")
    role_score = max((len(tokens(r) & tokens(title)) / max(1, len(tokens(r))) for r in roles), default=0)
    score = round(45 * role_score + 40 * len(covered) / max(1, len(mentioned)))
    reasons.append(f"Title overlap: {round(100 * role_score)}%")
    reasons.append(f"Evidence for {len(covered)} of {len(mentioned)} recognized skills in this posting")
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
        if any(contains(location, loc) for loc in locations):
            score += 10
            reasons.append("Advertised location matches a preference")
        else:
            blockers.append("Advertised location does not match your location filters")
    elif location:
        warnings.append("Location eligibility has not been checked; set preferred locations.")
    if "remote" in location.lower() or job.get("remote"):
        warnings.append("Remote roles may restrict countries or time zones; check the posting.")
    years = profile.get("years_experience")
    required_years = [int(n) for n in re.findall(r"\b(\d{1,2})\+?\s+years?\s+(?:of\s+)?(?:relevant\s+|professional\s+)?experience", body, re.I)]
    if years is not None and required_years and max(required_years) > years:
        warnings.append(f"Posting mentions {max(required_years)} years of experience; profile has {years}.")
        score = max(0, score - 10)
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
    return {"score": min(score, 100), "eligible": not blockers, "reasons": reasons,
            "blockers": blockers, "warnings": warnings, "matched_skills": matched,
            "qualification_percent": qualification, "covered_skills": covered,
            "missing_skills": [s for s in mentioned if s not in covered],
            "unmentioned_skills": [s for s in skills if s not in matched]}
