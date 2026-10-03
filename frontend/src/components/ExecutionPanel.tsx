import type { ApiError } from '../api/client';
import type { CollectionPage, ExecutionJobStatus, ExecutionJobView } from '../api/types';
import { DateTime } from './DateTime';
import { Fields, Id } from './EvidenceRecords';
import { ErrorState, LoadingState, TruncationNotice } from './Feedback';

const labels: Record<ExecutionJobStatus, string> = {
  QUEUED: 'Execution queued', RUNNING: 'Execution running', SUCCEEDED: 'Execution request completed',
  STOPPED: 'Execution stopped', FAILED: 'Execution infrastructure failed',
};
const explanations: Record<ExecutionJobStatus, string> = {
  QUEUED: 'The host accepted this request. Run and Resume are unavailable while it is active.',
  RUNNING: 'The host is processing this request. Run and Resume are unavailable while it is active.',
  SUCCEEDED: 'The application returned normally. Inspect refreshed Task state and evidence; SUCCEEDED does not mean Task DONE or tests passed.',
  STOPPED: 'Execution stopped safely. Durable Task evidence may exist; inspect it before requesting more work.',
  FAILED: 'Job infrastructure failed. Inspect Task state and durable evidence; this status does not determine the Task outcome.',
};
function JobFields({ job }: { job: ExecutionJobView }) {
  return <Fields rows={[
    ['Request ID', <Id value={job.id} />], ['Status', job.status], ['Requested', <DateTime value={job.created_at} />],
    ['Started', <DateTime value={job.started_at} />], ['Finished', <DateTime value={job.finished_at} />], ['Safe error', job.safe_error_code ?? '—'],
  ]} />;
}
export function ExecutionPanel({ job, history, checking, creating, refreshing, warning, refresh, disabled }: {
  job?: ExecutionJobView; history?: CollectionPage<ExecutionJobView>; checking: boolean; creating: boolean;
  refreshing: boolean; warning?: ApiError; refresh: () => Promise<void>; disabled: boolean;
}) {
  return <section className="panel execution-panel" aria-label="Execution requests">
    <div className="panel-heading"><h2>Execution request</h2><button type="button" disabled={disabled || checking || creating || refreshing} onClick={() => void refresh()}>Refresh execution history</button></div>
    {checking && <LoadingState>Checking persisted execution history…</LoadingState>}
    {creating && <LoadingState>Requesting execution — sending once…</LoadingState>}
    {refreshing && <LoadingState>Refreshing Task state and opened evidence…</LoadingState>}
    {/* Only status text is live. Unchanged polling snapshots are not announced. */}
    <p role="status" aria-live="polite" aria-atomic="true">{job ? labels[job.status] : history ? 'No persisted execution requests yet.' : 'Execution history is not yet verified.'}</p>
    {job && <><p className="muted">{explanations[job.status]}</p><JobFields job={job} /></>}
    {warning && <ErrorState error={warning} />}
    {history && history.items.length > 0 && <details className="execution-history"><summary>Recent executions ({history.total_returned})</summary>
      <ol className="evidence-list" aria-label="Recent execution requests">{history.items.map(item => <li className="evidence-record" key={item.id}><JobFields job={item} /></li>)}</ol>
      <TruncationNotice truncated={history.truncated} />
    </details>}
  </section>;
}
