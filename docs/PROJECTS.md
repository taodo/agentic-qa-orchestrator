# Task 11 Projects and workspace composition

QA Sentinel is the platform. Project is logical software identity; Task is one unit
of QA work owned by that Project. ProjectWorkspaceBinding is trusted runtime-only
configuration for one concrete local workspace. Agents reason, deterministic tools
act, evidence records reality, and existing orchestration/gates control progression.

## Logical identity and persistence

Project contains UUID id, unique key, name, description, created_at and updated_at.
Keys are 1–64 lowercase ASCII letters/digits separated by single hyphens, for example
`payment-api`. There is no whitespace/case normalization; invalid inputs fail.
ID, key and creation timestamp are immutable. Name, description and updated_at may
change explicitly; timestamps are not automatically advanced. ProjectRepository
supports add/get/get_by_key/list/save. Listing sorts by key then UUID. Save rejects
identity changes even through a copied Pydantic record. There is no delete API.

Every new Task requires an explicit Project UUID. Task ownership cannot be assigned
or saved to a different Project. SQLite requires a non-null indexed project_id FK.
Artifacts, invocations, events, errors and TestRuns remain task-scoped; Project
ownership is derived through Task rather than duplicated into each record.
Project rows have no workspace path, environment, credential or runtime-config blob.
Mappers remain explicit and repositories flush without committing; UnitOfWork owns
the transaction.

## Migration 0002

Revision `0002_projects.py` follows the unchanged accepted 0001. It creates projects,
adds task ownership, backfills existing Tasks and recreates tasks to enforce the
non-null FK and index. Empty legacy databases create no bootstrap Project.

Only databases with pre-existing Tasks receive migration-only Project
`00000000-0000-4000-8000-000000000011`, key `legacy-bootstrap`, with fixed timestamps.
All legacy Tasks retain their previous columns and linked history. This is not a
normal runtime default: domain/application creation still requires an explicit
owner. A developer must explicitly configure bindings for migrated ownership.

SQLite batch replacement of a table with incoming cyclic FKs requires disabling FK
checks on the dedicated migration connection before BEGIN. Alembic env does this
only for migration, checks all foreign keys inside the migration transaction before
commit, and restores enforcement afterward. Application connections retain FK
enforcement. Online migrations require an idle connection and exclusive database
access. Revision 0002 uses data inspection/reflection and is intended for online
SQLite upgrades, not generated offline SQL. Downgrade removes ownership/schema and
is a deliberate migration operation, not a Project deletion workflow.

## Runtime binding and registry

ProjectWorkspaceBinding is frozen and extra-forbidden, with project_id and an
existing canonical workspace_root. Its deterministic workspace_identity is SHA-256
over the Project UUID and canonical root. The identity is a drift detector, not
authorization by itself. Models cannot select or inspect a binding or registry.

ProjectRuntimeRegistry is explicitly constructed from bindings, with immutable
lookup storage, no singleton, IO execution, network or plugin container. resolve
requires a UUID and raises PROJECT_BINDING_MISSING when absent. Duplicate Project
IDs and equal/overlapping workspace roots are rejected. One Project maps to one
workspace in this phase. Use a single registry to compose all Projects in a process;
independently constructed registries cannot enforce uniqueness across each other.

```python
project = Project(key="calculator-a", name="Calculator A")
task = Task(project_id=project.id, title="Division", requirement="Add division")
with UnitOfWork(session_factory) as uow:
    uow.projects.add(project)
    uow.tasks.add(task)
    uow.commit()

binding = ProjectWorkspaceBinding(project_id=project.id, workspace_root=target_root)
registry = ProjectRuntimeRegistry([binding])
binding = registry.resolve(task.project_id)
reader = RepositoryReadService(RepositoryReadConfig(binding.workspace_root))
mutation = MutationService(MutationConfig(binding.workspace_root))
execution = TestExecutionService(session_factory, pytest_runner,
                                 workspace_binding=binding)
provider = PytestTestResultProvider(execution, approved_request)
runner = WorkflowRunner(session_factory, runtime, provider,
                        repository_service=reader, mutation_service=mutation,
                        workspace_binding=binding)
runner.run(task.id)
```

Configure pytest_runner's ExecutionConfig for the same root. Construction alone
does not authorize a Task; guards validate its persisted ownership before execution.

