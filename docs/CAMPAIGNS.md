# QA Campaign preparation (Task 2.1)

A QACampaign is a durable QA initiative owned by exactly one existing Project.
A Project can own multiple campaigns; campaign names need not be unique.
Campaign identity does not require a source repository, runtime binding or tests.
This task prepares campaigns; it does not execute them.

## Domain and lifecycle

The immutable domain entity and detached response contain id (UUID), project_id
(UUID), name (1–200 characters after whitespace stripping), optional objective
(null or at most 4,000 characters), status, created_at and updated_at. New
campaigns start at DRAFT with aware UTC timestamps. Ownership, identity and
created_at cannot be edited. Persistence uses the existing UUID-string identity
and ISO datetime conventions.

The only preparation transitions are:

```text
DRAFT -> READY_FOR_REVIEW -> APPROVED
```

Status changes require the explicit transition operation and the central domain
validator. Skipping, reversing, and self-transitions are rejected. There is no
reset/reopen operation in Task 2.1. Generic metadata updates cannot accept status.
Repository writes distinguish metadata changes from status changes and revalidate
identity and lifecycle rules before flushing; UnitOfWork owns commit/rollback.

Name and objective can be edited in every preparation state without changing
status. Explicit objective=null clears it; omitted fields retain their values.
An empty metadata update is a no-op. Non-empty metadata updates and successful
transitions refresh updated_at; rejected operations leave durable data unchanged.

APPROVED records the explicitly selected preparation state only. Task 2.1 has no
requirements/test-spec readiness evaluator, review evidence or approver identity;
it does not certify any future child content. Those contracts belong to later
Phase 2 tasks. No QA Run, execution status or PASS/FAIL outcome is implied.
Individual test FAIL must remain a per-test QA outcome, with remaining eligible
tests continuing under the future execution model.

## Application and HTTP

All campaign operations require a Project ID and validate that Project exists.
Reads/updates/transitions also check that the Campaign belongs to that Project.
There is no unscoped HTTP campaign lookup or ownership reassignment operation.

| HTTP operation | Application operation |
| --- | --- |
| POST /api/v1/projects/{project_id}/campaigns | create_campaign(project_id, name=..., objective=...) |
| GET /api/v1/projects/{project_id}/campaigns | list_project_campaigns(project_id, limit=50) |
| GET /api/v1/projects/{project_id}/campaigns/{campaign_id} | get_campaign(project_id, campaign_id) |
| PATCH /api/v1/projects/{project_id}/campaigns/{campaign_id} | update_campaign(project_id, campaign_id, name=..., objective=...) |
| POST /api/v1/projects/{project_id}/campaigns/{campaign_id}/transitions | transition_campaign(project_id, campaign_id, status=...) |

Create returns 201; other successful operations return 200. Example create body:

```json
{"name": "Booking regression", "objective": "Verify checkout behavior"}
```

Explicit transition body:

```json
{"status": "READY_FOR_REVIEW"}
```

Lists use the existing CollectionPage contract: items, total_returned and
truncated. Default limit is 50, valid range 1–200; SQL retrieves only limit+1
records. Order is newest created_at by UTC instant, then UUID ascending for ties.
The limit is never silently clamped and total_returned is not the database total.

Unknown/extra request fields are forbidden. Invalid UUIDs, invalid metadata and
limits return safe 422 envelopes. Missing Project or Campaign returns 404
PROJECT_NOT_FOUND or CAMPAIGN_NOT_FOUND. A mismatched Project/Campaign returns
409 PROJECT_CAMPAIGN_MISMATCH, following existing Task scoping conventions.
Illegal lifecycle changes return 409 CAMPAIGN_INVALID_TRANSITION. Transport
validation uses REQUEST_VALIDATION_ERROR; application validation uses INVALID_INPUT.
[Existing API contracts and errors](API.md) apply.

Existing host Basic/session authentication protects these routes; hosted unsafe
requests require the existing CSRF defense. Preparation never constructs models,
reads/mutates a target repository, runs commands or creates hidden Tasks/jobs.
Existing Task/ExecutionJob/workflow APIs and Phase 1 usage reads remain separate.

## Persistence and handoff

Alembic 0004 (parent 0003) adds only qa_campaigns: UUID PK, non-null Project FK,
bounded metadata, constrained preparation status and aware timestamps. The
project/created_at/id index supports project selection. Downgrade removes this
table and its campaigns, leaving existing Project/Task/evidence/job data intact.
It does not backfill campaigns or create Projects. The packaged migration and
host current-revision marker include 0004. No dependency is added.

Task 2.2 now attaches immutable specification sources and structured requirements
through the stable Campaign UUID and Project ownership; see
[Campaign requirements](REQUIREMENTS.md). Ingestion/extraction does not change
Campaign status. Task 2.4 adds [explicit human review, traceability and derived
readiness](CAMPAIGN_REVIEW.md) while preserving Campaign transitions. Task 2.3 adds [executor-neutral imported/generated test
specifications](TEST_SPECIFICATIONS.md), without approval/readiness or execution. Task 2.1 adds none of those child
models, ingestion, extraction, generation, readiness, traceability, execution,
source mutation or frontend redesign. Future changes to approval invalidation or
reverse transitions must be explicit contract changes rather than metadata
side effects.
