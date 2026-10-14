# Hermes research and architecture decision — Task 6.5

Research date: 2026-10-14. Issue #102, parent #99. This is a source/documentation
review and Hermes-inspired offline PoC. **Hermes was not installed, imported or
executed. No production memory integration is enabled.**

Reviewed official repository main commit:
`d97007c32d6340f7ba79ac1dfb5773cc00846448` (committer timestamp 2026-10-14T00:34:31Z).
The commit is the reproducibility pin, not a claimed released/supported SDK version.
Website docs are observed on the research date and may evolve independently.
Pinned source hashes are in `benchmarks/hermes_research_sources_v1.json`.
Raw-host access returned429; read-only GitHub contents API supplied the pinned source.
No downloaded code was executed or installed.

## Verified official facts and limits

[Official repository](https://github.com/NousResearch/hermes-agent) and
[pinned packaging](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/pyproject.toml)
identify MIT licensing and Python >=3.11,<3.15. The documented installer currently
provisions Python3.14 and multiple tool/runtime dependencies. Native Windows and
WSL2 are documented options, not experimentally validated here. Packaging is broad,
with conditional version pins; compatibility with QA Sentinel's Python3.12/current
OpenAI stack was not installed/tested. Do not assume safe in-process dependency reuse.

[Memory docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
describe profile-scoped MEMORY.md (2200 chars) and USER.md (1375 chars), captured at
session start. Tool writes alter storage, not that frozen prompt snapshot. Writes
can add/change/remove entries, reject over-cap content and scan threat patterns.
An opt-in approval gate stages writes, but writes/background learning are allowed
by default. History and session search are distinct from those bounded files.
Deleting notes/skills is supported; it does not establish erasure from every session,
backup or external provider, nor immutable QA audit retention.

[Pinned memory store](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/tools/memory_tool_store.py)
uses a separate file lock, re-reads before mutation and atomic text writes, with Unix
flock and Windows msvcrt paths. Staged entry-target checks protect against changed
entries. This is local file safety, not multi-tenant QA ownership, immutable evidence
or business approval. Runtime race/crash behavior was not executed here.

[Profile docs](https://hermes-agent.nousresearch.com/docs/user-guide/profiles)
explicitly advise one agent per profile/home. Separate homes split configuration,
secrets and state; shared skills/resources remain configurable. Profile directories
are not an OS/security sandbox or Project/Campaign/Target authorization boundary.
File locks do not make sharing one semantic memory home appropriate for several roles.

[Pinned session search](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/tools/session_search_tool.py)
returns stored messages without LLM calls, with discovery/browse/scroll shapes and
lineage handling. The live memory docs describe SQLite/FTS5. README marketing still
mentions LLM summarization; for this pin, source/search docs support non-LLM retrieval.
None of this makes retrieved conversation claims verified evidence. Actual query
performance, completeness and storage/privacy behavior were not benchmarked.

[Skills docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
describe SKILL.md procedural knowledge with supporting resources and management tools.
Creation/edit/deletion and background learning can operate without human approval
by default. Opt-in write approval stages changes; content guard is a separate heuristic,
not an approval or QA evidence gate. A procedural skill may contain commands/scripts;
loading it into an agent can convey instructions, so never equate it with inert QA data.

[Pinned write approval](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/tools/write_approval.py)
provides file-backed pending records. The docs' approved writes are Hermes-user actions,
not QA Sentinel Reviewer/Task/Test approvals. Hermes add/patch/remove does not implement
our future CANDIDATE → VALIDATED → PROMOTED → SUPERSEDED/RETIRED evidence lifecycle.

[Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
supports provider/model and toolset configuration; inference requires the chosen
provider's credentials or a separately provisioned endpoint. Pure session retrieval
needs stored sessions, not inference. Native secret/config files, external memory
plugins, skills registries and gateways are additional trust/data surfaces. No one
provider credential, model, service price or zero-retention promise is assumed.

[Security docs](https://hermes-agent.nousresearch.com/docs/user-guide/security) and
[pinned SECURITY.md](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/SECURITY.md)
state that local terminal executes as the host user. File-tool guards do not contain
that terminal; isolated backends and tool/approval controls are distinct layers.
Injection scanners are heuristic. Credentials can be forwarded to declared skills;
auth configuration can adopt other CLI logins by default. Plugins are privileged
extensions, not untrusted-data sandboxes. These are documented risks, not newly
validated exploits or assertions that configured containment always fails.

## Security assessment for QA Sentinel

1. Mutable prose memory cannot become authoritative Test/Run/evidence truth.
2. Automatic writes and background skill learning conflict with explicit promotion;
   merely enabling notifications does not disable learning/writes.
3. Historical DOM/locators can be stale or cross-target; current bounded observation
   and exact immutable scope/provenance must win every time.
4. Prompt-scanning heuristics cannot safely replace typed projections/policy.
5. Profile and filesystem separation alone cannot enforce our authorization scopes.
6. Default local tools, plugins, credential adoption/forwarding and external recall
   make a fully powered agent unsuitable for an in-process read-only helper.
7. Raw transcripts/user profiles may contain personal or secret-bearing data; never
   copy them wholesale into QA prompts or an experience store. Retention/deletion,
   consent, export/backup and external-provider handling require independent design.
8. Locking/atomic writes do not supply audit history, test-approval provenance,
   durable promotion or fresh observation. Pin dependencies/updates and re-review.

No privileged agent, provider key, real operator DB/source/session, skills write,
external plugin or service was used in this task. Actual isolation, SDK compatibility,
privacy compliance and agent-quality benefits remain unverified.

## Potential benefit by role (hypotheses, not measured uplift)

| Role | Bounded historical hint | Required current validation | Future measurement |
|---|---|---|---|
| Researcher | Prior evidence completeness gaps | Current sources, scope, hash | Verified-context relevance/omission rate |
| Planner | Previous stage-separation pitfalls | Current accepted requirements/plan gates | Reviewer rejection and completeness |
| Implementer | Prior freshness/authorization caution | Current accepted inputs and deterministic policy | Invalid-proposal rejection; no new repair capability |
| Investigator | Previous failure classification | Current results/evidence overrides old diagnosis | RCA agreement and stale-hint rejection |
| Reviewer | Prior provenance mismatch pattern | Current immutable version/approval/evidence | Incorrect approval prevention, not auto-approval |

The PoC exercises these five closed lesson types only. It does not generate skills,
procedures, models, fixes or new authority; role quality/token savings are not measured.

## Architecture options / decision

| Option | Boundary and authority | Provenance/lifecycle/privacy | Resource/Windows burden | Complexity/testability | Verdict |
|---|---|---|---|---|---|
| A. Native Hermes constrained adapter | Read-only export/file boundary could be narrow; importing/running full agent is not | Must translate mutable notes/skills into separately verified QA hints; never native write promotion | Broad packages/provider/config; native Windows documented but untested | Private internals/updates and format coupling; boundary needs independent tests | NO-GO for powered in-process agent; conditional future read-only export only |
| B. Isolated Hermes service | Separate OS/container and deny execution/network/credential capabilities | Scoped protocol, verification, retention and human promotion still QA-owned | Additional service, monitoring, secrets/cost and Windows/container support | Stronger containment possible; substantial new attack/operations surface | DEFER; approval/security/ops review required |
| C. QA Sentinel-owned verified experience store | Orchestrator retrieves bounded advisory references; agents cannot promote/execute | Native Project/Campaign/Target/artifact hashes, explicit reviewer lifecycle and current-observation checks | Existing persistence patterns; no Hermes runtime/model prerequisite | Most direct deterministic testing, cost/privacy ownership; requires separately scoped domain/migration work | RECOMMENDED CONDITIONAL GO for a future design, not implementation here |
| D. Defer integration entirely | Existing workflow only | No new retained data or external trust | Lowest burden | No experience benefit; baseline stays measurable | GO now for external-runtime deferral |

**Decision:** prefer C's separately reviewed design; retain D for actual Hermes runtime.
A/B have no production GO. The prototype borrows bounded memory/procedural-recall ideas,
not Hermes API integration, native search, skills format execution or runtime behavior.

## PoC evidence and limitations

[Offline boundary report](PHASE_6_OFFLINE_EVALUATION.md) and
`benchmarks/experience_poc_v1_report.{json,md}` record 24 labeled scenarios: 7 hints,
17 rejections, all oracle matches, zero provider/execution/promotion calls. Synthetic
review/evidence seals and current observations are explicit fixtures. Untrusted notes
are never passed into advisory context. Symbolic locator/path checks demonstrate the
policy shape, not real browser inspection or anti-injection completeness.

This validates deterministic fixture selection/rejection, not actual Hermes behavior,
real provenance mapping, concurrent production persistence or improved reasoning.
No production store/table/API/config/learning lifecycle is implemented.

## Prerequisites before separately authorizing 6.6

- Phase 5 smoke passes; reconcile/re-review the branch stack and obtain Tao's merge approval.
- Approve the C domain/scope/retention/privacy design and exact immutable evidence/approval
  adapters; do not trust candidate self-claims, profile contents or memory as current evidence.
- Specify human Reviewer/operator promotion and retirement/supersession, idempotency,
  concurrency/restart reconciliation, deletion vs immutable audit, and failure semantics.
- Define trusted current-observation freshness and reference mapping, target versioning,
  no-locator-reuse without current validation, and bounded required-context handling.
- Establish real retrieval/agent-quality baseline and independent relevance labels; test
  poisoning/cross-scope/secret cases and compare token/context cost truthfully.
- Any Hermes runtime/dependency/service/credential use needs explicit independent approval,
  pinned compatibility/security evaluation and no shell/browser/skills authority.

**NOT MERGED. NOT DEPLOYED. NO TYPESAFE OR HERMES ACTIVATION. Task 6.6 not started.**
