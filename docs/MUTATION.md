# Controlled implementation — Bootstrap Task 9

The real Implementer returns an ImplementationProposal through the existing
official Responses adapter. Deterministic application code reads and writes;
evidence records what happened; the orchestrator and existing gates control
progression. All requests retain `tools=[]`, `tool_choice="none"`, `store=False`,
native strict structured output, Pydantic revalidation, and zero SDK retries.
Mutation is ordinary application code, never a model function/tool. No dependency
or migration is added.

## Configuration and composition

RoleModelConfig.implementer defaults to `gpt-5.6-luna` with high reasoning effort.
All six roles can use RealAgentRuntime. CompositeAgentRuntime can retain fake roles;
fake Implementer keeps returning ImplementationOutput and does not activate mutation.
A real Implementer requires a separately configured MutationService; absence stops
before a provider request.

```python
mutation = MutationService(MutationConfig(workspace_root=prepared_target_root))
binding = ProjectWorkspaceBinding(project_id=task.project_id,
                                  workspace_root=prepared_target_root)
runtime = RealAgentRuntime(OpenAIModelAdapter(), RoleModelConfig())
runner = WorkflowRunner(session_factory, runtime, pytest_provider,
                        mutation_service=mutation, workspace_binding=binding)
```

Configure the deterministic pytest provider for the same target workspace. The
model cannot select roots, limits or commands. Concurrent runners/writers are
unsupported; use exclusive trusted access throughout implementation and testing.
Task 11 requires explicit persisted Project ownership and matching binding on the
runner/executor and real test service. See PROJECTS.md for composition and drift checks.

## Proposal versus canonical evidence

Frozen, extra-forbidden contracts in schemas/mutation.py define:

- SourceFileSnapshot: canonical relative path, SHA-256, full UTF-8 content, byte size.
- FileMutation: path, MODIFY or CREATE, expected_sha256, full content, reason.
- ImplementationProposal: status/summary, plan_steps, mutations,
  tests_added_or_modified, assumptions, known_issues and deviations.

MODIFY requires an existing regular text file and its exact supplied hash. CREATE
requires an absent authorized target and null expected_sha256. That nullable field
is required in structured output; null expresses absence of a precondition.
DELETE is outside the enum and rejected even on bypassed typed objects. There is
no diff parser, fuzzy patch, binary editing or implicit operation conversion.
BLOCKED/FAILED proposals cannot contain writes; zero-mutation reports remain valid.

The minimal new ArtifactType is IMPLEMENTATION_PROPOSAL. Allowed bounded proposals
are immutable separate evidence reserved before application. Rejected proposals
retain only digest, mutation count and fixed rejection code, avoiding arbitrary
rejected content. The existing IMPLEMENTATION artifact follows successful apply:
changed_files derive solely from actual applied facts; reported test paths are
intersected with those facts; commands_executed remains empty. Plan-step statuses
and deviations remain model reports checked by ImplementationGate, not correctness
proof. Rejection or rollback cannot produce canonical COMPLETED success evidence.
A nonwriting BLOCKED/FAILED report may have a canonical artifact with that status
and no changed files, subject to existing gate/stop semantics.

## Source selection and limits

Deterministic code validates the exact same-task accepted PLAN artifact, completed
Planner invocation and PASS gate on the actual transition/event. Every attempt
gets fresh current-byte snapshots outside a DB transaction. MODIFY authorization
is files_to_modify plus CODE_CHANGE step files. Legacy steps without kind load as
CODE_CHANGE and retain their original write scope. STATIC_REVIEW-only files do not
authorize writes; an independent files_to_modify entry or CODE_CHANGE step can still
authorize MODIFY. CREATE authorization remains files_to_create only. Both the prompt
projection and policy use the same declared modification-path calculation.

Source snapshot scope additionally includes STATIC_REVIEW files needed for
attestation. Visibility of those bytes is not write authorization. The complete
source/create union still receives the existing containment, protected-path,
case-alias and file-count checks, and all snapshots share the existing UTF-8,
per-file and aggregate byte limits. An absent source path also authorized for
CREATE has no snapshot; a later repair can explicitly MODIFY that existing path
with its fresh hash. Prior artifacts and investigation text cannot broaden scope.

