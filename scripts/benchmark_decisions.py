"""Offline current-routing baseline. No provider, tools, DB or workflow execution."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from qa_sentinel.agents.base import STATE_AGENTS
from qa_sentinel.domain.enums import TaskState
from qa_sentinel.orchestration.reliability_policy import InvestigatorContext, evaluate_investigator_escalation


def baseline(case):
    role = STATE_AGENTS[TaskState(case["state"])].value
    escalation = False
    if role == "INVESTIGATOR":
        context = InvestigatorContext(**{"confidence": 0.9, "attempt": 1, **case.get("investigator", {})})
        escalation = evaluate_investigator_escalation(context).escalate
    return role, escalation


def measure(path, mode="baseline"):
    if mode not in {"baseline", "offline-poc"}:
        raise ValueError("Unknown mode")
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ValueError("Corpus exceeds bound")
    corpus = json.loads(raw)
    cases = corpus["cases"]
    if not 1 <= len(cases) <= 100:
        raise ValueError("Case count exceeds bound")
    calls = fallbacks = 0
    correct = false = missed = violations = invalid = 0
    if mode == "offline-poc":
        from datetime import datetime, timedelta, timezone
        from qa_sentinel.decisions.contracts import DecisionRequest, DecisionProposal, DecisionFailure, Reason
        from qa_sentinel.decisions.policy import request_hash
        from qa_sentinel.orchestration.decision_router import DecisionRouter
        class Fixture:
            def propose(self, request):
                nonlocal calls
                calls += 1
                if scenario in {"provider-timeout", "provider-unavailable"}:
                    raise DecisionFailure(Reason.TIMEOUT if scenario == "provider-timeout" else Reason.UNAVAILABLE)
                return DecisionProposal(correlation_id=request.correlation_id, request_sha256=request_hash(request),
                    route=request.baseline_route, confidence=0.9, escalate=request.baseline_escalation,
                    reason_codes=("CLASSIFICATION",), provider="offline", configured_model="fixture",
                    reported_model="fixture-v1", provider_version="fixture-v1", latency_ms=0.0)
        router = DecisionRouter(Fixture(), enabled=True)

    timings = []
    for case in cases:
        started = perf_counter()
        route, escalation = baseline(case)
        if mode == "offline-poc":
            scenario = case["scenario"]
            now = datetime.now(timezone.utc)
            req = DecisionRequest(baseline_route=route, allowed_routes=(route,), workflow_state=case["state"],
                created_at=now, expires_at=now+timedelta(seconds=25), baseline_escalation=escalation,
                escalation_allowed=escalation, risk="ARCHITECTURE" if scenario == "architecture" else
                    "SECURITY" if scenario == "security" else "LOW",
                evidence_complete=scenario != "incomplete", permission_required=scenario == "approval-required",
                untrusted_input=scenario == "untrusted", policy_denied=scenario == "policy-denied")
            receipt = router.decide(req)
            route, escalation = receipt.route.value, receipt.escalate
            fallbacks += not receipt.accepted

        timings.append((perf_counter() - started) * 1000)
        violations += route != STATE_AGENTS[TaskState(case["state"])].value
        invalid += not isinstance(route, str) or type(escalation) is not bool
        correct += route == case["expected_route"]
        false += escalation and not case["expected_escalation"]
        missed += not escalation and case["expected_escalation"]
    timings.sort()
    return dict(mode=mode, version=corpus["version"], corpus_sha256=hashlib.sha256(raw).hexdigest(),
        samples=len(cases), route_correct=correct, route_accuracy=correct/len(cases),
        false_escalation=false, missed_escalation=missed, policy_violations=violations,
        invalid_output=invalid, fallback=fallbacks, provider_requests=calls, external_requests=0, provider_cost_usd=None,
        latency_ms_p50=timings[len(timings)//2], latency_ms_p95=timings[min(len(timings)-1, int(len(timings)*0.95))],
        scope="Existing stage-role mapping and Investigator escalation only; no LLM quality measurement",
        live_provider="LIVE NOT VERIFIED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="benchmarks/decision_routing_v1.json")
    parser.add_argument("--mode", choices=["baseline", "offline-poc"], default="baseline")
    args = parser.parse_args()
    print(json.dumps(measure(args.corpus, args.mode), indent=2))
