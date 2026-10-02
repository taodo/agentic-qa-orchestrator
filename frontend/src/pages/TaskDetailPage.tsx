import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getArtifacts, getDecisions, getErrors, getGates, getInvocations, getTask, getTestRuns, getTimeline, runTask, resumeTask } from '../api/tasks';
import { publicError, type ApiError } from '../api/client';
import { useResource } from '../app/useResource';
import { LoadingState, ErrorState } from '../components/Feedback';
import { DateTime } from '../components/DateTime';
import { StatusBadge } from '../components/StatusBadge';
import { Timeline } from '../components/Timeline';
import { EvidencePanel, type RefreshRegistry } from '../components/EvidencePanel';
import { ArtifactRecord, DecisionRecord, ErrorRecord, Fields, GateRecord, Id, InvocationRecord, TestRunRecord } from '../components/EvidenceRecords';

const sections = ['overview', 'timeline', 'artifacts', 'invocations', 'test-runs', 'errors', 'decisions', 'gates'] as const;
type Section = typeof sections[number];
const labels: Record<Section, string> = { overview: 'Overview', timeline: 'Timeline', artifacts: 'Artifacts', invocations: 'Invocations', 'test-runs': 'Test Runs', errors: 'Errors', decisions: 'Decisions', gates: 'Gates' };
function selectedSection(value: string | null): Section { return sections.includes(value as Section) ? value as Section : 'overview'; }

