# JobPilot

A free, local job-search workspace: **career profile → suggested roles → matching jobs → tailored materials → your approval → browser-assisted applications → outcome analytics**.

The core app uses Python's standard library, SQLite, and plain JavaScript. No subscription, paid API, cloud database, Docker, or LLM is required. There is no tracking or external font dependency.

## Run

Requires Python **3.10+**. From this folder:

```sh
python3 -m jobpilot
```

Open **http://127.0.0.1:8765**. Another port or data directory:

```sh
python3 -m jobpilot --port 8766 --data /path/to/private-data
```

Keep the server running for scheduled discovery. Each data directory is a separate single-person workspace. This is a local personal tool, not a public multi-user SaaS; it has no account system.

## Use the website

1. **Career profile:** enter contact details, skills, technologies, work bullets, projects, education, certifications, achievements, languages, and additional résumé text. Include names, dates, links, and outcomes within the bullets.
2. Leave target roles blank to infer up to five role families from your evidence, or specify your own. Suggestions recalculate whenever the profile is saved. Add advertised location filters and exclusions.
3. Upload your original résumé. The browser helper uses this file as its attachment; generated drafts do not silently replace it.
4. Click **Save & find my jobs**. The app fetches the configured companies' Greenhouse, Lever, Lever EU, and Ashby feeds, deduplicates jobs, and scores them against your current profile.
5. In **Discover jobs**, select jobs and prepare them in batches. Open a job to review its fit, missing skill evidence, résumé draft, cover letter, and source posting. Download its ZIP; `resume.html` can be printed to PDF from your browser.
6. Approve reviewed applications individually or in a selected batch. Connect the browser helper from **Automation** and run an approved batch.
7. Track results under **Applications**. Record manual submission confirmations, interviews, offers, or rejections. **Analytics** shows confirmed volume, recorded response rate, interview/offer stage rate, weekly submissions, source performance, and the event log.

Changes to a profile, résumé, or posting invalidate pending materials and approvals. Submitted applications retain their history. The helper claims each approved record atomically to prevent concurrent duplicate attempts.

## What is automated

| Step | Behavior |
| --- | --- |
| Role suggestions | Local evidence matching against an editable catalog of 30 role families; runtime, not hardcoded to one applicant |
| Discovery | Read-only public ATS APIs; scheduled refresh, retries for selected transient failures, per-source errors |
| Matching | Transparent score, skill coverage, evidence, exclusions, location checks, posting-age checks |
| Preparation | Batch résumé and cover-letter drafts using only user-authored statements |
| Autofill | Standard named contact fields, original résumé upload, exact saved screening answers on supported ATS hosts |
| Submission | Experimental standard **Lever** adapter, only for approved records and with a separate explicit helper toggle |
| Tracking | Confirmations, review-needed and unknown outcomes, complete per-job event histories |
| Analytics | Recorded outcomes and confirmed submissions; no assumption that opening or filling a form means applying |

Autofill on Greenhouse/Ashby is a generic standard-field adapter, not comprehensive platform support. First/last names, custom widgets, legal or demographic answers, CAPTCHA, login, and multi-step forms may need manual handling. Unknown answers are left blank. No CAPTCHA bypass, stealth tooling, password storage, or recruiter-email sending is included.

The browser helper has **not been validated by submitting real applications**. Its submit gate and state handling are tested; live employer forms vary. Start with autofill-only mode. For a form you submit manually, use **Confirm submitted manually** and record its actual confirmation in the app.

If a click is sent but no recognizable confirmation appears, the status becomes `submission_unknown`. It is excluded from confirmed analytics and cannot be automatically requeued. Check the employer portal or confirmation email, then record the verified result. Unfinished browser claims expire after 15 minutes into review-needed or unknown state.

## Match percentages

**Overall match, 0–100:** up to 45 points for target-title word overlap, 40 for evidence covering recognized skill mentions, 10 for an advertised location match, and 5 for a verified publication in the last seven days. A detected experience shortfall subtracts 10 points.

