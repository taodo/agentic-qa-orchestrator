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
- Requirements: key/title/status, open acceptance criteria, source citations and
  lazy approval/version history. Confirm source intake remains reachable below.
- Failed extraction: eligible Retry is explicit; history and token warning remain.
- NEEDS_CLARIFICATION: grounded-facts form is reachable; saving, revising and human
  approval remain separate. Blocked content must not offer an approval bypass.
- Test Specifications: structured steps/expected result/evidence, markers, linked
  Requirements, secondary provenance, import and generation controls.
- Traceability: coverage text, linked/approved counts, optional-name UUID fallback,
  truncation notices and contained table scrolling. No automatic detail fan-out.
- Readiness: satisfied checks, blockers, next link and full server aggregates.
- Runs/detail: run number, execution versus QA outcome, timestamps, snapshot
  identity, pagination, explicit Start Synthetic Run and synthetic per-test labels.
- Widths: approximately 1366, 1440 and 1920 pixels, plus a narrow 390-pixel window.
  Check long IDs/text and absence of ordinary horizontal page overflow.
- Keyboard: Tab through navigation/forms/disclosures, visible focus, activate Skip
  to content, and verify an obvious active Campaign route including Run detail.
- Reduced motion: enable the OS/browser preference and confirm hover/focus remains
  usable without animation/transition. The CSS rule also disables smooth scrolling.

Automated tests cover navigation, status text, readiness guidance and existing
preparation recovery behavior; browser fixture review checks appearance only.
