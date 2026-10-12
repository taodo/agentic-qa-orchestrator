# Product workspace UI

Task 3.6 is presentation only. React, local system typography and plain CSS remain
our stack; no component package, runtime font fetch or animation framework is used.

## Conventions

- `app.css` defines charcoal surfaces, spacing, fields, buttons, notices, bounded
  tables and keyboard focus. Use `.button--primary` for the explicit primary action;
  secondary actions use the shared button style. Preserve labels, disabled/busy
  state and safe inline feedback from the action components.
- `PageHeader`, `SectionHeader` and `Metric` have concrete workspace consumers.
  Existing `.panel`, lists and Feedback components supply surfaces and feedback.
  Add an abstraction only for repeated real use.
- `StateBadge` supplies shared semantic tones and visible text; Campaign badges
  keep friendly labels plus exact status in the title. COMPLETED is neutral and
  separate from PASS/FAIL. READY is preparation readiness, never a QA result.
- The sidebar receives already-loaded Project/Campaign context. It adds no reads,
  detail fan-out, writes or provider actions. One navigation set wraps on narrow
  windows; desktop navigation stays sticky. Operations/legacy remains secondary.
- Overview/Readiness guidance maps existing backend blocker codes to navigation.
  Satisfied/Blocking rows display those codes; backend status and aggregates remain
  authoritative. Guidance never enables an action or computes a readiness gate.
- Requirements and Test Specifications emphasize current keys, titles, review
  status and structured content. Audit IDs/provenance/history remain available
  through secondary disclosures. Requirement links use existing explicit detail
  selection, never automatic reads for every linked record.
- Source ingestion, extraction retry, clarification saving, AI revision and human
  review remain separate explicit actions. Saving clarification never approves or
  starts revision. Task 3.7 adds compact action-local
  summaries; see [AI action results](AI_ACTION_RESULTS.md) for authoritative field
  sources and unknown-usage semantics.
- Runs retain synthetic warnings, immutable snapshot evidence and distinct
  execution/QA outcome badges. No external target is tested by synthetic execution.
- Tables may scroll inside their own container; ordinary pages should not scroll
  horizontally. Respect `prefers-reduced-motion`; no entrance/scroll choreography.

## Human visual review checklist

Use synthetic prepared data, including incomplete preparation and a completed
synthetic Run with mixed results. Do not invoke a real provider for visual review.

- Projects/Project: registry, create form, context, Campaign list, secondary legacy.
- Overview: objective, preparation/readiness distinction, backend totals, blocker
  list and relevant next-step link. Check READY and NOT_READY and read failure.
- Requirements: compact key/title/status table, returned-count filters, visible-only
  selection and sequential bulk approval. Criteria, source citations, row clarification
  and lazy approval/version history live in row details. Confirm source intake remains
  reachable below; saving facts never invokes revision automatically.
- Failed extraction: eligible Retry is explicit; history and token warning remain.
- NEEDS_CLARIFICATION: grounded-facts form is reachable; saving, revising and human
  approval remain separate. Blocked content must not offer an approval bypass.
- Test Cases: compact current-only key/title table, returned-count filters, visible
  selection/export and sequential eligible bulk approval. Structured row detail,
  lazy approval evidence and separate out-of-list audit content remain explicit.
  Import and approved-only generation are secondary collapsible sections.
- Requirements/Test Cases: broad noninteractive row click and focused Enter/Space
  toggle detail; checkbox, buttons, links, forms and nested summaries act independently.
  Check selected/expanded cues and visible native disclosure controls.
- CSV: visible and selected subsets, truncation notice, Unicode/multiline/quote
  round trips and safe formula handling; see [CSV contract](TEST_CASES_WORKSPACE.md).
- Traceability: coverage text, linked/approved counts, optional-name UUID fallback,
  truncation notices and contained table scrolling. No automatic detail fan-out.
  Test Design Workbench enables per-row/batch Generate only for current APPROVED
  rows, at most 20. Success offers Go to Test Cases / Stay on Traceability; failure
  retains the safe code/known usage and never redirects or retries. Verify optional
  name failure does not disable valid coverage or approved UUID-only selection.
- Readiness: satisfied checks, blockers, next link and full server aggregates.
- Runs/detail: run number, separate execution/QA outcome, global persisted result
  counts and bounded Test Results table. Expand readable SYNTHETIC evidence, distinguish
  collected records from required-evidence descriptions, and inspect historical
  zero-evidence/FAILED-PARTIAL cases. Snapshot context, explicit Start and pagination
  remain. See [Run Results](QA_RUN_RESULTS.md).
