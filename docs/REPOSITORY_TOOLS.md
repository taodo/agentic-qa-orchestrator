# Task 10 repository evidence

Researcher and Planner can request local repository evidence through an optional
application-level protocol. Agents reason; RepositoryToolPolicy authorizes reads;
RepositoryReadService executes them; immutable evidence records the result. Existing
ResearchGate, PlanGate and WorkflowEngine still decide progression.

## Configuration and role access

Enable `RealAgentRuntime(adapter, repository_tools=True)` for Researcher/Planner
and supply `repository_service=RepositoryReadService(RepositoryReadConfig(root))`
to WorkflowRunner (or AgentExecutor). The root is a caller-configured existing
directory, resolved once into a frozen configuration. Models cannot select it.
CompositeAgentRuntime delegates capability to each role's selected runtime.
The default runtime remains compatible with ordinary final-output calls.

Only Researcher and Planner have repository-result context fields or turn schemas.
Investigator tooling is deferred. Implementer keeps Task 9 authorized source
snapshots, structured proposals and MutationService. Reviewer and Test Analyzer
receive supplied evidence and have no repository capability. The read service
independently rejects every other role before inspecting a target.

## Typed protocol

`schemas/repository.py` defines frozen, extra-forbidden contracts:

- RepositoryToolRequest: UUID request_id and a literal-tagged arguments union.
  The tool property derives from arguments, avoiding conflicting tool identifiers.
- LIST_FILES arguments: tool, relative directory path, depth and limit.
- READ_FILE arguments: tool and relative file path.
- SEARCH_TEXT arguments: tool, literal query, relative directory prefix and limit.
- RepositoryToolResult: request_id, tool, SUCCESS/DENIED/ERROR, typed data or null,
  fixed error_code or null, and returned_bytes. Failures contain no partial data.
- RepositoryEvidence: artifact reference, explicit call_index, request and result.
- ResearchTurn/PlannerTurn: kind TOOL_REQUEST or FINAL_OUTPUT, tool_request and
  role-specific final_output. Both nullable payload fields are required, and exactly
  one must be non-null. FINAL_OUTPUT preserves ResearchOutput or PlannerOutput.

Arguments are explicit rather than prose; callers use `.` for the root directory.
LIST_FILES returns sorted repository-relative FILE/DIRECTORY entries, bounded size
metadata and a truncated flag. Depth zero lists immediate entries; each additional
depth descends one level. READ_FILE returns the entire UTF-8 text, exact byte size
and SHA-256, preserving CRLF and other original bytes through decoding. Oversized
files fail without partial content. SEARCH_TEXT uses Python literal matching,
returns one match per matching line, sorted by path then line, with bounded
snippets, snippet_truncated, full-file SHA-256, result truncation and skipped count.
Its path is a directory prefix; there is no regex, semantic search or shell.

