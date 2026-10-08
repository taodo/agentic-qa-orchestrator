"""synthetic-position-v1: pure fixture outcomes, never target validation."""
from qa_sentinel.domain.qa_run import QARunTest, QAResult


class SyntheticRunExecutor:
    def evaluate(self, snapshot: QARunTest) -> QAResult:
        # Consume/revalidate the persisted content and receipt. Position belongs to
        # that immutable snapshot, not to a live Campaign or semantic title rule.
        snapshot = QARunTest.model_validate(snapshot.model_dump())
        return QAResult.PASS if snapshot.position % 2 else QAResult.FAIL
