import { ApiError, request } from './client';
import type { CollectionPage, ExecutionJobError, ExecutionJobStatus, ExecutionJobView } from './types';

export const EXECUTION_HISTORY_LIMIT = 10;
export function isActiveJob(job?: ExecutionJobView) { return job?.status === 'QUEUED' || job?.status === 'RUNNING'; }
function invalid(): never { throw new ApiError('INVALID_RESPONSE', 'Execution status could not be verified. Refresh execution history.'); }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
function id(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value)) return invalid();
  return value;
}
function timestamp(value: unknown): string {
  if (typeof value !== 'string' || value.length > 64 || !Number.isFinite(Date.parse(value))) return invalid();
  return value;
}
function nullableTimestamp(value: unknown) { return value === null ? null : timestamp(value); }
function job(value: unknown, taskId: string, jobId?: string): ExecutionJobView {
  const data = record(value);
  const result: ExecutionJobView = {
    id: id(data.id), task_id: id(data.task_id), project_id: id(data.project_id),
    status: data.status as ExecutionJobStatus, created_at: timestamp(data.created_at),
    started_at: nullableTimestamp(data.started_at), finished_at: nullableTimestamp(data.finished_at),
    safe_error_code: data.safe_error_code as ExecutionJobError | null,
  };
  if (result.task_id !== taskId || (jobId !== undefined && result.id !== jobId) ||
      !['QUEUED', 'RUNNING', 'SUCCEEDED', 'STOPPED', 'FAILED'].includes(result.status)) return invalid();
  const { status, started_at: start, finished_at: finish, safe_error_code: error } = result;
  const valid = status === 'QUEUED' ? start === null && finish === null && error === null :
    status === 'RUNNING' ? start !== null && finish === null && error === null :
    start !== null && finish !== null && (status === 'SUCCEEDED' ? error === null :
      status === 'STOPPED' ? error === 'RUNTIME_STOPPED' || error === 'EXECUTION_INTERRUPTED' : error === 'EXECUTION_FAILED');
  if (!valid || (start !== null && Date.parse(start) < Date.parse(result.created_at)) ||
      (finish !== null && start !== null && Date.parse(finish) < Date.parse(start))) return invalid();
  // Explicit allowlist: arbitrary provider/worker fields never enter browser state.
  return result;
}
export async function requestExecution(taskId: string, signal?: AbortSignal) {
  return job(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}/executions`, { method: 'POST', signal }), taskId);
}
export async function getExecution(taskId: string, jobId: string, signal?: AbortSignal) {
  return job(await request<unknown>(`/executions/${encodeURIComponent(jobId)}`, { signal, cache: 'no-store' }), taskId, jobId);
}
export async function getExecutions(taskId: string, signal?: AbortSignal): Promise<CollectionPage<ExecutionJobView>> {
  const data = record(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}/executions?limit=${EXECUTION_HISTORY_LIMIT}`, { signal, cache: 'no-store' }));
  if (!Array.isArray(data.items) || data.items.length > EXECUTION_HISTORY_LIMIT ||
      data.total_returned !== data.items.length || typeof data.truncated !== 'boolean') return invalid();
  const items = data.items.map(item => job(item, taskId));
  if (new Set(items.map(item => item.id)).size !== items.length) return invalid();
  return { items, total_returned: items.length, truncated: data.truncated };
}
