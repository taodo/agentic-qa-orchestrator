# Durable scoped Experience Store — Task 6.6

This is an internal, dormant QA Sentinel-owned relational foundation. No agent,
host route, browser or model is wired to it. Historical experience is advisory;
current observations and actual Run evidence retain authority. The fixture PoC
in `evaluation/experience_poc.py` is not imported by production code.

## Real scope and provenance

Project is an existing durable UUID entity. Exact scope is Project UUID + Campaign
UUID + Target UUID + SHA-256 of the immutable `TargetSnapshot` captured by a Run.
Composite ownership FKs use `qa_campaigns` and `targets_under_test`. Records without
a captured Target are not supported in this first foundation; no global fallback.
Live Target/Campaign changes do not rewrite historical scope. A caller must supply
its intended snapshot hash; no network/DOM lookup occurs or is implied.

Each record references 1–4 actual `qa_run_evidence` records, their owning Run/Test,
the stored Run snapshot hash, canonical immutable Run metadata/runtime digest,
canonical immutable Test/approval/plan digest and
canonical evidence digest. Source loading validates the registered evidence
contract against its completed Test snapshot and QA result, terminal Run status,
Target snapshot/scope and timestamp ordering. The owning completed Test may belong
to a failed Run: QA FAIL and system failure remain distinct. Source bodies, URLs,
Test prose, selectors, raw DOM, transcripts and credentials are not copied.

FKs restrict deletion of parents/sources; reference insert guards also match the
actual evidence owner. Retrieval reloads all bounded references, repeats validation
and compares hashes. This detects missing sources and changed Test/evidence/Run
bindings, including Run identity/runtime metadata changes without a snapshot-hash
update. SHA-256 is an integrity comparison, not a signature: a privileged DB
administrator who rewrites all sources and hashes can defeat it. The Run's stored
snapshot hash is bound, not recomputed through an unbounded whole-Run scan. This
proves linkage to persisted evidence, not the correctness of a historical lesson.

## Identity, lifecycle and content

Each UUID record is an immutable revision. Canonical UTC timestamps and sorted
JSON produce a digest over every stored semantic field except the digest itself.
A Campaign-scoped opaque UUID idempotency key replays identical intent; changed
scope/category/source selection/freshness with the same key conflicts. Different
keys intentionally create separate records. Writer reservation and a DB unique
constraint serialize competing creation requests using the existing SQLite UoW.

Only closed advisory categories and evidence-derived outcome/executor facts are
stored. Fixed advisory guidance is selected by category; there is no free-form
memory/command/selector/path/secret field. Extra fields are rejected, including
injection-looking prose. This is data minimization by construction, not a heuristic
secret scanner or a claim that arbitrary input can safely be sanitized.

Normal creation AND repository insertion permit only CANDIDATE. The closed future
states VALIDATED/PROMOTED/SUPERSEDED/RETIRED are represented for compatibility, but
there is no lifecycle transition, import-as-promoted, agent promotion or reviewer
API. Tests insert explicit state fixtures via SQL. All rows/reference rows are
append-only, including state. Task 6.7 must separately design reviewed append-only
lifecycle/revision/retirement semantics; this task exposes no transition loophole.
Expiry affects eligibility, not deletion. Migration downgrade refuses any retained
Experience history. Source/parent deletion is restricted; no silent cascade/purge.

## Bounded retrieval and freshness

Queries are typed, exact-scope and category-allowlisted. UUID ordering/keyset cursor
is deterministic. Inspect at most 32 records (+ one metadata-only overflow probe),
up to 4 sources each; return at most 5 candidates and at most 4096 serialized
advisory-context bytes. All exclusions use closed reason codes and scoped IDs only.
The returned cursor/scan-limit flag describes unexamined records honestly; nothing
claims they were considered. Result-count/byte omissions are explicit.

Only PROMOTED fixtures can be eligible. CANDIDATE and VALIDATED are not promoted
truth. Require created_at <= trusted service clock < expires_at, valid UTC aware
times, TTL at most 90 days, and each source age strictly less than the configured
freshness interval. A future source, invalid digest or missing reference rejects.
A terminal Run must have coherent creation/start/completion times and its evidence
must fall within those bounds. The trusted service clock is not supplied by queries.

Every projection is labeled UNVALIDATED_ADVISORY_CANDIDATE and contains only closed
historical facts, fixed guidance and immutable references. It is never evidence,
current truth, approval, execution permission or an executable locator. Current
observation validation belongs to 6.8; no old locator/path is even stored/projected
here. Consumers must validate relevance and contradictions against current evidence
before use, and must never concatenate arbitrary history into system instructions.

## Schema, isolation and deferred work

Migration 0019 adds Experience records and normalized provenance references with
ownership/source FKs, unique idempotency/source-order constraints, bounded payloads,
an exact-scope retrieval index and immutable-row triggers. Existing Run/Test/Evidence
schema/data are unchanged. Required host revision and packaged migrations advance;
existing databases require explicit operator migration, never automatic local-start
migration. No operator DB is opened by implementation or tests.

No HTTP/UI, promotion, automatic learning, production routing, Hermes/TypeSafe,
embedding/search infrastructure or agent integration. No measured relevance/quality
or token improvement is claimed. The next gates are independent review, approved
6.7 lifecycle/retention design, and 6.8 current-observation/relevance integration.