The unchanged OpenAI Responses adapter sends tools=[], tool_choice="none" and
store=False. Turn intent is schema-native structured output, revalidated with
Pydantic, never SDK tool execution or free-form prose parsing. The root schema is
an object; nested argument unions use anyOf and nullable fields remain required,
consistent with [OpenAI structured-output guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

## Authorization and bounds

Paths must use `/` separators and remain relative to the configured root. Absolute,
UNC, drive, backslash, colon, empty/dot/dot-dot components, control characters,
trailing spaces/dots and Windows device aliases are rejected rather than normalized
into permission. Each path component is checked before resolving. Symlinks and
junctions are denied even when they point inside the root. Reads require regular
single-link files with explicitly allowed extensions; devices, sockets, directories,
hardlinks, NUL content and invalid UTF-8 are rejected.

Protected names are checked case-insensitively, including root ancestry. They cover
.git, .github, .env/.env.*, .ssh/.aws/.azure, .codex/.agents, virtual environments,
node_modules/site-packages, cache/build directories, bundled test dependencies,
runtime/interpreter directories, private-key names and key extensions, and names
containing credential or secret. Discovery skips protected/unsafe entries without
following them; direct requests return typed denials. This is conservative path
protection, not a detector for secrets embedded in otherwise allowed source text.

| Configuration | Default |
| --- | --- |
| max_file_bytes | 128 KiB |
| max_total_bytes_per_invocation | 512 KiB |
| max_list_results | 200 |
| max_search_results | 50 |
| max_tool_calls_per_agent_invocation | 8 |
| max_depth | 5 |
| max_scanned_entries per operation | 2,000 |
| max_search_bytes per search | 2 MiB |
| max_snippet_chars | 512 |
| allowed_extensions | .py .md .txt .toml .json .yaml .yml .ini .cfg .rst |

Total returned bytes count each successful data payload's serialized UTF-8 JSON,
including metadata and escaping. Search also bounds all bytes examined, including
invalid text, with at most one sentinel byte to detect growth beyond the limit.
Directory work is bounded before sorting. Exceeding scan bounds fails explicitly
instead of returning an apparently complete scan. Query length is schema-bounded
to 256 characters and policy-bounded by snippet length; blank/control queries fail.
Request schemas cap depth at 5 and result limits at 1,000 even if host limits are
larger. Host usage counters and limits never come from model arguments.

Ordered successful evidence is included in subsequent bounded user context. At most
eight results and 512 KiB of data are selected by default. The existing 60,000
serialized-character prompt ceiling is an additional, often tighter limit. Exceeding
it raises existing CONTEXT_LIMIT before a provider request; evidence is not silently
dropped or truncated to imply consideration.

## Execution, persistence and recovery

ControlledRepositoryExecution runs inside the existing AgentExecutor. One overall
AgentInvocation stays STARTED across explicit turns. Each provider turn has a
MODEL_TURN_STARTED event, followed by MODEL_TURN_COMPLETED with the validated turn
and safe metadata (model, response ID, usage, latency), or MODEL_TURN_FAILED
with a sanitized code. The start reservation records configured model and effort.
Existing bounded schema correction schedules a separate invocation with changed
instructions through ReliabilityService; it does not execute a malformed tool
request. SDK retries remain disabled. No transaction spans provider calls or
filesystem reads.

Each request gets REPOSITORY_TOOL_REQUESTED with an explicit index. The bounded
typed result is stored in a separate immutable REPOSITORY_EVIDENCE artifact and
atomically linked by REPOSITORY_TOOL_COMPLETED. Task/invocation IDs, request UUID,
operation, path/query, hashes, result, timestamp and order remain traceable. The
artifact has no model producer because deterministic code produced it. Final agent
artifacts remain separate. AGENT_COMPLETED links ordered repository evidence refs;
Researcher is instructed to cite those refs in its final findings. Gate evaluation
then proceeds normally; Planner's NEEDS_RESEARCH remains available and authoritative.

Only final role output permits overall COMPLETED. Canonical invocation metadata
describes the final turn; per-turn events retain earlier usage and response IDs for
accounting. Raw provider objects, chain-of-thought, credentials, authorization
headers and raw refusal text are never persisted.

A session marker binds the invocation to its base context hash and repository
configuration identity. Restart verifies unique contiguous turn indexes, completed
provider reservations, matching requests and artifact links. It reconstructs ordered
durable results without re-reading them. A durable final turn can finish canonical
persistence without another model call. A persisted result can feed the next call
only if that call was not already reserved. Any unresolved MODEL_TURN_STARTED,
configuration/context/model drift or inconsistent history requires explicit
reconciliation and stops without repeating the provider call.

If a read succeeded but its result transaction failed, the already-completed model
request can be reused and the unrecorded read performed again. This is safe because
reads do not mutate; it is not exactly-once execution or snapshot isolation. Two
explicit reads may see different source hashes, and each durable result remains
history. Existing reliability retries start separate invocations with fresh budgets
and reads. Concurrent runners for the same invocation are not supported.

## Errors and trust boundary

Budget exhaustion records typed DENIED evidence without executing another tool;
TOOL_CALL_BUDGET_EXHAUSTED and TOTAL_BYTES_EXCEEDED become existing WORKFLOW_ERROR
with STRUCTURAL disposition. Other denied requests (protected/escaping paths,
role/limit/query violations, reused request IDs) become POLICY_VIOLATION/TERMINAL.
Missing/unreadable/invalid-encoding/oversized files and scan failures become
TOOL_ERROR/STRUCTURAL. Each stops the invocation through existing failure routing;
there is no follow-up model call after a failed read. ReliabilityService owns any
application recovery decisions. Provider failures and schema correction retain
their existing taxonomy and budgets. No sleeps or parallel retry policy are added.

Source content is untrusted user-context evidence, never system instructions.
There is no injection regex filter. Deterministic read authorization, no native
provider tools, read-only capability and existing gates enforce authority even
when a file asks the model to read credentials, mutate files or declare DONE.

The caller must select a trusted repository and exclude sensitive source content.
Portable path checks have TOCTOU limits under hostile concurrent filesystem changes;
this is not an OS sandbox. There is no snapshot isolation, content secret scanning,
Git/network access, subprocess, model test execution, write API or generic registry.
No dependency was added and no paid smoke was run.

## Verification

Unit tests cover path/protected/link/type/encoding/byte/work limits, literal sorted
search, deterministic hashes, full-content semantics, frozen schemas and config,
native no-tools requests, role boundaries and unchanged content/modes/mtime with
write and subprocess APIs blocked. Symlink creation skips only when the platform
denies the required privilege.

Mocked real-agent integrations discover temporary calculator source without initial
source-body injection, read and cite it, allow Planner reads, preserve gates and
NEEDS_RESEARCH, exercise budget/path/refusal/schema failures, record drift, reopen
durable evidence, reuse safe results and stop unresolved provider reservations.
A regression runs real Task 9 mutation and local pytest with source snapshots and
a non-browsing Reviewer. Normal tests strip OPENAI_API_KEY and forbid live provider
transport; all model responses use the existing official-SDK MockTransport fixture.
