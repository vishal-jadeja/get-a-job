# Job-hunting automation research

Research date: **25 September 2026**. This is a representative review of official product pages, repository READMEs, and ATS documentation—not an exhaustive census of all platforms or a claim that every repository was installed and audited. Marketing claims are attributed to their authors. Prices, free quotas, repositories, and supported boards change.

Networking / YC follow-up: **29 September 2026**. The [public YC engineering page](https://www.ycombinator.com/jobs/role/software-engineer) and its linked location pages expose server-rendered posting records, while the page links to account creation for additional jobs. The new connector reads those public records, reports coverage, and loads full public job pages for complete requirements. It does not claim access to the entire signed-in directory. Batch recency and reported listing activity are explicit sorting signals, not a verified startup-popularity ranking.

Company and people discovery uses public search snippets through the existing Firecrawl integration and professional links on public YC pages. Direct LinkedIn scraping and automated connection/message actions are excluded; see [LinkedIn's guidance](https://www.linkedin.com/help/linkedin/answer/a1341387). Public search snippets are labeled as unverified candidates, with source links and lookup dates. Outreach uses locally saved applicant evidence and remains an editable draft.

## Platforms

| Platform | What its primary source offers | Free constraint / implication for this project |
| --- | --- | --- |
| [Simplify Copilot](https://simplify.jobs/copilot) | Application autofill, job tracking, matching, résumé tools | Its site commits to free autofill and core tracking. Strong benchmark for user-controlled form completion. |
| [Simplify Autopilot](https://help.simplify.jobs/en/help/articles/1784339-getting-started-with-autopilot) | Automated filling and submission | Official help describes a beta for a subset of Simplify+ subscribers. Distinguish free autofill from paid autonomous application. |
| [Teal](https://www.tealhq.com/pricing) | Job tracker, multiple résumés, keyword analysis, AI materials | Free tracking and résumé tools; fuller keyword analysis and AI features are premium. Adopt the unified workspace concept. |
| [Huntr](https://huntr.co/pricing) | Application organization and résumé assistance with Free and Pro plans | Useful tracking benchmark; do not assume every AI feature is free. |
| [LoopCV](https://www.loopcv.pro/pricing/) | Automated search and application workflow | Official page describes a limited free plan and paid higher volume. Free does not mean unlimited application throughput. |
| [Sonara](https://www.sonara.ai/) | Managed job-search and auto-application product | Review of public product positioning only; no assumption of a sustainable unlimited free tier. A managed service adds an external data processor. |

Product comparison led to four requirements: own the career data, explain the fit, retain per-application control, and record observed results rather than claimed activity.

## GitHub projects

| Repository | Documented strength | Decision |
| --- | --- | --- |
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) | Aggregates jobs from multiple major job boards into structured records; MIT license shown | Offer an optional importer. The core uses public ATS feeds so scraping and its dependency stack are not mandatory. |
| [Pickle-Pixel/ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot) | Staged discover/enrich/score/tailor/apply workflow, broad board coverage | Adopt independently staged operations. Its full documented path includes model tooling and browser automation; source availability alone does not guarantee zero operating cost. |
| [Liam-Frost/AutoApply](https://github.com/Liam-Frost/AutoApply) | Applicant memory, review gates, scoring, materials, tracking | Strong conceptual fit. Its README specifies PolyForm Noncommercial; do not treat that as a permissive commercial open-source license. This project is independently implemented. |
| [AbhishekMandapmalvi/AutoApply](https://github.com/AbhishekMandapmalvi/AutoApply) | README describes multi-ATS applications, knowledge base, scheduling, scoring, provider choices | Useful end-to-end checklist; claimed platform breadth requires actual adapter testing and depends on configured AI providers. |
| [Gsync/jobsync](https://github.com/Gsync/jobsync) | Self-hosted tracker, résumé/job assistance, optional local Ollama | Reinforces local data ownership and reporting; local AI can be optional rather than required. |
| [humancto/mr-jobs](https://github.com/humancto/mr-jobs) | Discovery, scoring, materials, autofill and tracking in a dashboard | Adopt source-level visibility and an explainable pipeline, without claiming the same tested integrations. |
| [vesaias/JobNavigator](https://github.com/vesaias/JobNavigator) | Company career sources, job-board search, persona, extension, tracker | Closest broad reference for a career profile plus browser helper. Its wider adapter surface has continuing maintenance costs. |
| [sentient-engineering/jobber](https://github.com/sentient-engineering/jobber) | Browser-controlling agent for job applications | Demonstrates agent-driven interaction; general agents still need controls around unknown answers and ambiguous submission success. |
| [Reactive Resume](https://github.com/reactive-resume/reactive-resume) | Dedicated open-source résumé builder | Good external option for richer résumé authoring. This version ships simple printable materials rather than duplicating an entire design editor. |
| [attdobi/aipply](https://github.com/attdobi/aipply) | README describes LinkedIn search, application, tailoring, and tracking | Platform-specific automation has a narrower maintenance surface but depends on that platform's browser behavior and rules. |
| [Historical AIHawk repository URL](https://github.com/feder-cr/Jobs_Applier_AI_Agent_AIHawk) | During research, the URL redirected to `feder-cr/invisible_playwright_mcp` | Old recommendation lists can become stale. Do not blindly clone an old “AIHawk” URL or equate current redirect contents with the historical project. |

This review evaluates documented capabilities and architectural tradeoffs. It does **not** establish comparative success rates, bug counts, security guarantees, popularity rankings, or that any project outperforms careful manual applications.

## What the ATS interfaces actually allow

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html): public read endpoints; application POST requires a Job Board API key. A candidate cannot assume they have the employer's key. Use public reads plus the hosted application form.
- [Lever Postings API](https://github.com/lever/postings-api): public posting data, pagination, hosted job/application links. The API does not expose custom posting questions. A candidate-facing generic API submission is not a substitute for the employer's actual form. The helper uses the visible form.
- [Ashby public job-posting API](https://developers.ashbyhq.com/docs/public-job-posting-api): company-board feed with descriptions, locations, publication fields and application URLs. Discover via the public feed; complete applications through the hosted workflow.
- [LinkedIn's prohibited-software guidance](https://www.linkedin.com/help/linkedin/answer/a1341387): browser automation can conflict with platform restrictions. The included helper does not automate LinkedIn, bypass CAPTCHA, or use anti-detection tooling.

These differences rule out the claim that one unauthenticated API can mass-submit every company's jobs.

## Architecture chosen

**Python standard library + SQLite + browser-native UI + an optional Chromium helper.** The benefit is immediate local execution with no required package downloads or metered services. The cost is a deliberately simpler rule-based matcher, templates, and narrower browser support.

The profile is the reusable source of truth. At runtime, role families are suggested from skills, technologies, work evidence, projects, and résumé text. The user can select or override them. Discovery loads all configured board postings, then applies that person's score and filters; adding a company does not require changing code. An optional JobSpy importer performs profile-based cross-board searches.

Qualification reporting separates **overall match** from **recognized-skill coverage**. Neither is a calibrated measure of actual qualification or hiring probability. Missing profile evidence is not proof that a person lacks a skill.

Documents select and reorder facts rather than asking a language model to invent persuasive details. A profile/posting fingerprint binds preparation and approval to the actual reviewed data. Any change invalidates pending approval. Claims are transactional, submission attempts are recorded before clicking, and uncertain outcomes cannot automatically retry.

The default browser mode prepares fields for final review. A separately enabled experimental Lever adapter may submit only approved forms whose recognized fields are complete, original résumé is attached, and no challenges were detected. All other workflows retain human review.

## Current limits and next useful expansions

1. **Coverage:** only configured employers are included in the core. A larger curated company directory and optional broader board search improve recall; no honest “all jobs” guarantee exists.
2. **Role reasoning:** 30 editable role families and lexical evidence. Extend the catalog for specific industries; aliases, explicit required-vs-preferred extraction, and evidence verification would improve relevance.
3. **Browser adapters:** standard fields only; authentication, custom dropdowns, multi-step forms and challenges are manual. No real application was sent during validation.
4. **Materials:** printable HTML/TXT and cover-letter drafts. Original uploaded files are passed through; there is no automatic PDF/DOCX content extraction or replacement of uploaded résumé bytes.
5. **Outcome ingestion:** submissions are recorded from known confirmation text or the user's manual verification. Interviews/rejections/offers are manually updated; there is no mailbox access.
6. **Deployment:** single-person, loopback-only operation. Public multi-user deployment would need accounts, isolation, encrypted secret handling, background workers, and operational monitoring.

“Perfect” would be a misleading promise. This implementation establishes a free, inspectable workflow with clear boundaries and room to expand based on real application outcomes.
