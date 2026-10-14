"""Pure final arbitration. A receipt cannot transition state or execute a tool."""
from datetime import datetime, timezone
from hashlib import sha256
from qa_sentinel.agents.base import STATE_AGENTS
from .contracts import DecisionRequest, DecisionProposal, DecisionReceipt, Reason, Risk


def request_hash(request):
    return sha256(request.model_dump_json().encode("utf-8")).hexdigest()


def locked_reason(request, now):
    if now < request.created_at or now >= request.expires_at:
        return Reason.STALE
    if (request.risk != Risk.LOW or request.complexity == "COMPLEX" or
        not request.evidence_complete or request.evidence_conflict or request.untrusted_input or
        request.permission_required or request.policy_denied):
        return Reason.POLICY_LOCK
    return None


def arbitrate(request: DecisionRequest, proposal: DecisionProposal | None, *,
              failure: Reason | None = None, now=None):
    request = DecisionRequest.model_validate(request.model_dump())
    if proposal is not None:
        proposal = DecisionProposal.model_validate(proposal.model_dump())
    now = now or datetime.now(timezone.utc)
    reason = locked_reason(request, now) or failure
    if reason is None and proposal is None:
        reason = Reason.UNAVAILABLE
    if reason is None:
        if proposal.correlation_id != request.correlation_id or proposal.request_sha256 != request_hash(request):
            reason = Reason.CORRELATION_MISMATCH
        elif proposal.route not in request.allowed_routes:
            reason = Reason.DISALLOWED_ROUTE
        elif request.workflow_state is not None and proposal.route != STATE_AGENTS[request.workflow_state]:
            reason = Reason.DISALLOWED_ROUTE
        elif proposal.escalate and not request.escalation_allowed:
            reason = Reason.DISALLOWED_ESCALATION
        elif proposal.confidence < 0.8:
            reason = Reason.LOW_CONFIDENCE
        elif request.baseline_escalation and not proposal.escalate:
            # Advice cannot suppress an existing authoritative escalation.
            reason = Reason.POLICY_LOCK
    accepted = reason is None
    return DecisionReceipt(request=request, correlation_id=request.correlation_id, request_sha256=request_hash(request),
        route=proposal.route if accepted else request.baseline_route,
        escalate=proposal.escalate if accepted else request.baseline_escalation,
        accepted=accepted, reason=Reason.CLASSIFICATION if accepted else reason, proposal=proposal)
