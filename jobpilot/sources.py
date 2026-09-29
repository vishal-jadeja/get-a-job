"""Read-only connectors to documented public ATS feeds. No employer keys needed."""
import html
import json
import re
import ssl
import sys
import time
from pathlib import Path
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

MAX_RESPONSE = 16 * 1024 * 1024
KINDS = {"greenhouse", "lever", "lever_eu", "ashby", "yc"}


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "li", "div", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    p = TextParser()
    p.feed(html.unescape(str(value or "")))
    return re.sub(r"\n\s*\n", "\n\n", "".join(p.parts)).strip()


def clean_url(value):
    u = urlsplit(str(value).strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError("Job links must be public HTTPS URLs without credentials or custom ports")
    host = u.hostname.lower()
    import ipaddress
    try:
        ipaddress.ip_address(host)
        raise ValueError("IP addresses are not job sites")
    except ValueError as exc:
        if str(exc) == "IP addresses are not job sites":
            raise
    if "." not in host or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local job URLs are not allowed")
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref", "referrer", "gh_src"}]
    return urlunsplit(("https", host, u.path.rstrip("/"), urlencode(sorted(query)), ""))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Unexpected upstream redirect; update the board configuration")


def tls_context():
    """Use verified HTTPS, including the OS CA fallback for python.org on macOS."""
    context = ssl.create_default_context()
    # python.org's macOS installer may lack its optional certifi bundle. Use the
    # OS-provided CA bundle when that happens; certificate checks remain enabled.
    if sys.platform == "darwin" and not ssl.get_default_verify_paths().cafile and Path("/etc/ssl/cert.pem").exists():
        context.load_verify_locations(cafile="/etc/ssl/cert.pem")
    return context


def fetch_json(url):
    context = tls_context()
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "JobPilot/1.0 (personal job discovery)", "Accept": "application/json"})
            with build_opener(NoRedirect, HTTPSHandler(context=context)).open(req, timeout=25) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise ValueError("Job feed exceeded 16 MB")
                return json.loads(raw)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(min(4, 2 ** attempt))


def validate_source(source):
    if source.get("kind") not in KINDS:
        raise ValueError("Choose Greenhouse, Lever, Lever EU, Ashby, or YC")
    if source.get('kind') == 'yc' and source.get('board') != 'engineering':
        raise ValueError('The YC source uses the engineering board')
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", source.get("board", "")):
        raise ValueError("Board name must be a slug, such as stripe; not a URL")
    return {"kind": source["kind"], "board": source["board"],
            "company": str(source.get("company") or source["board"])[:150], "enabled": bool(source.get("enabled", True))}


def normalize(kind, board, company, data):
    jobs = []
    records = data if kind.startswith("lever") else data.get("jobs", [])
    for row in records:
        if kind == "greenhouse":
            job = {"external_id": str(row["id"]), "title": row["title"], "company": company,
                   "location": row.get("location", {}).get("name", ""), "url": row["absolute_url"],
                   "description": plain(row.get("content")), "posted_at": ""}
            # updated_at is not a publication date: do not pretend old roles are fresh.
        elif kind.startswith("lever"):
            body = [row.get("descriptionPlain") or plain(row.get("description"))]
            body += [plain(x.get("text", "")) + "\n" + plain(x.get("content", "")) for x in row.get("lists", [])]
            body.append(row.get("additionalPlain") or plain(row.get("additional")))
            job = {"external_id": str(row["id"]), "title": row["text"], "company": company,
                   "location": row.get("categories", {}).get("location", ""),
                   "url": row.get("applyUrl") or row["hostedUrl"], "description": "\n\n".join(body),
                   "remote": row.get("workplaceType") == "remote", "posted_at": ""}
        else:
            if row.get("isListed") is False:
                continue
            job = {"external_id": str(row["id"]), "title": row["title"], "company": company,
                   "location": row.get("location", ""), "url": row.get("applyUrl") or row["jobUrl"],
                   "description": row.get("descriptionPlain") or plain(row.get("descriptionHtml")),
                   "remote": row.get("isRemote", False), "posted_at": row.get("publishedAt", "")}
        job.update(source=kind, board=board)
        job["url"] = clean_url(job["url"])
        jobs.append(job)
    return jobs


def discover(source, fetch=fetch_json):
    s = validate_source(source)
    kind, board = s["kind"], s["board"]
    if kind == 'yc':
        from .yc import discover as discover_yc
        return discover_yc()['jobs']
    if kind == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    elif kind == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    else:
        domain = "api.eu.lever.co" if kind == "lever_eu" else "api.lever.co"
        jobs = []
        for skip in range(0, 10000, 100):
            rows = fetch(f"https://{domain}/v0/postings/{board}?mode=json&limit=100&skip={skip}")
            jobs.extend(normalize(kind, board, s["company"], rows))
            if len(rows) < 100:
                return jobs
        raise ValueError("Board exceeds pagination limit; narrow the source")
    return normalize(kind, board, s["company"], fetch(url))
