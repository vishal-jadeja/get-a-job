"""Tailoring selects and reorders user-authored evidence; never generates career claims."""
import hashlib
import html
import json
from .matching import tokens, contains
from .latex_resume import render_latex


def fingerprint(profile, job):
    # Submission approval covers exact profile and posting, including the uploaded file digest.
    value = {"profile": profile, "job": {k: job.get(k) for k in ("title", "company", "url", "description", "location")}}
    if job.get('resume_asset'):
        value['job']['resume_asset'] = job['resume_asset']
    if job.get('resume_variant_id'):
        value['job']['resume_variant_id'] = job['resume_variant_id']
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def prepare(profile, job):
    if not profile.get("name") or not profile.get("email"):
        raise ValueError("Add your name and email in Profile before preparing applications")
    if not profile.get("experience") and not profile.get("resume_text") and not profile.get("projects"):
        raise ValueError("Add your work evidence or résumé text before preparing applications")
    relevance = tokens(job.get("description", "") + " " + job["title"])
    evidence = sorted(profile.get("experience", []), key=lambda line: -len(tokens(line) & relevance))
    skills = sorted(profile.get("skills", []), key=lambda s: not contains(job.get("description", ""), s))
    contact = " · ".join(str(profile[k]) for k in ("email", "phone", "location", "linkedin", "website") if profile.get(k))
    parts = [profile["name"], contact]
    if profile.get("headline"):
        parts.append(profile["headline"])
    if skills:
        parts.append("SKILLS\n" + ", ".join(skills))
    if evidence:
        parts.append("SELECTED EXPERIENCE\n" + "\n".join("• " + item for item in evidence))
    if profile.get("resume_text"):
        parts.append(profile["resume_text"])
    for key, heading in (("projects", "PROJECTS"), ("education", "EDUCATION"),
                         ("certifications", "CERTIFICATIONS"), ("achievements", "ACHIEVEMENTS"), ("languages", "LANGUAGES")):
        if profile.get(key):
            values = profile[key]
            if key == "projects":
                values = sorted(values, key=lambda item: -len(tokens(item) & relevance))
            parts.append(heading + "\n" + "\n".join("• " + item for item in values))
    resume = "\n\n".join(parts)
    cover = f"Dear {job['company']} hiring team,\n\nI am applying for the {job['title']} role."
    if evidence:
        cover += " My relevant experience includes:\n\n" + "\n".join("• " + x for x in evidence[:3])
    cover += f"\n\nThank you for considering my application. I would welcome the opportunity to discuss my experience.\n\n{profile['name']}"
    esc = html.escape
    sections = "".join("<p>" + esc(p).replace("\n", "<br>") + "</p>" for p in parts[1:])
    printable = ("<!doctype html><html><head><meta charset='utf-8'><title>" + esc(profile["name"]) +
                 " — Resume</title><style>body{font:11pt/1.5 Arial,sans-serif;color:#182326;max-width:760px;margin:44px auto;padding:0 32px}h1{font-size:25pt}p{white-space:normal} @page{size:A4;margin:18mm}@media print{body{margin:0;padding:0}}</style></head><body><h1>" +
                 esc(profile["name"]) + "</h1>" + sections + "</body></html>")
    return {"resume": resume, "resume_html": printable, "resume_latex": render_latex(resume), "cover_letter": cover, "evidence": evidence,
            "fingerprint": fingerprint(profile, job), "note": "All career statements come verbatim from your profile. The browser helper uploads your original résumé file."}
