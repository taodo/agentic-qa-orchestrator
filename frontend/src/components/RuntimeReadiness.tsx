import { useCallback } from 'react';
import { getRuntimeStatus } from '../api/host';
import { useResource } from '../app/useResource';

export function RuntimeReadiness({ projectId }: { projectId: string }) {
  const status = useResource(useCallback(() => getRuntimeStatus(projectId), [projectId]));
  const data = !status.loading && !status.error ? status.data : undefined;
  return <section className="panel" aria-label="Project runtime readiness">
    <div className="panel-heading"><h2>Runtime readiness</h2><button type="button" disabled={status.loading} onClick={() => void status.reload()}>Refresh runtime</button></div>
    {status.loading && <p role="status">Checking this host…</p>}
    {status.error && <p role="status">Runtime status unavailable. Use local validate on the full-stack host; Run still checks configuration on the backend.</p>}
    {data && (!data.runtime_configured ? <>
      <p>Runtime: Not configured for this host</p>
      <p className="muted">This Project has persisted identity but no runtime on this host. {data.mode === 'local' ? 'Use local init and local validate, then restart the host with the configuration.' : 'Only Demo Calculator has the deterministic synthetic runtime in demo mode.'}</p>
    </> : data.mode !== 'local' ? <>
      <p>Runtime: Configured · Synthetic demo</p>
      <p className="muted">Deterministic synthetic demo only. No live AI, source mutation or real pytest.</p>
    </> : <>
      <p>Runtime: Configured for this host</p>
      <dl className="metadata"><div><dt>Model key</dt><dd>{data.model_ready ? 'Present (not verified with provider)' : 'Missing'}</dd></div><div><dt>Tests</dt><dd>{data.test_targets_configured ? 'Configured' : 'Not configured'}</dd></div></dl>
      <p className="muted">Run uses the trusted local workspace configured outside Project persistence.</p>
    </>)}
    <p className="muted">Status is a manual snapshot, not an execution guarantee. The backend remains authoritative.</p>
  </section>;
}
