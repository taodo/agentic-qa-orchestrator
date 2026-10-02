import { useCallback, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { getTask, getTimeline, runTask, resumeTask } from '../api/tasks';
import { publicError, type ApiError } from '../api/client';
import { useResource } from '../app/useResource';
import { LoadingState, ErrorState } from '../components/Feedback';
import { DateTime } from '../components/DateTime';
import { StatusBadge } from '../components/StatusBadge';
import { Timeline } from '../components/Timeline';
export function TaskDetailPage({ taskId }: { taskId: string }) {
  const task = useResource(useCallback(() => getTask(taskId), [taskId]));
  const timeline = useResource(useCallback(() => getTimeline(taskId), [taskId]));
  const gate = useRef(false);
  const [busy, setBusy] = useState<'run' | 'resume'>();
  const [error, setError] = useState<ApiError>();
  async function act(action: 'run' | 'resume') {
    if (gate.current) return;
    gate.current = true; setBusy(action); setError(undefined);
    try { if (action === 'run') await runTask(taskId); else await resumeTask(taskId); }
    catch (failure) { setError(publicError(failure)); }
    finally {
      // Safe stops may still commit evidence. Read durable state after either result.
      await Promise.all([task.reload(), timeline.reload()]);
      gate.current = false; setBusy(undefined);
    }
  }
  const detail = task.data;
  return <><header className="page-header"><p className="eyebrow">Workspace / Task</p><h1>{detail?.title || 'Task Detail'}</h1>{detail && <div className="task-heading"><StatusBadge state={detail.state} /><Link to={`/projects/${detail.project_id}`}>View Project</Link></div>}</header>
    {task.loading && <LoadingState>Loading Task…</LoadingState>}{task.error && <ErrorState error={task.error} retry={() => void task.reload()} />}
    {detail && <><section className="panel"><div className="panel-heading"><h2>Execution</h2><div className="actions"><button type="button" disabled={!!busy || task.loading || !!task.error} onClick={() => void act('run')}>{detail.state === 'DONE' || detail.state === 'FAILED' ? 'Run (terminal check)' : 'Run'}</button>{detail.state === 'BLOCKED' && detail.resume_state && <button type="button" disabled={!!busy || task.loading || !!task.error} onClick={() => void act('resume')}>Resume</button>}</div></div>
      <p className="muted">Run waits for backend completion. Resume only continues the stored state; click Run separately afterward.</p>
      {detail.state === 'BLOCKED' && <p className="notice">This Task is blocked. Run does not resume it.</p>}
      {busy && <LoadingState>{busy === 'run' ? 'Running — waiting for the synchronous API request to complete…' : 'Resuming — recording the state transition…'}</LoadingState>}
      {error && <ErrorState error={error} />}
      <h3>Requirement</h3><p className="prose">{detail.requirement}</p>
      <dl className="metadata"><div><dt>Project ID</dt><dd className="mono">{detail.project_id}</dd></div><div><dt>Task ID</dt><dd className="mono">{detail.id}</dd></div><div><dt>Created</dt><dd><DateTime value={detail.created_at} /></dd></div><div><dt>Updated</dt><dd><DateTime value={detail.updated_at} /></dd></div><div><dt>Completed</dt><dd><DateTime value={detail.completed_at} /></dd></div><div><dt>Resume state</dt><dd>{detail.resume_state || '—'}</dd></div><div><dt>Implementation attempts</dt><dd>{detail.implementation_attempt}</dd></div><div><dt>Defect cycles</dt><dd>{detail.defect_cycle}</dd></div><div><dt>Review cycles</dt><dd>{detail.review_cycle}</dd></div><div><dt>Terminal reason</dt><dd className="prose">{detail.terminal_reason || '—'}</dd></div></dl>
    </section></>}
    <section className="panel timeline-panel"><div className="panel-heading"><h2>Persisted timeline</h2><button type="button" disabled={!!busy || timeline.loading} onClick={() => void timeline.reload()}>Refresh timeline</button></div>
      {timeline.loading && <LoadingState>Loading Timeline…</LoadingState>}{timeline.error && <ErrorState error={timeline.error} retry={busy ? undefined : () => void timeline.reload()} />}{timeline.data && <Timeline page={timeline.data} />}
    </section>
  </>;
}
