import { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useCampaign } from './CampaignDetailPage';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { createRun, getRunResults, listRuns, listRunRequirements, runsPath, startRun } from '../api/runs';
import type { QARun } from '../api/runTypes';
import { RunResultsTable } from '../components/RunResultsTable';
import { DateTime } from '../components/DateTime';
import { ErrorState, EmptyState, LoadingState, TruncationNotice } from '../components/Feedback';
import { StateBadge } from '../components/StatusBadge';
import { SectionHeader } from '../components/WorkspaceUI';
import { CampaignReadiness } from '../components/CampaignReadiness';

function SyntheticNotice() { return <aside className="notice synthetic-notice"><strong>Synthetic execution</strong><p>No external target is tested in this mode.</p><p>Deterministic demo fixture: odd snapshot positions PASS, even positions FAIL. Results demonstrate lifecycle behavior, not target application correctness.</p></aside>; }
function RunSummary({ run }: { run: QARun }) { return <dl className="metadata"><div><dt>Execution status</dt><dd><StateBadge status={run.execution_status} /></dd></div><div><dt>QA outcome</dt><dd><StateBadge status={run.qa_outcome} /></dd></div>
  <div><dt>Requirement count</dt><dd>{run.requirement_count}</dd></div><div><dt>Test count</dt><dd>{run.test_count}</dd></div><div><dt>Created</dt><dd><DateTime value={run.created_at} /></dd></div><div><dt>Started</dt><dd><DateTime value={run.started_at} /></dd></div><div><dt>Completed</dt><dd><DateTime value={run.completed_at} /></dd></div><div><dt>Note</dt><dd>{run.note ?? 'No note'}</dd></div></dl>; }

export function CampaignRunsPage() {
  const { projectId:p, campaignId:c, base, readiness } = useCampaign();
  const runs = useResource(useCallback(() => listRuns(p,c),[p,c]));
  return <><SectionHeader title="Runs" /><SyntheticNotice /><div className="panel-heading"><h3>Create QA Run</h3><button disabled={readiness.loading} onClick={() => void readiness.reload()}>Refresh readiness</button></div>
    {readiness.loading ? <LoadingState>Loading readiness…</LoadingState> : readiness.error ? <ErrorState error={readiness.error} retry={() => void readiness.reload()} /> : readiness.data &&
      (readiness.data.status === 'READY' ? <CreateRunForm p={p} c={c} /> : <><p>Campaign is NOT_READY. Resolve preparation blockers before creating a Run.</p><Link to={`${base}/readiness`}>Inspect Readiness</Link><CampaignReadiness value={readiness.data} base={base} /></>)}
    <section className="panel"><div className="panel-heading"><h3>Saved Runs</h3><button disabled={runs.loading} onClick={() => void runs.reload()}>Refresh Runs</button></div>
      {runs.loading ? <LoadingState>Loading Runs…</LoadingState> : runs.error ? <ErrorState error={runs.error} retry={() => void runs.reload()} /> : runs.data && <>
        {!runs.data.items.length ? <EmptyState>No QA Runs yet.</EmptyState> : <ul className="preparation-records">{runs.data.items.map(run => <li key={run.id} className="evidence-record run-record"><Link className="record-title" to={runsPath(p,c,run.id)}>RUN-{String(run.run_number).padStart(3,'0')}</Link><p className="mono muted technical-id">{run.id}</p><RunSummary run={run} /><p>Snapshot hash: <code title={run.snapshot_hash}>{run.snapshot_hash.slice(0,16)}…</code></p></li>)}</ul>}
        <TruncationNotice truncated={runs.data.truncated} /></>}
    </section></>;
}

function CreateRunForm({ p,c }: { p:string;c:string }) {
  const navigate = useNavigate();
  const action = usePreparationAction<QARun>();
  const [intent,setIntent] = useState<{ idempotency_key: string; note?: string }>();
  const [note,setNote] = useState('');
  const authFailed = action.error?.code === 'HOST_AUTH_REQUIRED';
  return <form className="panel create-run-form" onSubmit={event => { event.preventDefault(); if (authFailed) return; void action.run(() => {
    const body = intent ?? {idempotency_key:crypto.randomUUID(), ...(note ? {note} : {})};
    setIntent(body);
    return createRun(p,c,body);
  }, async run => { navigate(runsPath(p,c,run.id)); }); }}>
    <p>Capture approved preparation without starting execution. A new request creates a separate Run.</p>
    <label htmlFor="run-note">Run note (optional)</label><textarea id="run-note" maxLength={1000} value={note} disabled={action.busy || !!intent} onChange={e => setNote(e.target.value)} />
    <button disabled={action.busy || authFailed} type="submit">{action.busy ? 'Creating QA Run…' : intent ? 'Retry Create QA Run' : 'Create QA Run'}</button>
    {action.error && <ErrorState error={action.error} />}{action.error && intent && <><p>The previous request keeps its key and note for an explicit retry. It is never retried automatically.</p><button type="button" disabled={action.busy || authFailed} onClick={() => { setIntent(undefined); setNote(''); }}>New create request</button></>}
  </form>;
}

