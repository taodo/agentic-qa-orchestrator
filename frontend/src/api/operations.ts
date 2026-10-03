import { ApiError, request } from './client';
import type { CollectionPage, TaskState, ExecutionJobStatus, ExecutionJobError } from './types';

export const taskStates: TaskState[] = ['CREATED', 'RESEARCHING', 'PLANNING', 'IMPLEMENTING', 'TESTING', 'ANALYZING', 'INVESTIGATING', 'REVIEWING', 'BLOCKED', 'FAILED', 'DONE'];
const jobs: ExecutionJobStatus[] = ['QUEUED', 'RUNNING', 'SUCCEEDED', 'STOPPED', 'FAILED'];
const jobErrors: ExecutionJobError[] = ['RUNTIME_STOPPED', 'EXECUTION_INTERRUPTED', 'EXECUTION_FAILED'];
export type Attention = 'NORMAL' | 'ACTIVE' | 'ATTENTION' | 'BLOCKED';
export const attentionLabels: Record<Attention, string> = { NORMAL: 'Normal', ACTIVE: 'Active', ATTENTION: 'Attention', BLOCKED: 'Blocked' };
export const activityLabels = {
  TASK_STATE_CHANGED: 'Task state changed', EXECUTION_QUEUED: 'Execution queued', EXECUTION_STARTED: 'Execution started',
  EXECUTION_SUCCEEDED: 'Execution succeeded', EXECUTION_STOPPED: 'Execution stopped', EXECUTION_FAILED: 'Execution failed',
  BLOCKING_ERROR_RECORDED: 'Blocking error recorded', TEST_PASS: 'TestRun PASS', TEST_FAIL: 'TestRun FAIL', TEST_UNKNOWN: 'TestRun UNKNOWN',
};
export const errorLabels = { ERROR_RECORDED: 'Error recorded', OUTPUT_SCHEMA_INVALID: 'Output schema invalid',
  MUTATION_RECONCILIATION_REQUIRED: 'Mutation reconciliation required', EXECUTION_FAILED: 'Execution failed',
  EXECUTION_INTERRUPTED: 'Execution interrupted', RUNTIME_STOPPED: 'Runtime stopped' };
export interface OperationalSummary {
  project_count: number; task_count: number; running_jobs: number; queued_jobs: number; blocked_tasks: number;
  terminal_tasks: number; reconciliation_attention_tasks: number; recent_failed_jobs: number; recent_stopped_jobs: number;
  recent_jobs_window: number; generated_at: string;
}
export interface OperationalProject {
  project_id: string; project_key: string; task_count: number; active_jobs: number; blocked_tasks: number;
  reconciliation_attention_tasks: number; latest_activity_at: string;
}
export interface OperationalTask {
  task_id: string; project_id: string; project_key: string; title: string; task_state: TaskState;
  active_execution_status: ExecutionJobStatus | null; latest_execution_status: ExecutionJobStatus | null;
  latest_execution_error_code: ExecutionJobError | null; reconciliation_attention: boolean;
  attention: Attention; latest_error_code: keyof typeof errorLabels | null; updated_at: string;
}
export interface OperationalActivity {
  record_id: string; task_id: string; project_id: string; kind: keyof typeof activityLabels; timestamp: string; task_state: TaskState | null;
}
export interface OperationsSnapshot {
  summary: OperationalSummary; projects: CollectionPage<OperationalProject>;
  tasks: CollectionPage<OperationalTask>; activity: CollectionPage<OperationalActivity>;
}