- Widths: approximately 1366, 1440 and 1920 pixels, plus a narrow 390-pixel window.
  Check long IDs/text and absence of ordinary horizontal page overflow.
- Keyboard: Tab through navigation/forms/disclosures, visible focus, activate Skip
  to content, and verify an obvious active Campaign route including Run detail.
- Reduced motion: enable the OS/browser preference and confirm hover/focus remains
  usable without animation/transition. The CSS rule also disables smooth scrolling.

Automated tests cover navigation, status text, readiness guidance and existing
preparation recovery behavior; browser fixture review checks appearance only.

## UI V3 foundation

UI V3 preserves existing React/plain-CSS and API contracts. Semantic surface,
field, border, text, accent and status tokens define charcoal/purple dark mode
and deliberately neutral light mode. The shell exposes a compact Appearance
control; only `qa-sentinel.theme` (`dark`/`light`) is persisted in localStorage.
Missing, invalid or unavailable storage falls back to dark. Storage failures still
allow a session-local selection. The same-origin `/assets/theme-init.js` runs
before the SPA, fits the existing hosted `script-src 'self'` policy and static
asset allowlist, and touches no auth/project/session configuration.

The compact sidebar retains one workflow navigation set and explicit current
Project/Campaign context. Where already loaded, live Campaign Target decoration
is published without extra shell reads and labelled LIVE CONFIG. Historical Run
Target context always stays in the Run view and comes from its immutable snapshot.
Results is active for nested Run routes. Narrow layouts expose a Navigation toggle
without removing workflow links; tables scroll within bounded containers. Keyboard
focus, skip-to-content, native disclosures, textual statuses and reduced-motion
rules remain. Semantic PASS/FAIL colors are distinct from the purple accent.

Workspace Overview uses authoritative readiness requirement/test counts, one
bounded `listRuns?limit=50` read, latest returned Run metadata, and five recent
rows with explicit returned/truncated disclosure. Unknown counts are Unavailable;
no history is No Run/Not evaluated. Approved tests are never relabelled executable.
The workflow strip presents counts and saved status, not a frontend state machine.
Next-action links are guidance and do not enable execution. Preparation metadata
and Run outcomes remain independent. There is no Project-wide aggregate or fabricated
Dashboard: Campaign-owned Target/history cannot be inferred as a Project default.

Recent Runs uses only stored metadata, including target_snapshot; passed/failed
columns are omitted because this list API does not expose those aggregates. Run
Results retains the authoritative aggregate counts, COMPLETED + FAIL distinction,
bounded evidence disclosures, immutable Target context and CSV/XLSX export. No N+1
result/detail calls are made to populate the overview. Specification limitations,
explicit retry/clarification actions, analysis audit, current test tables, approval,
selection, human edit and source traceability remain reachable. Target creation
is an explicit New Target disclosure; existing Campaign selection says Change Target.

Visual review uses disposable read-only synthetic fixtures, never a live provider,
operator database or Target URL. Verify dark/light Overview and Results, desktop /
tablet / 390px navigation, long URL/IDs, status text, field/focus contrast, bounded
scrolling, document limitations and expanded evidence. A synthetic screenshot is
UI review proof, not evidence of real application testing.

### Reviewed visual refinement

The refinement keeps the same requests/actions and theme persistence. A compact
Target hero groups authoritative name, environment, inert URL, Campaign identity
and already-loaded preparation counts; its SYNTHETIC warning stays visible and
association context is a native disclosure. Project UUID remains available in the
Project link title instead of primary navigation. Sidebar labels are calmer, with
stronger purple selection and quieter Settings/Audit hierarchy.

Metrics share one surface, workflow steps use connected horizontal/vertical
presentation without derived completion states, and Recent Runs emphasizes stored
Run identity and semantic outcomes. Dark and light have distinct hero, sidebar,
section and metric surfaces, modest shadows and stronger system typography.
No new API read, state machine, fake health indicator or behavioral gate is added.

### Visual Pass 2: QA command center

Dark-first purple gradients, restrained glows and category icon tiles distinguish
navigation, Target hero, metrics and connected workflow. Light mode uses its own
readable pale surfaces. The contextual rail reuses the already-loaded Target and
links to existing preparation/results routes; it introduces no additional reads.

Results charts only the persisted RunResults.summary total, passed, failed,
skipped and not_evaluated counts. Empty or contradictory counts produce an honest
notice instead of invented segments. Text counts remain available alongside the
static decorative SVG. Overview does not fetch result details to invent a chart,
health, pass rate, trend, duration or activity feed. Mobile stacks main content
before contextual cards; existing bounded table/evidence disclosures remain intact.
