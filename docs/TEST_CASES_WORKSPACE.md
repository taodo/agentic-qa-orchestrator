# Test Cases workspace (Task 3.11)

The operator workspace is **Test Cases**; the domain contract remains
`CampaignTestSpecification`. Existing `/test-specifications` routes, `test_spec_id`
deep links, result/action fragments and API routes remain available. Traceability
is the primary Test Design Workbench; Import Existing Tests and the approved-only
secondary generation selection remain in collapsible sections below the table.
Import, generation and approval refresh the current table and readiness through
existing reads. No new provider, execution or backend behavior is introduced.

## Table and review boundaries

The table uses the current-only, bounded list (`limit=50`). Local keys/titles are
primary identity; structured steps, expected outcomes, evidence, linked Requirement
IDs, blockers and provenance are disclosed in row details. Approval evidence is
read only after an explicit request. An explicitly selected record missing from
the current list requires one detail read and appears separately as read-only
audit content: never a current selectable/exportable row, even if historically
READY_FOR_REVIEW. There is no automatic per-row detail fan-out.

All / Needs clarification / Ready for review / Approved counts describe returned
current records, never full Campaign totals. Filter changes clear selection.
Select all visible and Deselect all operate only on returned filtered rows.
Approved cases remain selectable for export, but cannot be approved again.

Bulk approval is a compact, initially collapsed panel directly below selection/export
and above the table. Its summary shows `Approve selected Test Cases (N eligible)`;
opening it reveals reviewer label, optional note and Confirm approval. It reuses
the accepted sequential single-record review API. It submits
only selected current READY_FOR_REVIEW cases without information markers,
unresolved references, missing links/evidence/overall result or missing step
expectations; the backend retains final authority. Reviewer labels remain operator
assertions. Progress and per-case public outcomes are shown, with no atomicity
claim or automatic retry. Authorization failures and navigation stop undispatched
requests; an already dispatched request cannot be undone. Conflicts require
operator inspection. Approval, coverage, readiness and execution results remain
separate concepts.

Both Requirements and Test Cases support broad noninteractive row clicks and
focused-row Enter/Space. Native visible disclosure summaries remain available.
Checkboxes, buttons, links, forms, fields and nested disclosures do not toggle the
outer row. Expanded rows use the existing theme and retain table semantics.

## Exact CSV contract

Exports use only already-loaded authoritative Test Case fields. Visible CSV
contains exactly filtered returned current rows; selected CSV contains exactly
explicitly selected visible current rows, in displayed order. Empty exports are
disabled. Truncation notices state that additional Campaign cases are excluded.
Export sends no API request, performs no detail fan-out and invokes no provider.
It is an operator download, not an exhaustive Campaign report or import template.

Stable header order:

```text
title,test_type,priority,preconditions,steps,overall_expected_result
```

Human-readable cell formatting (manual-acceptance follow-up):

- Title, test type and priority use their existing plain display values.
- No preconditions gives an empty cell; one is rendered verbatim; multiple are
  numbered `1. ...`, `2. ...` in authoritative array order, separated by LF.
- Steps are rendered by ascending authoritative step index (without mutating the
  stored array). Each action stays paired with its own expected result. Steps are
  separated by a blank line within the single cell. A null step expectation is
  left blank after `Expected:`; no result is invented.
- Overall expected result is already `string | null` in the authoritative contract:
  plain text is preserved, including its line breaks; null becomes an empty cell.
- Arrays/objects are never JSON-serialized into this user-facing export. Internal
  structured domain data is unchanged. Audit fields/IDs/review status/Requirement
  links/evidence/markers/provenance are not exported. This is a readable execution
  aid, not a lossless domain archive or an import template.

Example of the single `steps` cell:

```text
1. Action: Attempt to submit the booking without providing a guest name.
   Expected: The booking is rejected.

2. Action: Inspect the post-submission persistence state and compare it with the recorded pre-submission state.
   Expected: No partial booking record attributable to the rejected attempt is persisted.
```

Encoding and safety:

- UTF-8 with BOM for spreadsheet Unicode detection; CSV records end in CRLF.
- Every cell is double-quoted, with internal quotes doubled. Commas, quotes,
  embedded CR/LF and Unicode are preserved. Multiline steps/preconditions remain
  exactly one cell each, not extra CSV records or columns.
- All six cells receive spreadsheet protection **after** readable formatting.
  Plain cells beginning with `=`, `+`, `-` or `@`, including after whitespace or
  control characters, receive a leading literal apostrophe. Cells starting with
  control characters are also protected. Numbered content starts with its index;
  embedded formula-like action/expected text remains ordinary cell content.
  Consumers should treat exported cells as data and retain this protection.
- No hidden runtime/config, credentials, provider objects or usage data is added.
  Operators must still avoid entering secrets into preparation content.
- Filenames use a normalized ASCII Campaign slug (maximum 60 characters; fallback
  `campaign`) plus `-test-cases-visible.csv` or `-test-cases-selected.csv`. Campaign
  text never becomes a filesystem path. Temporary browser object URLs are released.

## Manual showcase after technical review

Use synthetic prepared data. These are operator checks, not a claimed live run.

1. Confirm sidebar/page Test Cases and compact local key/title table.
2. Inspect all filters and returned counts; select visible, deselect and change
   filters. Confirm hidden and historical cases are excluded.
3. Toggle Test Case and Requirement rows by broad click, summary and keyboard;
   check that checkbox, link, nested disclosure and form controls remain independent.
4. Inspect structured detail and explicitly load approval evidence.
5. Select eligible cases, open the top approval panel and confirm approval, including a conflict; verify individual results
   and excluded clarification/approved cases. Verify readiness through existing reads.
6. Export visible CSV, open it in the operator's spreadsheet program and inspect
   Unicode, multiline cells and protected formula-like text. Export a selected
   subset; verify exactly those rows and bounded-list notices.
7. Import existing tests and inspect the refreshed table. Traceability generation
   remains APPROVED-only; Go to Test Cases retains its existing destination.
8. Verify readiness, QA Run and synthetic outcome semantics remain unchanged.

No XLSX, pagination expansion, bulk transaction, generic status override or new
Test Case clarification editor is added. No migration or dependency is needed.