// Explicit projections discard any unexpected response fields. Enum text never
// becomes a display label without validation against this fixed vocabulary.
function invalid(): never { throw new ApiError('INVALID_RESPONSE', 'Operational snapshot unavailable.'); }
function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : invalid(); }
function text(value: unknown, max: number): string { return typeof value === 'string' && value.length <= max ? value : invalid(); }
export function validUuid(value: string): boolean { return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value); }
function uuid(value: unknown): string { const id = text(value, 36); return validUuid(id) ? id : invalid(); }
function stamp(value: unknown): string { const time = text(value, 40); return Number.isFinite(Date.parse(time)) ? time : invalid(); }
function count(value: unknown): number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid(); }
function bool(value: unknown): boolean { return typeof value === 'boolean' ? value : invalid(); }
function enumeration<T extends string>(value: unknown, allowed: readonly T[]): T { return typeof value === 'string' && allowed.includes(value as T) ? value as T : invalid(); }
function nullable<T>(value: unknown, parse: (value: unknown) => T): T | null { return value === null ? null : parse(value); }
function page<T>(value: unknown, parse: (value: unknown) => T): CollectionPage<T> {
  const data = object(value);
  if (!Array.isArray(data.items) || data.items.length > 50 || data.total_returned !== data.items.length) invalid();
  return { items: data.items.map(parse), total_returned: count(data.total_returned), truncated: bool(data.truncated) };
}
function summary(value: unknown): OperationalSummary {
  const v = object(value);
  if (v.recent_jobs_window !== 50) invalid();
  return { project_count: count(v.project_count), task_count: count(v.task_count), running_jobs: count(v.running_jobs),
    queued_jobs: count(v.queued_jobs), blocked_tasks: count(v.blocked_tasks), terminal_tasks: count(v.terminal_tasks),
    reconciliation_attention_tasks: count(v.reconciliation_attention_tasks), recent_failed_jobs: count(v.recent_failed_jobs),
    recent_stopped_jobs: count(v.recent_stopped_jobs), recent_jobs_window: 50, generated_at: stamp(v.generated_at) };
}
function project(value: unknown): OperationalProject {
  const v = object(value);
  return { project_id: uuid(v.project_id), project_key: text(v.project_key, 64), task_count: count(v.task_count),
    active_jobs: count(v.active_jobs), blocked_tasks: count(v.blocked_tasks), reconciliation_attention_tasks: count(v.reconciliation_attention_tasks), latest_activity_at: stamp(v.latest_activity_at) };
}
function task(value: unknown): OperationalTask {
  const v = object(value);
  return { task_id: uuid(v.task_id), project_id: uuid(v.project_id), project_key: text(v.project_key, 64), title: text(v.title, 240),
    task_state: enumeration(v.task_state, taskStates), active_execution_status: nullable(v.active_execution_status, value => enumeration(value, ['QUEUED', 'RUNNING'] as const)),
    latest_execution_status: nullable(v.latest_execution_status, value => enumeration(value, jobs)), latest_execution_error_code: nullable(v.latest_execution_error_code, value => enumeration(value, jobErrors)),
    reconciliation_attention: bool(v.reconciliation_attention), attention: enumeration(v.attention, Object.keys(attentionLabels) as Attention[]),
    latest_error_code: nullable(v.latest_error_code, value => enumeration(value, Object.keys(errorLabels) as (keyof typeof errorLabels)[])), updated_at: stamp(v.updated_at) };
}
function activity(value: unknown): OperationalActivity {
  const v = object(value);
  return { record_id: uuid(v.record_id), task_id: uuid(v.task_id), project_id: uuid(v.project_id),
    kind: enumeration(v.kind, Object.keys(activityLabels) as (keyof typeof activityLabels)[]), timestamp: stamp(v.timestamp), task_state: nullable(v.task_state, value => enumeration(value, taskStates)) };
}

export async function getOperations(taskQuery: string, projectId: string): Promise<OperationsSnapshot> {
  // allSettled keeps the cycle occupied until every GET settles, even if one
  // fails early; the next refresh cannot overlap remaining requests.
  const results = await Promise.allSettled([
    request<unknown>('/operations/summary'), request<unknown>('/operations/projects?limit=50'),
    request<unknown>(`/operations/tasks?limit=50${taskQuery ? `&${taskQuery}` : ''}`),
    request<unknown>(`/operations/activity?limit=50${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ''}`),
  ]);
  const values = results.map(result => result.status === 'fulfilled' ? result.value : (() => { throw result.reason; })());
  return { summary: summary(values[0]), projects: page(values[1], project), tasks: page(values[2], task), activity: page(values[3], activity) };
}
