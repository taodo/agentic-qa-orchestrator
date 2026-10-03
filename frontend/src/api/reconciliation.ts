import { ApiError, request } from './client';

export const reconciliationLabels = { CLEAR: 'Clear', RECOVERABLE: 'Recoverable', MANUAL_ACTION_REQUIRED: 'Manual action required', INCONSISTENT: 'Inconsistent' } as const;
export type ReconciliationStatus = keyof typeof reconciliationLabels;
export const recoveryGuidance = {
  EXECUTION_JOB_INTERRUPTED: 'An execution request was interrupted. Inspect Task state and core evidence separately before continuing.',
  AGENT_INVOCATION_PENDING: 'An agent invocation has no durable final outcome. Inspect its evidence; do not clear STARTED or retry blindly.',
  PROVIDER_CALL_UNCERTAIN: 'A reserved model turn has no durable outcome. Inspect provider-side outcome privately; do not replay the request.',
  IMPLEMENTATION_MUTATION_UNCERTAIN: 'Mutation outcome is uncertain. Inspect the authorized workspace and durable evidence; do not reapply or roll back automatically.',
  TEST_EXECUTION_PENDING: 'A test execution has no durable TestRun. Inspect the workspace and process outcome; do not rerun uncertain pytest.',
  WORKSPACE_DRIFT: 'Workspace identity or applied hashes do not verify. Inspect the trusted binding and explicit files privately; do not repair automatically.',
  EVIDENCE_INCONSISTENT: 'Durable evidence linkage is inconsistent. Have the trusted operator inspect it; do not fabricate completion or bypass gates.',
} as const;
export type RecoveryKind = keyof typeof recoveryGuidance;
export interface ReconciliationAssessment {
  task_id: string; status: ReconciliationStatus; safe_to_run: boolean; safe_to_resume: boolean;
  issues: { kind: RecoveryKind; severity: 'INFO' | 'BLOCKING'; evidence_refs: string[] }[];
}
function invalid(): never { throw new ApiError('INVALID_RESPONSE', 'Reconciliation could not be verified.'); }
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
export async function getReconciliation(taskId: string): Promise<ReconciliationAssessment> {
  const data = record(await request<unknown>(`/tasks/${encodeURIComponent(taskId)}/reconciliation`, { cache: 'no-store' }));
  if (data.task_id !== taskId || typeof data.status !== 'string' || !Object.hasOwn(reconciliationLabels, data.status) ||
      typeof data.safe_to_run !== 'boolean' || typeof data.safe_to_resume !== 'boolean' || !Array.isArray(data.issues) || data.issues.length > 100) return invalid();
  const issues = data.issues.map(value => {
    const issue = record(value);
    if (typeof issue.kind !== 'string' || !Object.hasOwn(recoveryGuidance, issue.kind) || !['INFO', 'BLOCKING'].includes(String(issue.severity)) ||
        !Array.isArray(issue.evidence_refs) || issue.evidence_refs.length > 8 || issue.evidence_refs.some(ref => typeof ref !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(ref))) return invalid();
    // Never retain arbitrary server summaries, paths, exceptions or provider fields.
    return { kind: issue.kind as RecoveryKind, severity: issue.severity as 'INFO' | 'BLOCKING', evidence_refs: issue.evidence_refs as string[] };
  });
  const unsafe = data.status === 'MANUAL_ACTION_REQUIRED' || data.status === 'INCONSISTENT';
  if ((unsafe || issues.some(issue => issue.severity === 'BLOCKING')) && (data.safe_to_run || data.safe_to_resume)) return invalid();
  return { task_id: taskId, status: data.status as ReconciliationStatus, safe_to_run: data.safe_to_run, safe_to_resume: data.safe_to_resume, issues };
}
