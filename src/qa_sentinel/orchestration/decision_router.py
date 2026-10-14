"""Explicit opt-in advisory boundary. Not wired to active workflow/host composition."""
from collections import deque
from datetime import datetime, timezone
from pydantic import ValidationError
from qa_sentinel.decisions.contracts import DecisionRequest, DecisionProposal, DecisionFailure, Reason
from qa_sentinel.decisions.policy import arbitrate, locked_reason


class DecisionRouter:
    def __init__(self, provider=None, *, enabled=False, audit_limit=64):
        if type(enabled) is not bool or type(audit_limit) is not int or not 1 <= audit_limit <= 128:
            raise ValueError("Invalid bounded router configuration")
        self.enabled = enabled
        self.provider = provider
        self._audit = deque(maxlen=audit_limit)

    @property
    def audit(self):
        return tuple(self._audit)

    def decide(self, request):
        request = DecisionRequest.model_validate(request.model_dump())
        proposal = None
        reason = locked_reason(request, datetime.now(timezone.utc))
        if reason is None:
            if not self.enabled:
                reason = Reason.DISABLED
            elif self.provider is None:
                reason = Reason.UNAVAILABLE
            else:
                try:
                    candidate = self.provider.propose(request)
                    # Never trust model_construct/model_copy or unvalidated provider claims.
                    proposal = DecisionProposal.model_validate(candidate.model_dump())
                except DecisionFailure as error:
                    reason = error.reason
                except (ValidationError, AttributeError, TypeError, ValueError):
                    reason = Reason.INVALID_OUTPUT
                except Exception:
                    reason = Reason.PROVIDER_ERROR
        receipt = arbitrate(request, proposal, failure=reason)
        # Typed UUID/hash/enums/numeric usage only. No prompt, context, DOM or exceptions.
        self._audit.append(receipt)
        return receipt