export function CampaignRunDetailPage() {
  const { runId = '' } = useParams();
  return <RunDetail key={runId} runId={runId} />;
}
function RunDetail({runId}:{runId:string}) {
  const { projectId:p, campaignId:c, base } = useCampaign();
  const [reqPosition,setReqPosition] = useState(0), [testPosition,setTestPosition] = useState(0);
  const results = useResource(useCallback(() => getRunResults(p,c,runId,testPosition),[p,c,runId,testPosition]));
  const run = {...results,data:results.data?.run};
  const tests = {...results,data:results.data?.tests};
  const reqs = useResource(useCallback(() => listRunRequirements(p,c,runId,reqPosition),[p,c,runId,reqPosition]));
  const action = usePreparationAction<QARun>();
  async function refresh() { await results.reload(); }
  return <><Link to={`${base}/runs`}>← Runs</Link><SectionHeader title="QA Run detail" /><SyntheticNotice />
    <p>This Run uses the immutable preparation snapshot captured when the Run was created. Later Campaign changes do not alter this Run.</p>
    <button disabled={run.loading || action.busy} onClick={() => void refresh()}>Refresh Run and results</button>
    {action.error && <ErrorState error={action.error} />}
    {run.loading ? <LoadingState>Loading Run…</LoadingState> : run.error ? <ErrorState error={run.error} retry={() => void refresh()} /> : run.data && <section className="panel run-summary"><h3>RUN-{String(run.data.run_number).padStart(3,'0')}</h3><p className="mono muted technical-id">{run.data.id}</p><RunSummary run={run.data} />
      {results.data && <dl className="metadata" aria-label="Run result totals">{Object.entries({Total:results.data.summary.total,Completed:results.data.summary.completed,Passed:results.data.summary.passed,Failed:results.data.summary.failed,Skipped:results.data.summary.skipped,'Not evaluated':results.data.summary.not_evaluated,Remaining:results.data.summary.remaining}).map(([label,count])=><div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>}
      <p>Snapshot hash: <code>{run.data.snapshot_hash}</code></p><p>Readiness at creation: {run.data.readiness_at_creation.status}</p><p>Captured Campaign: {run.data.campaign_snapshot.name}</p>
      {run.data.execution_error_code && <p role="alert">{run.data.execution_error_code}: Synthetic execution could not complete. Earlier completed QA results and evidence remain saved. Interrupted and unstarted tests are not evaluated; this is an execution-system failure, not a product assertion failure.</p>}
      {run.data.execution_status === 'CREATED' && <button className="button--primary" disabled={action.busy || action.error?.code === 'HOST_AUTH_REQUIRED'} onClick={() => void action.run(async () => {
        try { return await startRun(p,c,runId); } catch (error) { await refresh(); throw error; }
      }, async () => { await refresh(); })}>{action.busy ? 'Running synthetic execution…' : 'Start Synthetic Run'}</button>}
      {action.busy && <p role="status">Results refresh when synchronous execution completes.</p>}
      {run.data.execution_status === 'RUNNING' && <p>Execution is RUNNING. Refresh to inspect saved progress. Restart/resume is unavailable.</p>}
    </section>}
    <section className="panel campaign-section"><h3>Test Results</h3>{tests.loading ? <LoadingState>Loading Test snapshot…</LoadingState> : tests.error ? <ErrorState error={tests.error} retry={() => void tests.reload()} /> : tests.data && <>
      {!tests.data.items.length && <EmptyState>No Test snapshots on this page.</EmptyState>}
      {tests.data.items.length>0 && <RunResultsTable items={tests.data.items} p={p} c={c} runId={runId}/>}
      <TruncationNotice truncated={tests.data.truncated} />{tests.data.truncated && <button onClick={() => setTestPosition(tests.data!.items.at(-1)!.position)}>Next Test snapshot page</button>}{testPosition > 0 && <button onClick={() => setTestPosition(0)}>First Test snapshot page</button>}
    </>}</section>
    <section className="panel campaign-section"><h3>Requirement snapshot</h3>{reqs.loading ? <LoadingState>Loading Requirement snapshot…</LoadingState> : reqs.error ? <ErrorState error={reqs.error} retry={() => void reqs.reload()} /> : reqs.data && <>
      {!reqs.data.items.length && <EmptyState>No Requirement snapshots on this page.</EmptyState>}
      {reqs.data.items.map(item => <article key={item.id} className="evidence-record"><h4>{item.content.title}</h4><p>{item.content.logical_key}</p><p className="prose">{item.content.description}</p><ul>{item.content.acceptance_criteria.map(ac => <li key={ac.key}>{ac.key}: {ac.text}</li>)}</ul>
        <details><summary>Frozen source and approval evidence</summary><p>Original Requirement: {item.original_requirement_id}</p><p>Snapshot identity: {item.id}</p><p>Approval hash: {item.approval.content_hash}</p>{item.content.source_references.map((ref,i) => <blockquote key={i}>Source {ref.source_id}, lines {ref.start_line}–{ref.end_line}: {ref.excerpt}</blockquote>)}</details></article>)}
      <TruncationNotice truncated={reqs.data.truncated} />{reqs.data.truncated && <button onClick={() => setReqPosition(reqs.data!.items.at(-1)!.position)}>Next Requirement snapshot page</button>}{reqPosition > 0 && <button onClick={() => setReqPosition(0)}>First Requirement snapshot page</button>}
    </>}</section>
  </>;
}
