# JobPilot personal job-search workspace

## Intent and scope

Build a complete personal workflow for finding roles, comparing opportunities,
preparing and reviewing multiple applications, and managing the follow-through.
The working assumption is a free, private, local-first app; existing Python 3.10+,
SQLite and plain JavaScript remain the stack. No paid service is required.
Success is a usable, persistent journey from imported/discovered jobs through
shortlisting, editable materials, explicit approval, browser assistance, confirmed
submission, follow-ups, contacts and interview preparation.

## Design

Use a focused workbench: Today, Discover, Applications, Planner, Contacts, and
the existing profile, analytics, automation and source management. Today shows
actual next actions, deadlines and weekly progress. Discovery supports saved
searches, bookmarks, tags, sorting and comparisons. Applications has board and
list views with a dedicated approved queue. Every job has a workspace for notes,
priority, compensation, deadlines, tasks, interview notes and editable documents.

Visual system: cool paper #f4f6fa, white #ffffff, ink #18243b, slate #66728a,
blue #315bd6, pale blue #eaf0ff. Use Segoe UI for the Windows-native workbench,
clear left-aligned headings, restrained borders, compact tables, and a blue
timeline accent for next actions. Responsive navigation and visible focus states.
No decorative marketing hero in the daily workflow.

## Implementation sequence

1. Add a workspace persistence module using additive tables for job metadata,
   tasks, recruiter contacts, saved searches, and material revisions. Validate
   dates, job references, bounded text and enumerated values. Preserve existing
   data and transaction semantics. Test reopen persistence and invalid inputs.
2. Add material editing with escaped printable HTML, immutable revision history,
   and approval invalidation. Add reversible archive, shortlisting and explicit
   manual submission for externally completed applications. Test state guards.
3. Add authenticated workspace APIs, calendar export, selected-material ZIPs,
   an explicit approved queue, and a complete SQLite/resume backup ZIP. Test
   authentication, archive contents and response behavior.
4. Build Today, planner, contacts, saved searches, comparison and pipeline views;
   extend job details with tracking, document editing and interview prep.
   Preserve existing profile/discovery functionality. Provide empty/loading/error
   states and editable forms that polling cannot discard.
5. Improve helper batch selection, safe first/last-name fields and capture of a
   current posting through a user-triggered action. Keep approval before filling,
   conservative submission checks, and uncertain-result recovery.
6. Run Python/Node suites, browser smoke and end-to-end fixture workflows; inspect
   desktop/mobile layouts, fix defects, update README and record verification.

## Review focus

- Existing databases reopen without data loss; archive restoration preserves stage.
- Editing documents clears approval; submitted history cannot be silently rewritten.
- Unknown submission outcomes cannot be requeued; selections never broaden a batch.
- User and imported text is escaped; dates and links are validated at the server.
- Form edits survive background refresh; keyboard actions and mobile controls work.

## Boundaries

This iteration does not create a public multi-user service, connect an inbox,
purchase services, send recruiter messages, or submit real applications during QA.
External forms and source availability vary; report what was actually verified.
Outreach and interview support are editable drafts/prompts grounded in saved data,
not fabricated experience or promises of hiring success.
