# Verification checkpoint — 2026-09-28

## Passed

- `python -m unittest discover -s tests -q`: 59 tests passed.
- `node --test tests/extension.test.js`: 6 tests passed.
- Browser QA with fictional data: task creation/completion, job comparison,
  batch preparation, draft editing and approval invalidation, explicit queues,
  contact creation/outreach drafts, automatic role-profile selection, selected
  résumé attachment, and interview-preparation prompts.
- Desktop and 390px mobile dashboard layouts inspected.
- Live read-only Ashby check returned 30 Linear postings.
- Backups restore planning data and generate a new connection token; backup
  database bytes are checked to exclude the old token.

## Remaining live verification

- LaTeX source generation and PDF workflow/cache/state tests pass. Tectonic
  0.17.0 is installed locally under ignored `.tools/tectonic`. The first
  fictional PDF render exceeded the app timeout while fetching packages; a
  direct compiler run is warming its cache. Visual inspection and PDF text
  extraction must follow before claiming live PDF generation verified.
- Firecrawl URL/search parsing and HTTP behavior are fixture-tested. The live
  keyless request returned HTTP 403. Successful extraction/search needs a
  working service connection/API key.
- The updated extension has not been installed and exercised against live
  employer forms in this run. No real applications have been submitted.
- No mailbox sync, public multi-user hosting, or recruiter-message sending.

## Reproduce

Run `python tests/serve_ui.py` for an isolated browser fixture workspace at
`http://127.0.0.1:18765`. It does not use the normal personal data folder.

Run `python tests/render_resume.py` for a fictional Jake-style résumé under
ignored `output/pdf/`. It needs Tectonic and package access on first use.

The product scope and architectural choices are in `PRODUCT-PLAN.md`.
