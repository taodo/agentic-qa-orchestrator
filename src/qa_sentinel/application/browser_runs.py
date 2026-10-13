"""Seal manual plans in an already-approved preparation snapshot, without executing."""
from qa_sentinel.domain.browser_execution import BrowserPlanEnvelope, BrowserExecutionPlan
from qa_sentinel.domain.qa_run import QARun, QARunTest, PreparedQARun, snapshot_fingerprint
from qa_sentinel.execution.browser_policy import digest, run_test_snapshot_digest


def seal(prepared, plans, identity, policy, *, origin="MANUAL"):
    run=QARun.model_validate({**prepared.run.model_dump(),"executor_kind":"WEB_BROWSER","runtime_identity":identity})
    if set(plans)!={t.content.id for t in prepared.tests}: raise ValueError("Exact manual plan selection required")
    tests=[]
    for test in prepared.tests:
        plan=BrowserExecutionPlan.model_validate(plans[test.content.id].model_dump())
        envelope=BrowserPlanEnvelope(project_id=run.project_id,campaign_id=run.campaign_id,run_id=run.id,
            run_test_id=test.id,origin=origin,plan=plan,plan_hash=digest(plan),
            test_snapshot_hash=run_test_snapshot_digest(test),target_snapshot_hash=digest(run.target_snapshot))
        policy.validate_envelope(envelope,run,test)
        tests.append(QARunTest.model_validate({**test.model_dump(),"browser_plan":envelope}))
    run=QARun.model_validate({**run.model_dump(),"snapshot_hash":snapshot_fingerprint(run.campaign_snapshot,
        prepared.requirements,tests,run.snapshot_version,run.target_snapshot,run.runtime_identity)})
    return PreparedQARun(run=run,requirements=prepared.requirements,tests=tuple(tests))
