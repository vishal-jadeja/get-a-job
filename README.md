# JobPilot

A free, local job-search workspace: **career profile → suggested roles → matching jobs → tailored materials → your approval → browser-assisted applications → outcome analytics**.

The core app uses Python's standard library, SQLite, and plain JavaScript. No subscription, paid API, cloud database, Docker, or LLM is required. There is no tracking or external font dependency.

## Run

Requires Python **3.10+**. From this folder:

```sh


```

Open **http://127.0.0.1:8765**. Another port or data directory:

On Windows, use `python -m jobpilot` from PowerShell. No dependency installation is needed for the core app.

```sh
python3 -m jobpilot --port 8766 --data /path/to/private-data
```

Keep the server running for scheduled discovery. Each data directory is a separate single-person workspace. This is a local personal tool, not a public multi-user SaaS; it has no account system.

## Use the website

1. **Career profile:** enter contact details, skills, technologies, work bullets, projects, education, certifications, achievements, languages, and additional résumé text. Include names, dates, links, and outcomes within the bullets.
2. Leave target roles blank to infer up to five role families from your evidence, or specify your own. Suggestions recalculate whenever the profile is saved. Add advertised location filters and exclusions.
3. Upload your default résumé and any role-specific files in the **Résumé library**. Choose an attachment in each job's workspace. Generated drafts do not silently replace uploaded files.
4. Click **Save & find my jobs**. The app fetches the configured companies' Greenhouse, Lever, Lever EU, and Ashby feeds, deduplicates jobs, and scores them against your current profile.
5. In **Discover jobs**, select jobs and prepare them in batches. Open a job to review its fit, missing skill evidence, résumé draft, cover letter, and source posting. Download its ZIP; `resume.html` can be printed to PDF from your browser.
6. Approve reviewed applications individually or in a selected batch. Under **Applications**, select approved jobs and click **Queue selected**. Connect the browser helper from **Automation** and run that queue.
7. Track results under **Applications**. Record manual submission confirmations, interviews, offers, or rejections. **Analytics** shows confirmed volume, recorded response rate, interview/offer stage rate, weekly submissions, source performance, and the event log.

Changes to a profile, résumé, or posting invalidate pending materials and approvals. Submitted applications retain their history. The helper claims each approved record atomically to prevent concurrent duplicate attempts.

## Manage the whole search

- **Today:** weekly application goal, pending tasks, shortlisted priorities, deadlines, and recent activity. Only confirmed submissions count toward the goal.
- **Discover:** shortlist jobs, add tags and priorities, filter by source/status/tag, sort by match/date/deadline/company, and save searches. Select 2–4 jobs to compare them side by side.
- **Applications:** board or list view, batch preparation and approval, selected-material ZIP downloads, and an explicit helper queue. Archive and restore applications without losing submitted history.
- **Each job workspace:** compensation notes, application deadline, next steps, attachment selection, editable résumé/cover-letter drafts, and revision history. Editing materials clears approval.
- **Planner:** dated tasks, follow-ups, and interviews with optional local time; mark complete or reopen. Export open dated tasks to an `.ics` calendar. For notifications, import the file into your calendar app; JobPilot does not send background notifications.
- **Contacts:** recruiter/referral contact records, conversation notes, editable outreach drafts, and follow-up tasks. Drafts are copied for you to send; JobPilot does not send messages.
- **Interview prep:** prompts grounded in recognized skills, skill gaps, questions to ask, and persistent preparation notes.

## Different résumés for different roles