**Skill coverage:** recognized skills in the posting supported by your profile ÷ all recognized skills in the posting. Skills come from the role catalog and your own skills. Missing evidence is displayed separately. Optional skill mentions may be included; this does not parse every requirement.

Neither percentage is a probability of hiring, an employer's ATS score, or a complete measure of eligibility. Work authorization, geography, required credentials, nuanced experience, and unrecognized requirements need review. Remote does not imply worldwide eligibility. Unknown publication dates are shown as unknown; Greenhouse's update timestamp is not treated as publication.

The rule-based matcher is deliberately inspectable and free. It does not understand all synonyms, infer a complete career path, or replace a recruiter. Edit `jobpilot/roles.py` to extend role families and reference skills.

## Expand discovery

The nine starter company boards are examples, not the entire job market. Add employer slugs under **Job sources**, or import arbitrary postings through **Add job**. A sample import schema is in [`examples/jobs.json`](examples/jobs.json). JSON import accepts up to 5,000 records per request.

For broader searches, the optional [JobSpy](https://github.com/speedyapply/JobSpy) importer reads roles and location from the saved profile:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install python-jobspy
python -m jobpilot.jobspy_import --country india --sites indeed --limit 30
```

Use `--location` to override the profile location. Board access and library compatibility can change; blocked sources report errors and are not bypassed. This optional integration is separate from the dependency-free core and was not live-tested with JobSpy installed. Consult each site's rules before enabling a scraper. JobSpy is discovery, not submission.

No system can promise to discover **every** job or reliably submit **every** employer's application. The research rationale and coverage comparison are in [`docs/RESEARCH.md`](docs/RESEARCH.md).

## Browser helper setup

1. In Automation, download and unzip the helper, or use the repository's `extension/` folder.
2. In a Chromium browser, open `chrome://extensions` / `brave://extensions` / `edge://extensions`.
3. Enable Developer mode and choose **Load unpacked**, selecting the extension folder.
4. Open the helper, enter the local server URL, and paste the private connection token copied from Automation.
5. Click Connect. Approve reviewed jobs in the dashboard, then start a batch. Job-site permissions are requested when starting a batch, limited to supported ATS hosts.

By default, the helper fills forms and stops for final review. The optional Lever auto-submit toggle only submits already-approved, recognized complete forms. Keep the browser and server open. **Stop** prevents subsequent submissions; it cannot undo a request already sent.

## Data, exports, and privacy

- SQLite database: `data/jobpilot.sqlite3`; original résumé: `data/resume.bin`. Both remain local and are excluded from Git.
- The local server binds only to `127.0.0.1`, validates host/origin headers, and uses a random bearer token for API requests. Keep the connection token private.
- Your résumé and profile fields leave your computer only when the helper fills an employer's application page. A website can observe field input before submission.
- Export JSON from the header for a profile/jobs/events snapshot, or CSV from Applications/Analytics. JSON export excludes the connection token and binary résumé.
- For a restorable backup, stop the server and copy the entire `data/` folder. Restore by pointing `--data` at that copy. Data is not encrypted at rest; use your computer's disk encryption and normal private-file practices.
- This version has no mailbox integration. Interview/offer/rejection outcomes require manual updates.

## Tests

Python tests use the standard library. Node 18+ is only needed for helper tests, not for running the app.

```sh
python3 -m unittest discover -s tests -v
node --test tests/extension.test.js
```

The suite covers matching, skill gaps, runtime role suggestions, geography, stale postings, source normalization/pagination, URL handling, evidence-preserving materials, transactional deduplication, approval invalidation, concurrent claims, uncertain submission recovery, authenticated HTTP workflows, exports, and helper submission gates.

## Project layout

```text
jobpilot/        SQLite store, matcher, source adapters, HTTP server, scheduler
static/          Responsive dashboard and onboarding
extension/       Chromium browser helper, no bundled third-party dependencies
tests/           Python integration/unit tests and Node helper tests
docs/            Research and implementation decisions
examples/        Import schema example
```

MIT licensed. Written independently; the researched repositories were not vendored or copied.