Only selected existing source-scope files are read. Exact bytes are SHA-256 hashed
and strictly decoded as UTF-8 without normalization. NUL-containing/undecodable
content, special files, directories and hardlink aliases are rejected. Source is
user/context JSON separate from system instructions. Embedded instructions cannot
authorize operations. There is no discovery of unrelated files or expansion of refs.

| Limit | Default |
| --- | --- |
| Individual source | 128 KiB |
| Total source | 512 KiB |
| Authorized paths | 20 |
| Individual replacement | 256 KiB |
| Total replacement payload | 1 MiB |
| Mutation count | 20 |

MutationConfig exposes positive integer limits. Existing model ceilings of 60000
serialized input characters and bounded output tokens also apply and can reject
earlier than filesystem limits. Nothing is silently truncated. A resulting file
above the source limit requires explicit configuration resolution before a later
source snapshot.

## Paths, credentials and trust

Paths must be relative with `/`. Absolute, drive/UNC, backslash, colon/alternate
stream, control characters, empty/dot/dotdot components, trailing space/dot and
Windows device names are denied. Duplicate targets and case aliases are denied.
Targets must resolve inside the canonical root. All target symlinks/junctions,
including internal links, are denied and root identity is rechecked. Existing
parents are required: directory creation is not supported. CREATE refuses existing
paths even if they appeared after source capture.

Protected components include `.git`, `.github`, `.env`/`.env.*`, `.aws`, `.ssh`,
`.azure`, `.codex`, `.agents`, `.venv`/`venv`/`env`, node_modules, site-packages,
__pycache__, dependency caches, interpreter/runtime directories, credential/secret
names, private-key names and `.pem`/`.key`/`.p12`/`.pfx` files. The conservative exact
list is repository-owned in mutation/policy.py and cannot be changed by a model.
Host QA Sentinel and overlapping roots are disallowed by default. Explicit trusted
`allow_host_workspace=True` permits intentional host targeting, still subject to
accepted-plan authorization and protected paths. Tests never use this to mutate
host source: all writes are to temporary prepared workspaces.

Callers must exclude secret-bearing source from selection. Protected paths cover
obvious credentials; QA Sentinel cannot guarantee secret detection inside arbitrary
source text. No secret-scanning dependency is added. API keys, authorization headers,
raw provider requests/responses, raw refusals and hidden reasoning are not persisted.

## Apply and rollback

MutationPolicy validates the complete set: contract, paths, authorization,
count/size, encoding, file types, snapshot consistency and current hashes. A denied
set applies nothing. PolicyDecision is typed (allowed, reason_code, reason); model
prose cannot determine policy. MODIFY SHA mismatch records STALE_SOURCE and never
silently overwrites or asks the model again. CREATE conflicts preserve existing data.

MutationService holds originals in memory, stages every replacement in its existing
parent, flushes/fsyncs and rechecks the entire set before any target write. Each
target is checked again immediately before publication. MODIFY uses os.replace,
preserving its original mode where practical. CREATE uses os.link for atomic
exclusive publication without replacement, then removes the staging link. The
filesystem must support same-directory hardlinks; unsupported filesystems fail
safely with application evidence. CREATE uses platform tempfile mode. Models have
no permission/ownership controls. UTF-8 is written as exact bytes with no newline
translation; proposed LF/CRLF is preserved and rollback restores original bytes.

On later failure, earlier MODIFY files are restored in reverse order and CREATE
files are removed. Rollback verifies the applied hash before restoration to avoid
knowingly clobbering newer edits and continues restoring other files if one fails.
ApplicationResult records success, decision, actual path/operation/before/after
hashes/byte sizes on success and rollback NOT_NEEDED/SUCCEEDED/FAILED on failure.
An empty applied collection on failure is not proof that every target is unchanged
when rollback failed. Failed rollback records MUTATION_RECONCILIATION_REQUIRED when
persistence is available and requires explicit inspection. Cleanup is best effort and may leave `.qa-mutation-*`
staging files if cleanup itself fails.

The service calls no model, shell, Python executor, Git, pytest or workflow transition
and does not classify defects. Metadata is never evaluated as code. Target source
and conftest may execute later under the separate Task 6 pytest runner; the prepared
workspace is trusted, not an OS or network sandbox.

## Durable phases and reconciliation

ControlledImplementationExecution reuses AgentExecutor:

