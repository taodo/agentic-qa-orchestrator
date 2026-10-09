import type { RunTestResult } from '../api/runTypes';
import { getRunTestEvidence } from '../api/runs';
import { usePreparationAction } from '../app/usePreparationAction';
import { PreparationRow } from './PreparationRow';
import { StateBadge } from './StatusBadge';
import { DateTime } from './DateTime';
import { ErrorState, TruncationNotice } from './Feedback';

function EvidenceDetail({test,p,c,runId}:{test:RunTestResult;p:string;c:string;runId:string}) {
  const read=usePreparationAction<Awaited<ReturnType<typeof getRunTestEvidence>>>();
  const evidence=read.result??test.evidence;
  return <section aria-label={`Evidence for ${test.content.title}`}>
    <h5>Recorded execution evidence ({test.evidence_count})</h5>
    {!evidence.items.length && <p>No recorded execution evidence. Historical completed tests may predate evidence collection; missing evidence is not a QA result.</p>}
    <ol>{evidence.items.map(item=><li key={item.id} className="evidence-record">
      <strong>SYNTHETIC</strong><p className="prose">{item.summary}</p>
      <dl className="metadata"><div><dt>Source</dt><dd>{item.source}</dd></div><div><dt>Kind</dt><dd>{item.kind}</dd></div>
        <div><dt>Strategy</dt><dd>{item.payload.strategy}</dd></div><div><dt>Snapshot position</dt><dd>{item.payload.position}</dd></div>
        <div><dt>Observed synthetic outcome</dt><dd>{item.payload.outcome}</dd></div><div><dt>Recorded by host</dt><dd><DateTime value={item.recorded_at}/></dd></div>
        <div><dt>Evidence order</dt><dd>{item.sequence}</dd></div></dl>
      <details><summary>Evidence audit identity</summary><p>{item.id} · {item.schema_version}</p></details>
    </li>)}</ol>
    <TruncationNotice truncated={evidence.truncated}/>
    {evidence.truncated && <><p className="notice">Only the bounded evidence preview is shown.</p><button disabled={read.busy} onClick={()=>void read.run(()=>getRunTestEvidence(p,c,runId,test.id))}>{read.busy?'Loading evidence…':'View bounded test evidence'}</button></>}
    {read.error && <ErrorState error={read.error}/>}
  </section>;
}

export function RunResultsTable({items,p,c,runId}:{items:RunTestResult[];p:string;c:string;runId:string}) {
  return <div className="campaign-table-scroll" role="region" aria-label="Test Results table" tabIndex={0}>
    <table className="campaign-table"><caption>Persisted results from immutable Run Test snapshots</caption>
      <thead><tr>{['#','Test Case','Execution','QA Result','Evidence / details'].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{items.map(item=><PreparationRow key={item.id} id={`run-test-${item.id}`}>{({open,setOpen,detailId})=><>
        <td>{item.position}</td><th scope="row"><span className="record-key">{item.content.key}</span><h4>{item.position}. {item.content.title}</h4></th>
        <td><StateBadge status={item.execution_status}/></td><td><StateBadge status={item.qa_result}/></td>
        <td><span>{item.evidence_count} evidence record(s)</span><details id={detailId} open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>Result / evidence details</summary>
          <EvidenceDetail test={item} p={p} c={c} runId={runId}/>
          <p>Overall expected behavior: {item.content.overall_expected_result}</p><h5>Steps and expected behavior snapshot</h5><ol className="test-steps">{item.content.steps.map(step=><li key={step.index}>{step.action} — Expected: {step.expected}</li>)}</ol>
          <h5>Required evidence description (preparation, not collected evidence)</h5><ul>{item.content.required_evidence.map((value,i)=><li key={i}>{value}</li>)}</ul>
          <details><summary>Frozen test identity and provenance</summary><p>Original test: {item.original_test_specification_id}</p><p>Snapshot: {item.id}</p><p>Approval hash: {item.approval.content_hash}</p><p>Origin: {item.content.provenance.origin}</p><p>Linked Requirement snapshots: {item.linked_requirement_snapshot_ids.join(', ')}</p></details>
        </details></td>
      </>}</PreparationRow>)}</tbody>
    </table>
  </div>;
}