export function TaskDetailPage({ taskId }: { taskId: string }) {
  const [params] = useSearchParams();
  const selected = selectedSection(params.get('view'));
  const [opened, setOpened] = useState<Set<Section>>(() => new Set([selected]));
  useEffect(() => { setOpened(previous => previous.has(selected) ? previous : new Set([...previous, selected])); }, [selected]);
  const task = useResource(useCallback(() => getTask(taskId), [taskId]));
  const timeline = useResource(useCallback(() => getTimeline(taskId), [taskId]));
  const refreshers = useRef(new Map<string, () => Promise<void>>());
  const register: RefreshRegistry = useCallback((key, refresh) => {
    refreshers.current.set(key, refresh);
    return () => { refreshers.current.delete(key); };
  }, []);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const gate = useRef(false);
  const [busy, setBusy] = useState<'run' | 'resume'>();
  const [error, setError] = useState<ApiError>();
  async function act(action: 'run' | 'resume') {
    if (gate.current) return;
    gate.current = true; setBusy(action); setError(undefined);
    try { if (action === 'run') await runTask(taskId); else await resumeTask(taskId); }
    catch (failure) { if (mounted.current) setError(publicError(failure)); }
    finally {
      // Safe stops may still commit evidence. Only opened panels exist in the registry.
      if (mounted.current) {
        await Promise.all([task.reload(), timeline.reload(), ...Array.from(refreshers.current.values(), refresh => refresh())]);
        if (mounted.current) { gate.current = false; setBusy(undefined); }
      }
    }
  }
  const detail = task.data;
  function sectionUrl(section: Section) {
    const next = new URLSearchParams(params); next.set('view', section);
    return `?${next.toString()}`;
  }
  const panelProps = { taskId, register, busy: !!busy };
  return <>
    <header className="page-header"><p className="eyebrow">Workspace / Task inspector</p><h1>{detail?.title || 'Task Detail'}</h1>{detail && <div className="task-heading"><StatusBadge state={detail.state} /><Link to={`/projects/${detail.project_id}`}>View Project</Link><Id value={detail.id} /></div>}</header>
    {task.loading && <LoadingState>Loading Task…</LoadingState>}{task.error && <ErrorState error={task.error} retry={busy ? undefined : () => void task.reload()} />}
    {detail && <section className="panel execution-controls" aria-label="Execution controls"><div className="panel-heading"><h2>Execution</h2><div className="actions"><button type="button" disabled={!!busy || task.loading || !!task.error} onClick={() => void act('run')}>{detail.state === 'DONE' || detail.state === 'FAILED' ? 'Run (terminal check)' : 'Run'}</button>{detail.state === 'BLOCKED' && detail.resume_state && <button type="button" disabled={!!busy || task.loading || !!task.error} onClick={() => void act('resume')}>Resume</button>}</div></div>
      <p className="muted">Run waits for backend completion. Resume only continues the stored state; click Run separately afterward.</p>
      {detail.state === 'BLOCKED' && <p className="notice">This Task is blocked. Run does not resume it.</p>}
      {busy && <LoadingState>{busy === 'run' ? 'Running — waiting for the synchronous API request to complete…' : 'Resuming — recording the state transition…'}</LoadingState>}
      {error && <ErrorState error={error} />}
    </section>}
    <nav className="section-nav" aria-label="Task sections">{sections.map(section => <Link key={section} to={sectionUrl(section)} aria-current={selected === section ? 'page' : undefined}>{labels[section]}</Link>)}</nav>
    <div hidden={selected !== 'overview'}>{detail && <section className="panel" aria-label="Overview"><div className="panel-heading"><h2>Overview</h2><button type="button" disabled={!!busy || task.loading} onClick={() => void task.reload()}>Refresh Overview</button></div>
      <h3>Requirement</h3><p className="prose">{detail.requirement}</p>
      <Fields rows={[
        ['Project ID', <Link to={`/projects/${detail.project_id}`}><Id value={detail.project_id} /></Link>], ['Task ID', <Id value={detail.id} />],
        ['Created', <DateTime value={detail.created_at} />], ['Updated', <DateTime value={detail.updated_at} />], ['Completed', <DateTime value={detail.completed_at} />],
        ['Resume state', detail.resume_state], ['Current invocation ID', <Id value={detail.current_invocation_id} />],
        ['Implementation attempts', detail.implementation_attempt], ['Defect cycles', detail.defect_cycle], ['Review cycles', detail.review_cycle],
        ['Terminal reason', <span className="prose">{detail.terminal_reason ?? '—'}</span>],
      ]} />
    </section>}</div>
    <div hidden={selected !== 'timeline'}><section className="panel" aria-label="Timeline"><div className="panel-heading"><h2>Persisted timeline</h2><button type="button" disabled={!!busy || timeline.loading} onClick={() => void timeline.reload()}>Refresh timeline</button></div>
      {timeline.loading && <LoadingState>Loading Timeline…</LoadingState>}{timeline.error && <ErrorState error={timeline.error} retry={busy ? undefined : () => void timeline.reload()} />}{timeline.data && <Timeline page={timeline.data} />}
    </section></div>
    {opened.has('artifacts') && <div hidden={selected !== 'artifacts'}><EvidencePanel {...panelProps} panelKey="artifacts" name="Artifacts" load={getArtifacts} render={ArtifactRecord} /></div>}
    {opened.has('invocations') && <div hidden={selected !== 'invocations'}><EvidencePanel {...panelProps} panelKey="invocations" name="Invocations" load={getInvocations} render={InvocationRecord} /></div>}
    {opened.has('test-runs') && <div hidden={selected !== 'test-runs'}><EvidencePanel {...panelProps} panelKey="test-runs" name="Test Runs" load={getTestRuns} render={TestRunRecord} /></div>}
    {opened.has('errors') && <div hidden={selected !== 'errors'}><EvidencePanel {...panelProps} panelKey="errors" name="Errors" load={getErrors} render={ErrorRecord} /></div>}
    {opened.has('decisions') && <div hidden={selected !== 'decisions'}><EvidencePanel {...panelProps} panelKey="decisions" name="Decisions" load={getDecisions} render={DecisionRecord} /></div>}
    {opened.has('gates') && <div hidden={selected !== 'gates'}><EvidencePanel {...panelProps} panelKey="gates" name="Gates" load={getGates} render={GateRecord} /></div>}
  </>;
}
