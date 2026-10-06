import type { OperationsSnapshot } from '../api/operations';
export const projectId = '00000000-0000-0000-0000-000000000001';
export const taskId = '00000000-0000-0000-0000-000000000002';
export const now = '2026-10-03T12:00:00Z';
const page = <T,>(items: T[]) => ({ items, total_returned: items.length, truncated: false });
export const snapshot: OperationsSnapshot = {
  summary: { project_count: 1, task_count: 1, running_jobs: 0, queued_jobs: 0, blocked_tasks: 0,
    terminal_tasks: 0, reconciliation_attention_tasks: 0, recent_failed_jobs: 0, recent_stopped_jobs: 0, recent_jobs_window: 50, generated_at: now },
  projects: page([{ project_id: projectId, project_key: 'demo-calculator', task_count: 1, active_jobs: 0, blocked_tasks: 0, reconciliation_attention_tasks: 0, latest_activity_at: now }]),
  tasks: page([{ task_id: taskId, project_id: projectId, project_key: 'demo-calculator', title: 'Calculator', task_state: 'REVIEWING',
    latest_execution_status: 'SUCCEEDED', active_execution_status: null, latest_execution_error_code: null, attention: 'NORMAL', reconciliation_attention: false, latest_error_code: null, updated_at: now }]),
  activity: page([{ record_id: taskId, task_id: taskId, project_id: projectId, kind: 'EXECUTION_SUCCEEDED', timestamp: now, task_state: null }]),
};
