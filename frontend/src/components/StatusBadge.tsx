import type { TaskState } from '../api/types';

const success = new Set(['DONE', 'APPROVED', 'COVERED', 'READY', 'PASS']);
const danger = new Set(['FAILED', 'FAIL']);
const warning = new Set(['BLOCKED', 'STOPPED', 'NEEDS_CLARIFICATION', 'PARTIAL', 'NOT_COVERED', 'NOT_READY']);
const active = new Set(['READY_FOR_REVIEW', 'RUNNING', 'QUEUED', 'RESEARCHING', 'PLANNING', 'IMPLEMENTING', 'TESTING', 'ANALYZING', 'INVESTIGATING', 'REVIEWING']);

export function StateBadge({ status, label = status }: { status: string; label?: string }) {
  const tone = success.has(status) ? 'success' : danger.has(status) ? 'danger' : warning.has(status) ? 'warning' : active.has(status) ? 'active' : 'neutral';
  return <span className={`badge ${tone}`} title={status}>{label}</span>;
}
export function StatusBadge({ state }: { state: TaskState }) {
  return <StateBadge status={state} />;
}