## Isolation and failure handling

ProjectWorkspaceGuard verifies persisted Task/Project ownership, explicit binding
Project UUID, canonical reader/mutation/test roots and the real provider's own
Project binding. WorkflowRunner checks before stages, context selection and resume,
including terminal-task return. AgentExecutor checks before provider description,
reservation or model calls. TestExecutionService checks independently before its
execution reservation and subprocess, protecting direct service callers as well.

PytestTestResultProvider exposes workspace_root and workspace_binding from its
service. Workspace-backed wrappers must forward both capabilities. Fake providers
declare no physical workspace and retain existing deterministic scenarios. Pure
supplied-context/fake workflows may omit a binding while still requiring a persisted
Project owner. Any configured reader, mutation service or real execution requires
an explicit binding. There is no path/title/name-based inference or default owner.

Mismatches stop before source snapshots, repository evidence, model calls, mutation
or test processes. Runner records a fixed WORKFLOW_ERROR code and raises existing
RunnerStoppedError, preserving state/counters for reconciliation; it never creates a
product FAIL TestRun or changes the graph. Direct AgentExecutor/execution-service
calls raise ProjectBindingError with a fixed safe code. They do not publish a
successful invocation or TestRun. Existing recovery policies/budgets are unchanged.

Codes distinguish PROJECT_BINDING_MISSING/MISMATCH, REPOSITORY_WORKSPACE_MISMATCH,
MUTATION_WORKSPACE_MISMATCH, TEST_WORKSPACE_MISMATCH, TEST_PROJECT_BINDING_MISMATCH,
ownership/unavailable-workspace failures and reconciliation. Missing registry lookup
raises directly because no Task is available for correlated failure persistence.

Accepted artifact selection still lists by task_id and validates gate/invocation
provenance. A foreign Task's current_invocation_id is explicitly rejected. Same role,
relative file name or higher attempt in another Project does not select its evidence.
Task 9 path/hash/rollback and Task 10 protected-path/read budgets remain unchanged.

## Durable identity and restart

Before first bound progression, PROJECT_WORKSPACE_BOUND records only the identity
digest in a task-scoped immutable event. No absolute root or Project ID is duplicated
in evidence. Subsequent execution compares the durable digest before continuation.
Changing root, Project, or removing the binding stops for reconciliation even if
all newly supplied services agree with one another. A missing root also stops safely.
Correct runtime recreation reuses Task 10 durable results/final turns and Task 9
canonical applied evidence under their existing reconciliation rules.

When adopting pre-Task-11 evidence without an anchor, guard verifies Task 10 session
configuration identities and Task 9 source-capture/reservation/application identities
against supplied services before binding. Legacy real-test reservations lack root
identity, so they require explicit reconciliation rather than guessed continuation.
Workspace-specific evidence is not automatically portable to another root. Logical
Project rows remain portable and can bind to a different root for new work in another
environment; already-bound Tasks require deliberate reconciliation before relocation.

## Trust, verification and remaining scope

Trusted host configuration selects prepared workspaces and services. Source and
pytest code remain trusted executable workspace content. Path hashes are not an OS
sandbox; concurrent runners/hostile writers, symlink races and shared resources used
by target test code remain outside these composition guarantees. Existing services'
path protections still apply. Arbitrary source can contain secrets: Project identity
and bindings do not add secret scanning or permit credentials/environment storage.

Tests cover keys, identity immutability, transaction rollback, repositories, registry,
FK/non-null/unique/index/schema integrity, legacy migration with cyclic linked rows,
schema rollback and restored FK enforcement on integrity failure,
and unchanged old data. Two temporary calculator Projects with identical relative
paths independently research, apply proposals, run actual local pytest and review.
Tests block reads/writes/Popen on wrong compositions in CREATED/IMPLEMENTING/TESTING,
verify task-scoped artifacts, reopen ownership and safe restart, and reject binding
drift without repeated model/read operations. Existing Task 9/10 fixtures use explicit
Projects/bindings; normal provider tests keep zero network/key requirements/API cost.

No dependency, prompt/model role, provider tool, state edge or reliability framework
was added. Multi-repository Projects, Application Services, Backend API, Frontend,
auth/organizations/RBAC, deletion, provisioning and workers remain future work.
Task 12 is not implemented; wait for review and explicit user approval.
