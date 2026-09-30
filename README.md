# QA Sentinel — Agentic QA Orchestrator

Bootstrap Task 1: Python 3.12+ package skeleton, Pydantic v2 domain contracts,
agent output schemas, unit tests, and initial architecture documentation.

From this directory:

```shell
python -m pip install -e ".[test]"
python -m pytest
```

Runtime packages are intentionally empty. No orchestration, agents, execution,
persistence, prompts, or model APIs are implemented.
See docs/PHASE_1.md for contract assumptions and scope.