1. Save your complete career evidence in **Career profile**.
2. Under **Role-focused résumés**, create profiles such as Backend Engineering and Frontend Engineering. Enter target job titles, a truthful headline, relevant skills, experience, and projects, and limits for each section.
3. Prepare jobs individually or in batches. The app chooses a role profile by title-word overlap (at least 60% of a target title's words), or falls back to your general profile. Ties use the first stored matching profile. You can override this selection per application.
4. Within that profile, each posting's requirements rank the saved skills, experience bullets, and projects. No missing skill, achievement, or employment claim is invented. Unchecked entire evidence sections use the full saved list.
5. Review the result and the displayed tailoring profile; edit the drafts if needed. Preparation automatically creates LaTeX using an adaptation of [Jake's Resume](https://www.overleaf.com/latex/templates/jakes-resume/syzfjbzwjncs). Use **Download LaTeX** for Overleaf, **Download PDF** for local compilation, or **Generate PDFs** for up to 20 selected applications. ZIPs include `resume.tex`, the template license, and a PDF when generated.
6. Click **Use tailored PDF as attachment** to compile/select the job-specific PDF without losing your edited draft. Review and approve again. You can also choose a separately uploaded file from **Résumé library**. The selected attachment is always shown separately.

Local PDF compilation requires [Tectonic](https://tectonic-typesetting.github.io/en-US/install.html). Put its executable on PATH, under `.tools/tectonic/`, or set `JOBPILOT_TECTONIC` to its full path. First use downloads LaTeX packages; later runs reuse the cache. Compilation runs locally with untrusted-input mode, escaped applicant text, and a timeout. No applicant data is sent to Overleaf or a remote compiler. Without Tectonic, download the `.tex` source or print `resume.html` from a browser. Long profiles may produce multiple pages; review the PDF and reduce the role profile's evidence limits if needed.

Role profiles control draft content; the résumé library contains actual attachment files. Updating role profiles invalidates pending drafts/approvals. Submitted drafts remain unchanged. If selected career evidence has been removed or rewritten, update the role profile before preparing again.

## What is automated

| Step | Behavior |
| --- | --- |
| Role suggestions | Local evidence matching against an editable catalog of 30 role families; runtime, not hardcoded to one applicant |
| Discovery | Read-only public ATS APIs; scheduled refresh, retries for selected transient failures, per-source errors |
| Matching | Transparent score, skill coverage, evidence, exclusions, location checks, posting-age checks |
| Preparation | Per-role and per-posting résumé/cover-letter drafts, editable with revision history |
| Autofill | Standard contact fields, explicitly saved first/last names, per-job résumé attachment, exact saved screening answers |
| Submission | Experimental standard **Lever** adapter, only for approved records and with a separate explicit helper toggle |
| Tracking | Confirmations, review-needed and unknown outcomes, complete per-job event histories |
| Analytics | Recorded outcomes and confirmed submissions; no assumption that opening or filling a form means applying |

Autofill on Greenhouse/Ashby is a generic standard-field adapter, not comprehensive platform support. Enter first/last names explicitly in the profile; the helper never splits a full name to guess them. Custom widgets, legal or demographic answers, CAPTCHA, login, and multi-step forms may need manual handling. Unknown answers are left blank. No CAPTCHA bypass, stealth tooling, password storage, or recruiter-email sending is included.

The browser helper has **not been validated by submitting real applications**. Its submit gate and state handling are tested; live employer forms vary. Start with autofill-only mode. For a form you submit manually, use **Confirm submitted manually** and record its actual confirmation in the app.

If a click is sent but no recognizable confirmation appears, the status becomes `submission_unknown`. It is excluded from confirmed analytics and cannot be automatically requeued. Check the employer portal or confirmation email, then record the verified result. Unfinished browser claims expire after 15 minutes into review-needed or unknown state.

## Match percentages

**Overall match, 0–100:** up to 45 points for target-title word overlap, 40 for evidence covering recognized skill mentions, 10 for an advertised location match, and 5 for a verified publication in the last seven days. A detected experience shortfall subtracts 10 points.

**Skill coverage:** recognized skills in the posting supported by your profile ÷ all recognized skills in the posting. Skills come from the role catalog and your own skills. Missing evidence is displayed separately. Optional skill mentions may be included; this does not parse every requirement.

Neither percentage is a probability of hiring, an employer's ATS score, or a complete measure of eligibility. Work authorization, geography, required credentials, nuanced experience, and unrecognized requirements need review. Remote does not imply worldwide eligibility. Unknown publication dates are shown as unknown; Greenhouse's update timestamp is not treated as publication.

The rule-based matcher is deliberately inspectable and free. It does not understand all synonyms, infer a complete career path, or replace a recruiter. Edit `jobpilot/roles.py` to extend role families and reference skills.

## Expand discovery

The nine starter company boards are examples, not the entire job market. Add employer slugs under **Job sources**, or import arbitrary postings through **Add job**. A sample import schema is in [`examples/jobs.json`](examples/jobs.json). JSON import accepts up to 5,000 records per request.

### Optional Firecrawl search and URL import

In Discover, **Search the web** sends your typed query to Firecrawl and shows up to 10 web results. **Preview import** extracts a single posting. Alternatively, paste a URL in **Add job** and click **Import from URL with Firecrawl**. Review and correct the extracted fields before saving. Search/extraction do not apply for jobs.

Set an API key in **Automation → Firecrawl web discovery** for the current server session, or configure `FIRECRAWL_API_KEY` in the server environment before starting JobPilot. Keys entered in the app remain in server memory and are never exported. Guest search and posting extraction were verified without a key on 2026-09-28; guest access can still be unavailable or rate-limited. If a guest request is rejected, configure a key or use manual import. Account credits and service limits apply.

Only the posting URL or explicit search query is sent to Firecrawl. Applicant profiles and résumé files are not sent. Manual import and public ATS discovery work without Firecrawl. This integration uses the [v2 single-page JSON extraction API](https://docs.firecrawl.dev/features/llm-extract) and [v2 search API](https://docs.firecrawl.dev/features/search). HTTPS uses the same certificate verification as ATS discovery, including the system CA bundle fallback for macOS Python installations missing their default bundle.

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

The helper also has **Preview current posting**, using user-triggered `activeTab` access. Open a public HTTPS posting, preview captured details, correct the title/company/description, then save it. It reads posting text and structured JobPosting data, not form input values. Capture does not require Firecrawl. After updating the repository, reload the unpacked extension to use the new helper version.

## Data, exports, and privacy

- SQLite database: `data/jobpilot.sqlite3`; default résumé: `data/resume.bin`; variant attachment files are stored as SQLite blobs. All remain local and are excluded from Git.
- The local server binds only to `127.0.0.1`, validates host/origin headers, and uses a random bearer token for API requests. Keep the connection token private.
- Your résumé and profile fields leave your computer only when the helper fills an employer's application page. A website can observe field input before submission.
- Export JSON from the header for profile/jobs/events/planning data, or CSV from Applications/Analytics with tracking details. JSON is an export, not a complete backup; it excludes tokens, attachment binaries, and historical material revisions.
- **Automation → Download full backup** makes a consistent SQLite snapshot including résumé variants, planning records, and draft history, plus the default attachment. It removes the connection token. Stop the server, extract the ZIP into a **new private folder**, then start with `python -m jobpilot --data "path/to/folder"`. Reconnect the helper with the new token. Restore instructions are inside the ZIP. Alternatively, stop the server and copy the whole data folder. Data and backups are not encrypted at rest.
- This version has no mailbox integration. Interview/offer/rejection outcomes require manual updates.

## Tests

Python tests use the standard library. Node 18+ is only needed for helper tests, not for running the app.

```sh
python3 -m unittest discover -s tests -v
node --test tests/extension.test.js
```

To also check real résumé PDF compilation and extracted text, install Tectonic
and Poppler (`pdftotext`), then run:

```sh
JOBPILOT_TEST_PDF=1 python3 -m unittest discover -s tests -q
```

This optional test is skipped by default. A fictional résumé for visual review
can be generated with `python3 tests/render_resume.py`; see
[`docs/VERIFICATION.md`](docs/VERIFICATION.md) for the current checkpoint.

The suite covers matching, skill gaps, runtime role suggestions, geography, stale postings, source normalization/pagination, URL handling, evidence-preserving materials, transactional deduplication, approval invalidation, concurrent claims, uncertain submission recovery, authenticated HTTP workflows, exports, and helper submission gates.

It also covers role-specific tailoring, résumé selection, draft revisions, archive restoration, persistent planning records, calendar output, backup restoration/token removal, explicit queues, Firecrawl response parsing, and credential exclusion. See [verification notes](docs/VERIFICATION.md) for the distinction between fixture tests, browser QA, and live external checks.

For a disposable browser-test workspace with fictional jobs:

```sh
python tests/serve_ui.py
```

Open `http://127.0.0.1:18765`. This uses a temporary database, not your normal workspace.

## Project layout

```text
jobpilot/        SQLite store, matcher, source adapters, HTTP server, scheduler
static/          Responsive dashboard and onboarding
extension/       Chromium browser helper, no bundled third-party dependencies
tests/           Python integration/unit tests and Node helper tests
docs/            Research and implementation decisions
examples/        Import schema example
```

MIT licensed. The adapted Jake's Resume LaTeX template is attributed to Jake Gutierrez, based on sb2nov/resume; its MIT license is included in `jobpilot/templates/LICENSE-jake.txt` and generated LaTeX/bundles. Other researched repositories were not vendored.
