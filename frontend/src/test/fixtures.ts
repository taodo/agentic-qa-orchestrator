import type { CollectionPage, ExecutionJobStatus, ExecutionJobView, ProjectView, TaskDetail, TimelineEntry } from '../api/types';
export const project: ProjectView = { id: 'project-a', key: 'calculator-a', name: 'Calculator A', description: 'Arithmetic service', created_at: '2026-10-01T12:00:00+07:00', updated_at: '2026-10-02T05:00:00Z' };
export const task: TaskDetail = { id: 'task-a', project_id: project.id, title: 'Add division', requirement: 'Implement division with a zero divisor guard.', state: 'CREATED', created_at: project.created_at, updated_at: project.updated_at, completed_at: null, resume_state: null, current_invocation_id: null, implementation_attempt: 1, defect_cycle: 2, review_cycle: 3, terminal_reason: null };
export const page = <T,>(items: T[], truncated = false): CollectionPage<T> => ({ items, total_returned: items.length, truncated });
export function execution(status: ExecutionJobStatus = 'QUEUED', changes: Partial<ExecutionJobView> = {}): ExecutionJobView {
  return { id: 'job-a', task_id: task.id, project_id: project.id, status, created_at: '2026-10-02T05:00:00Z',
    started_at: status === 'QUEUED' ? null : '2026-10-02T05:00:01Z',
    finished_at: status === 'QUEUED' || status === 'RUNNING' ? null : '2026-10-02T05:00:02Z',
    safe_error_code: status === 'STOPPED' ? 'RUNTIME_STOPPED' : status === 'FAILED' ? 'EXECUTION_FAILED' : null, ...changes };
}
export const event = (id: string, type: string, index = 1): TimelineEntry => ({ index, insertion_order: index, timestamp: '2026-10-02T05:00:00Z', timestamp_tied: false, event_id: id, task_id: task.id, category: 'EVENT', event_type: type, summary: type, actor: { type: 'ORCHESTRATOR', id: 'qa-sentinel' }, correlation: { artifact_id: null, invocation_id: null, test_run_id: null, decision_id: null }, details: { to_state: 'RESEARCHING' } });
export function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
export function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
