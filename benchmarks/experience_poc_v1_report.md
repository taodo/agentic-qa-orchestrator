# Hermes-inspired offline experience fixture PoC

Actual Hermes integration: NOT RUN. No production persistence, execution or promotion.

Fixture SHA-256: `37ea005c8f0bddd4f2e8759fb8eee9af3df9c7bafb6f44706a7f6c524ecbdd4d`

| Scenario | Hints | Context bytes | Oracle match | Rejection reasons |
|---|---:|---:|---|---|
| role-researcher | 1 | 326 | True | none |
| role-planner | 1 | 336 | True | none |
| role-implementer | 1 | 352 | True | none |
| role-investigator | 1 | 353 | True | none |
| role-reviewer | 1 | 347 | True | none |
| stale-locator | 0 | 2 | True | STALE_LOCATOR |
| cross-target | 0 | 2 | True | SCOPE_MISMATCH |
| cross-campaign | 0 | 2 | True | SCOPE_MISMATCH |
| cross-project | 0 | 2 | True | SCOPE_MISMATCH |
| target-version | 0 | 2 | True | SCOPE_MISMATCH |
| missing-provenance | 0 | 2 | True | INVALID_EVIDENCE_PROVENANCE |
| wrong-provenance | 0 | 2 | True | INVALID_EVIDENCE_PROVENANCE |
| unreviewed | 0 | 2 | True | INVALID_REVIEW_PROVENANCE |
| expired | 0 | 2 | True | STALE |
| candidate | 0 | 2 | True | NOT_PROMOTED |
| validated | 0 | 2 | True | NOT_PROMOTED |
| superseded | 0 | 2 | True | NOT_PROMOTED |
| retired | 0 | 2 | True | NOT_PROMOTED |
| current-overrides | 0 | 2 | True | CURRENT_EVIDENCE_OVERRIDES |
| old-observation | 0 | 2 | True | STALE_OBSERVATION |
| injection-is-inert | 1 | 326 | True | none |
| context-bound | 0 | 2 | True | CONTEXT_BOUND |
| current-locator-reference | 1 | 326 | True | none |
| stale-path | 0 | 2 | True | STALE_PATH |
