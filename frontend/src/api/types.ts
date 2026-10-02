// Manual transport contracts matching Task 13. UUIDs/datetimes are JSON strings.
export type UUID = string;
export type Timestamp = string;
export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type TaskState = 'CREATED' | 'RESEARCHING' | 'PLANNING' | 'IMPLEMENTING' | 'TESTING' | 'ANALYZING' | 'INVESTIGATING' | 'REVIEWING' | 'BLOCKED' | 'FAILED' | 'DONE';
export type AgentName = 'RESEARCHER' | 'PLANNER' | 'IMPLEMENTER' | 'TEST_ANALYZER' | 'INVESTIGATOR' | 'REVIEWER';
export interface CollectionPage<T> { items: T[]; total_returned: number; truncated: boolean }
export interface ProjectView { id: UUID; key: string; name: string; description: string; created_at: Timestamp; updated_at: Timestamp }
export interface TaskSummary { id: UUID; project_id: UUID; title: string; state: TaskState; created_at: Timestamp; updated_at: Timestamp; completed_at: Timestamp | null }
export interface TaskDetail extends TaskSummary {
  requirement: string; resume_state: TaskState | null; current_invocation_id: UUID | null;
  implementation_attempt: number; defect_cycle: number; review_cycle: number; terminal_reason: string | null;
}
export interface ActorRef { type: 'HUMAN' | 'AGENT' | 'TOOL' | 'ORCHESTRATOR' | 'SYSTEM'; id: string }
export interface CorrelationRef { invocation_id: UUID | null; artifact_id: UUID | null; test_run_id: UUID | null; decision_id: UUID | null }
export interface TimelineEntry {
  index: number; insertion_order: number; timestamp: Timestamp; timestamp_tied: boolean;
  event_id: UUID; task_id: UUID; category: string; event_type: string; actor: ActorRef;
  correlation: CorrelationRef; summary: string; details: JsonValue;
}
export interface ArtifactView {
  id: UUID; task_id: UUID; invocation_id: UUID | null;
  artifact_type: 'RESEARCH' | 'PLAN' | 'IMPLEMENTATION' | 'IMPLEMENTATION_PROPOSAL' | 'TEST_RESULT' | 'TEST_ANALYSIS' | 'INVESTIGATION' | 'REVIEW' | 'REPOSITORY_EVIDENCE';
  schema_version: string; producer_agent: AgentName | null; producer_model: string | null;
  content: JsonValue; created_at: Timestamp; supersedes_artifact_id: UUID | null;
}
export interface TestRunView {
  id: UUID; task_id: UUID; implementation_artifact_id: UUID; report_artifact_id: UUID | null;
  execution_status: 'COMPLETED' | 'INCOMPLETE' | 'FAILED'; outcome: 'PASS' | 'FAIL' | 'UNKNOWN';
  environment: string; started_at: Timestamp; finished_at: Timestamp; passed_count: number; failed_count: number; skipped_count: number;
}
export interface ErrorView {
  id: UUID; task_id: UUID;
  error_type: 'AGENT_ERROR' | 'SCHEMA_ERROR' | 'TOOL_ERROR' | 'TEST_FAILURE' | 'ENVIRONMENT_ERROR' | 'POLICY_VIOLATION' | 'WORKFLOW_ERROR' | 'EXTERNAL_BLOCKER';
  code: string; severity: 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'; owner: 'AGENT' | 'TOOL' | 'TEST_TARGET' | 'ENVIRONMENT' | 'ORCHESTRATOR' | 'EXTERNAL';
  retryable: boolean; blocking: boolean; source: { actor: ActorRef | null; invocation_id: UUID | null; tool: string | null };
  message: string; evidence_refs: string[]; created_at: Timestamp;
}
export interface DecisionView { id: UUID; task_id: UUID; decision_type: 'ROUTE_AGENT' | 'RETRY' | 'ESCALATE_MODEL' | 'TRANSITION' | 'BLOCK' | 'FAIL' | 'RESUME'; decision_source: string; reason_code: string; reason_details: string; evidence_refs: string[]; created_at: Timestamp }
export interface GateEvaluationView { id: UUID; task_id: UUID; gate_name: string; result: 'PASS' | 'FAIL' | 'BLOCKED'; checks: { check: string; result: 'PASS' | 'FAIL' | 'BLOCKED'; reason: string | null }[]; blocking_reasons: string[]; evaluated_at: Timestamp }
export interface InvocationView { id: UUID; task_id: UUID; agent: AgentName; model: string; reasoning_effort: string; attempt: number; status: 'STARTED' | 'COMPLETED' | 'FAILED' | 'BLOCKED'; started_at: Timestamp; finished_at: Timestamp | null; error_id: UUID | null }
export interface ApiErrorEnvelope { error: { code: string; message: string } }
