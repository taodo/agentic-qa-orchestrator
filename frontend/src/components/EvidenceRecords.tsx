import type { ReactNode } from 'react';
import type { ArtifactView, DecisionView, ErrorView, GateEvaluationView, InvocationView, TestRunView } from '../api/types';
import { DateTime } from './DateTime';
import { ErrorSeverity, GateResult, InvocationStatus, TestExecutionStatus, TestOutcome } from './EvidenceStatus';
import { JsonContent } from './JsonContent';

export function Id({ value }: { value: string | null }) { return <span className="mono">{value ?? '—'}</span>; }
export function Fields({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="metadata evidence-metadata">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? '—'}</dd></div>)}</dl>;
}
function References({ values }: { values: string[] }) {
  return values.length ? <ul className="reference-list">{values.map((id, index) => <li key={`${id}-${index}`}><Id value={id} /></li>)}</ul> : <>—</>;
}
export function ArtifactRecord(item: ArtifactView) {
  return <><h3 className="record-heading">{item.artifact_type}</h3><Fields rows={[
    ['Artifact ID', <Id value={item.id} />], ['Created', <DateTime value={item.created_at} />],
    ['Producer agent', item.producer_agent], ['Producer model', item.producer_model],
    ['Invocation ID', <Id value={item.invocation_id} />], ['Schema version', item.schema_version],
    ['Supersedes artifact ID', <Id value={item.supersedes_artifact_id} />],
  ]} /><h4>Content</h4><JsonContent value={item.content} /></>;
}
export function InvocationRecord(item: InvocationView) {
  return <><div className="record-heading"><h3>{item.agent}</h3><InvocationStatus value={item.status} /></div><Fields rows={[
    ['Invocation ID', <Id value={item.id} />], ['Attempt', item.attempt], ['Model', item.model],
    ['Reasoning effort', item.reasoning_effort], ['Started', <DateTime value={item.started_at} />],
    ['Finished', <DateTime value={item.finished_at} />], ['Error ID', <Id value={item.error_id} />],
  ]} /></>;
}
export function TestRunRecord(item: TestRunView) {
  return <><div className="record-heading"><h3>Test Run</h3><TestOutcome value={item.outcome} /><TestExecutionStatus value={item.execution_status} /></div><Fields rows={[
    ['Test Run ID', <Id value={item.id} />], ['Environment', item.environment],
    ['Started', <DateTime value={item.started_at} />], ['Finished', <DateTime value={item.finished_at} />],
    ['Passed', item.passed_count], ['Failed', item.failed_count], ['Skipped', item.skipped_count],
    ['Implementation artifact ID', <Id value={item.implementation_artifact_id} />], ['Report artifact ID', <Id value={item.report_artifact_id} />],
  ]} /></>;
}
export function ErrorRecord(item: ErrorView) {
  return <><div className="record-heading"><h3>{item.code}</h3><ErrorSeverity value={item.severity} /></div><p className="prose">{item.message}</p><Fields rows={[
    ['Error ID', <Id value={item.id} />], ['Error type', item.error_type], ['Owner', item.owner],
    ['Retryable', item.retryable ? 'Yes' : 'No'], ['Blocking', item.blocking ? 'Yes' : 'No'],
    ['Created', <DateTime value={item.created_at} />], ['Evidence references', <References values={item.evidence_refs} />],
    ['Source actor', item.source.actor ? <span className="prose">{item.source.actor.type} · {item.source.actor.id}</span> : null],
    ['Source invocation ID', <Id value={item.source.invocation_id} />], ['Source tool', item.source.tool],
  ]} /></>;
}
export function DecisionRecord(item: DecisionView) {
  return <><h3 className="record-heading">{item.decision_type}</h3><Fields rows={[
    ['Decision ID', <Id value={item.id} />], ['Decision source', item.decision_source], ['Reason code', item.reason_code],
    ['Reason details', <span className="prose">{item.reason_details}</span>], ['Evidence references', <References values={item.evidence_refs} />],
    ['Created', <DateTime value={item.created_at} />],
  ]} /></>;
}
export function GateRecord(item: GateEvaluationView) {
  return <><div className="record-heading"><h3>{item.gate_name}</h3><GateResult value={item.result} /></div><Fields rows={[
    ['Gate evaluation ID', <Id value={item.id} />], ['Evaluated', <DateTime value={item.evaluated_at} />],
  ]} /><h4>Checks</h4>{item.checks.length ? <ul className="gate-checks">{item.checks.map((check, index) => <li key={index}>
    <div className="record-heading"><strong className="prose">{check.check}</strong><GateResult value={check.result} /></div><p className="prose">{check.reason ?? 'No persisted reason.'}</p>
  </li>)}</ul> : <p>No persisted checks.</p>}
    <h4>Blocking reasons</h4>{item.blocking_reasons.length ? <ul>{item.blocking_reasons.map((reason, index) => <li className="prose" key={index}>{reason}</li>)}</ul> : <p>No persisted blocking reasons.</p>}</>;
}
