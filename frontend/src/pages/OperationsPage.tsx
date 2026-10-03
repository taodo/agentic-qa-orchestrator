import { Link, useSearchParams } from 'react-router-dom';
import { useOperations } from '../app/useOperations';
import { activityLabels, attentionLabels, errorLabels, taskStates, validUuid } from '../api/operations';
import { DateTime } from '../components/DateTime';
import { StatusBadge } from '../components/StatusBadge';
import { RuntimeReadiness } from '../components/RuntimeReadiness';
import { TruncationNotice } from '../components/Feedback';
import '../styles/operations.css';

export function OperationsPage() {
  const [params, setParams] = useSearchParams();
  const projectId = params.get('project_id') ?? '';
  const state = params.get('task_state') ?? '';
  const allowed = ['project_id', 'task_state', 'attention_only', 'active_only'];
  const invalid = [...params.keys()].some(key => !allowed.includes(key) || params.getAll(key).length > 1)
    || !!projectId && !validUuid(projectId) || !!state && !taskStates.includes(state as typeof taskStates[number])
    || ['attention_only', 'active_only'].some(key => params.has(key) && !['true', 'false'].includes(params.get(key)!));
  const query = new URLSearchParams();
  for (const key of allowed) if (params.get(key)) query.set(key, params.get(key)!);
  const resource = useOperations(query.toString(), projectId, !invalid);
  const data = resource.data;
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  }
  const cards = data && [
    ['Projects', data.summary.project_count], ['Tasks', data.summary.task_count], ['Running', data.summary.running_jobs],
    ['Queued', data.summary.queued_jobs], ['Blocked', data.summary.blocked_tasks], ['Reconciliation attention', data.summary.reconciliation_attention_tasks],
  ];
  return <>
    <header className="page-header"><p className="eyebrow">Workspace / Operations</p><h1>Operations</h1>
      <p className="muted">Read-only visibility over persisted evidence. Task state remains workflow truth.</p>
      <div className="actions"><button type="button" aria-disabled={resource.loading} disabled={invalid || resource.error?.code === 'HOST_AUTH_REQUIRED'} onClick={() => { if (!resource.loading) resource.refresh(); }}>Refresh</button>
        <span className="muted">{data ? <>Last updated <DateTime value={data.summary.generated_at} /></> : 'No snapshot loaded'} · Refreshes every 7 seconds while visible</span></div>
    </header>
    <section className="panel operations-filters" aria-label="Operations filters">
      <label>Project<select aria-label="Project" value={projectId} onChange={event => filter('project_id', event.target.value)}><option value="">All Projects</option>
        {projectId && !data?.projects.items.some(p => p.project_id === projectId) && <option value={projectId}>Selected Project</option>}
        {data?.projects.items.map(p => <option key={p.project_id} value={p.project_id}>{p.project_key}</option>)}</select></label>
      <label>Task state<select aria-label="Task state" value={state} onChange={event => filter('task_state', event.target.value)}><option value="">All states</option>
        {taskStates.map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="check"><input type="checkbox" checked={params.get('attention_only') === 'true'} onChange={event => filter('attention_only', event.target.checked ? 'true' : '')} />Attention only</label>
      <label className="check"><input type="checkbox" checked={params.get('active_only') === 'true'} onChange={event => filter('active_only', event.target.checked ? 'true' : '')} />Active only</label>
    </section>
    {invalid && <div role="alert" className="error"><p>Invalid Operations filters. No operational reads were requested.</p><button onClick={() => setParams({})}>Reset filters</button></div>}
    {resource.error && <p role="alert" className="error">{resource.error.message}</p>}
    {resource.loading && !data && !invalid && <p role="status">Loading operational snapshot…</p>}
    {data && <>
      <dl className="operations-cards" aria-label="System summary">{cards && cards.map(([label, value]) => <div className="panel" key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p className="muted">All Projects: {data.summary.terminal_tasks} terminal Tasks · Last {data.summary.recent_jobs_window} requested jobs: {data.summary.recent_failed_jobs} failed, {data.summary.recent_stopped_jobs} stopped. Summary cards are global; filters apply to Tasks and Project activity.</p>
      <section className="panel" aria-label="Operational Tasks"><div className="panel-heading"><h2>Tasks</h2><span className="muted">Newest Task update first · Up to 50</span></div>
        <p className="muted">Reconciliation signals are DB-only triage. Pending work may still be active. No signal does not mean CLEAR; open Task Detail for the full assessment and evidence. Job SUCCEEDED does not mean Task DONE.</p>
        {data.tasks.items.length ? <div className="operations-table" role="region" aria-label="Task summaries" tabIndex={0}><table><caption>Task states and execution lifecycles</caption><thead><tr><th scope="col">Task</th><th scope="col">Project</th><th scope="col">Task state</th><th scope="col">Execution job</th><th scope="col">Attention / signals</th><th scope="col">Updated</th></tr></thead><tbody>
          {data.tasks.items.map(t => <tr key={t.task_id}><td><Link to={`/tasks/${t.task_id}`}>{t.title}</Link></td><td><Link to={`/projects/${t.project_id}`}>{t.project_key}</Link></td><td><StatusBadge state={t.task_state} /></td>
            <td>{t.active_execution_status ?? t.latest_execution_status ?? 'No job'}{t.latest_execution_error_code && <small>{errorLabels[t.latest_execution_error_code]}</small>}</td>
            <td>{attentionLabels[t.attention]}<small>{t.reconciliation_attention ? 'Reconciliation attention' : 'No DB signal'}</small>{t.latest_error_code && <small>{errorLabels[t.latest_error_code]}</small>}</td><td><DateTime value={t.updated_at} /></td></tr>)}
        </tbody></table></div> : <p>No Tasks match these filters.</p>}<TruncationNotice truncated={data.tasks.truncated} />
      </section>
      <section className="panel" aria-label="Recent activity"><div className="panel-heading"><h2>Recent activity</h2><span className="muted">Newest first · Up to 50</span></div>
        {data.activity.items.length ? <ol className="operations-activity">{data.activity.items.map(item => <li key={`${item.kind}:${item.record_id}`}><Link to={`/tasks/${item.task_id}`}>{activityLabels[item.kind]}</Link>{item.task_state && <> · Task {item.task_state}</>}<small><DateTime value={item.timestamp} /> · Task <span className="mono">{item.task_id}</span></small></li>)}</ol> : <p>No activity recorded for this selection.</p>}
        <TruncationNotice truncated={data.activity.truncated} />
      </section>
      <section className="panel" aria-label="Project summaries"><h2>Projects</h2><div className="operations-table" role="region" aria-label="Project operational counts" tabIndex={0}><table><caption>Persisted Project summaries</caption><thead><tr><th scope="col">Project</th><th scope="col">Tasks</th><th scope="col">Active jobs</th><th scope="col">Blocked</th><th scope="col">Reconciliation attention</th><th scope="col">Latest activity</th></tr></thead><tbody>
        {data.projects.items.map(p => <tr key={p.project_id}><td><Link to={`/projects/${p.project_id}`}>{p.project_key}</Link><button className="operations-runtime-button" onClick={() => filter('project_id', p.project_id)}>Inspect runtime</button></td><td>{p.task_count}</td><td>{p.active_jobs}</td><td>{p.blocked_tasks}</td><td>{p.reconciliation_attention_tasks}</td><td><DateTime value={p.latest_activity_at} /></td></tr>)}
      </tbody></table></div>{!data.projects.items.length && <p>No Projects recorded.</p>}<TruncationNotice truncated={data.projects.truncated} />
        <p className="muted">Select a Project to inspect this host’s runtime readiness separately. Projects beyond this bounded list remain available through Projects navigation.</p></section>
    </>}
    {projectId && !invalid && <RuntimeReadiness key={projectId} projectId={projectId} />}
  </>;
}