1. Validate accepted plan; commit STARTED and existing invocation counters.
2. Read fresh sources; commit IMPLEMENTATION_SOURCE_CAPTURED with plan/root identity
   and path/hash/size manifest, without duplicate original source bodies.
3. Call the model without a DB transaction and validate proposal/policy. A writing
   proposal must also pass the existing ImplementationGate before apply.
4. Commit immutable proposal and MUTATION_RESERVED with model metadata.
5. Apply files outside a DB transaction, without model calls.
6. Atomically commit canonical output, COMPLETED invocation, AGENT_COMPLETED and
   MUTATION_APPLIED facts. Existing gates/WorkflowEngine alone progress to TESTING.

Policy/application failure uses atomic error/invocation evidence. Forbidden actions
map to POLICY_VIOLATION/TERMINAL. Stale/create conflicts, missing/nontext/oversized
source, missing service and implementation-gate rejection map to
WORKFLOW_ERROR/STRUCTURAL. Application failure maps to TOOL_ERROR/STRUCTURAL.
Fixed messages discard raw filesystem exception text. Provider/schema taxonomy and
retries remain owned by existing ReliabilityService; no mutation retry loop or
threshold/budget copy is added.

Completion persistence failure after successful writes raises
MutationReconciliationRequired. STARTED and reservation remain durable; subsequent
runner execution refuses another model call or apply. Any unresolved STARTED attempt,
including process interruption or failed rollback, requires inspection. The runner
records fixed workflow-error evidence when possible. IMPLEMENTING has no BLOCKED
edge: its snapshot remains IMPLEMENTING and RunnerStoppedError exposes the stop.
Forbidden terminal requests may use the existing FAILED edge. No graph is changed.

There is no automatic resolution API or distributed filesystem/DB transaction.
A developer must inspect the invocation, reserved proposal, source manifest and
actual target hashes, then deliberately resolve workspace and workflow evidence
before resuming. Blindly clearing STARTED is unsafe. Process death may lose original
in-memory backups: durable hashes identify uncertainty but do not supply crash-proof
restoration. Multi-file crash atomicity and exactly-once distributed apply are out
of scope.

If completion committed but routing failed, restart selects only the canonical
artifact, verifies root/applied hashes and reuses output without provider call or
reapply. Verification also runs before testing. Workspace drift/configuration
mismatch stops for reconciliation rather than testing unrelated bytes.

Portable filesystem primitives leave unavoidable TOCTOU windows between checks and
publication. Repeated validation, atomic per-file publication and rollback provide
best-effort local semantics, not isolation from hostile concurrent writers or link
swaps. Exclusive trusted workspace access is required.

## Repair and verification

CODE_FIX/TEST_FIX uses unchanged Investigator routing, gates, defect-cycle budgets
and circuit checks. Each new Implementer receives accepted plan, current authorized
snapshots, previous implementation ref, selected InvestigationOutput and relevant
refs. After apply, actual pytest tests the changed target. Reviewer assesses
deterministic test evidence and ReviewGate alone permits DONE.

Tests use the actual SDK with existing mock transport, zero network and zero real
API cost. The mandatory add-only calculator scenario applies unguarded division,
runs pytest FAIL, obtains mocked real analysis/RCA, applies a second proposal with
the fresh hash and guard, runs pytest PASS, then obtains mocked real review and
gate-controlled DONE. Fixtures never switch source for repair. Tests cover CREATE,
whole-set rejection, stale conflicts, encoding/modes/limits, partial apply/rollback,
reservation/completion failure, restart/reopen, drift, retries, gates/budgets, zero
tools and literal command-like metadata. Task 6 deliberately does not classify logs
into failure fingerprints; the circuit test supplies a trusted explicit identity
through its existing provider capability. Task 10 adds separate read-only Researcher/
Planner evidence; Implementer snapshots remain unchanged. Task 11 adds Project binding.

## Task 22 read-only assessment

The application now detects reservations without canonical completion, explicit
reconciliation markers, failed rollback and applied hash/root drift before new
Run/Resume/enqueue. It reuses MutationService.verify_applied for bounded explicit
recorded files, after closing the read transaction. Later durable implementation
facts supersede earlier hashes for the same path; no proposal text proves writes.
Assessment never captures new source snapshots, applies, restores, deletes,
clears STARTED or fabricates completion. Preview has no mutation service or real
filesystem assessment. [Operator playbook](RECONCILIATION.md#operator-playbooks).
