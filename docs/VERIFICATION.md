# Verification checkpoint — 2026-09-28

## Passed

- `JOBPILOT_TEST_PDF=1 python3 -m unittest discover -s tests -q`: 67 tests passed,
  including real Tectonic compilation and PDF text extraction. The default suite
  passes 66 tests and skips this optional integration test.
- `node --test tests/extension.test.js`: 13 tests passed.
- Browser QA with fictional data: task creation/completion, job comparison,
  batch preparation, draft editing and approval invalidation, explicit queues,
  contact creation/outreach drafts, automatic role-profile selection, selected
  résumé attachment, and interview-preparation prompts.
- Desktop and 390px mobile dashboard layouts inspected.
- Live read-only Ashby check returned 30 Linear postings.
- Backups restore planning data and generate a new connection token; backup
  database bytes are checked to exclude the old token.
- Follow-up on macOS arm64: fixed the template's font lookup, which failed with
  `The font "Latin Modern Roman" cannot be found`. It now requests explicit font
  files from Tectonic's bundle instead of requiring an installed system font.
- Tectonic 0.17.0 compiled the fictional résumé through `compile_pdf` after the
  initial package download. Poppler confirmed one Letter-size page; the rendered
  page was visually inspected with no clipping or overlapping text. Text
  extraction preserved contact details, skills, experience, projects and education.
- Added an opt-in integration test for accented names, section headings, dates,
  and escaped characters (`&`, `%`, `#`) in the compiled PDF.
- Firecrawl follow-up: reproduced a certificate verification failure in Python
  before the request reached the service. Reused ATS discovery's verified HTTPS
  context, including its macOS system CA fallback. Added transport tests covering
  certificate configuration, authentication headers, HTTP errors, malformed and
  oversized responses, and network failures.
- Live keyless Firecrawl search returned 10 results. JSON extraction of one
  result returned a Software Engineer, New Grad posting at Palantir Technologies,
  with a 1,287-character description and the original posting URL preserved.
  Only a generic query and a public posting URL were sent; no jobs were imported.
- Fixed the helper's Stop timing gap after the server records a submission attempt
  but before dispatching the click. The worker now stops without clicking and
  records the conservative `submission_unknown` state with an explanatory note.
  Seven worker tests simulate Chrome/server responses to cover this gap, explicit
  and empty queues, autofill-only mode, rejected claims, redirects and unconfirmed
  clicks. These are not live employer-form tests.
- Browser follow-up in Brave with the disposable fixture workspace: selected-job
  preparation, actual PDF generation and attachment selection, approval, and draft
  editing all succeeded. Editing changed Approved back to Prepared as expected.

## Remaining live verification

- Tectonic 0.17.0 is available locally under ignored `.tools/tectonic`. A fresh
  package cache can still take longer than the app's 90-second timeout to populate.
  PDF rendering was verified on macOS with the fictional Latin-script samples;
  other scripts, long profiles and Windows/Linux rendering need further checks.
- Firecrawl authenticated account behavior remains fixture-tested. Guest access
  worked in the follow-up but may vary by service limits and network; earlier
  keyless attempts returned HTTP 403.
- The updated extension has not been installed and exercised against live
  employer forms in this run. No real applications have been submitted.
- No mailbox sync, public multi-user hosting, or recruiter-message sending.

## Reproduce

Run `python tests/serve_ui.py` for an isolated browser fixture workspace at
`http://127.0.0.1:18765`. It does not use the normal personal data folder.

Run `python tests/render_resume.py` for a fictional Jake-style résumé under
ignored `output/pdf/`. It needs Tectonic and package access on first use.

Run `JOBPILOT_TEST_PDF=1 python3 -m unittest discover -s tests -q` to include
real PDF compilation and text checks. This also needs Poppler's `pdftotext` on
PATH. Without the environment flag, the dependency-free suite skips that test.

For visual inspection, render the fixture with:

```sh
pdftoppm -scale-to 1500 -png -singlefile output/pdf/sample-resume.pdf output/pdf/sample-resume
```

The product scope and architectural choices are in `PRODUCT-PLAN.md`.
