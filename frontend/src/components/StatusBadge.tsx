import type { TaskState } from '../api/types';
export function StatusBadge({ state }: { state: TaskState }) {
  const tone = state === 'DONE' ? 'success' : state === 'FAILED' ? 'danger' : state === 'BLOCKED' ? 'warning' : state === 'CREATED' ? 'neutral' : 'active';
  return <span className={`badge ${tone}`}>{state}</span>;
}
