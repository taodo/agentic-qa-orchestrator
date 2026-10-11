import type { CampaignReadiness, CampaignRequirement, CampaignTestSpecification, ApprovalEvidence } from './campaignTypes';
export type RunStatus = 'CREATED' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'STOPPED' | 'FAILED';
export type RunOutcome = 'NOT_EVALUATED' | 'PASS' | 'FAIL' | 'PARTIAL';
export interface QARun {
  id: string; project_id: string; campaign_id: string; run_number: number; idempotency_key: string; note: string | null;
  snapshot_version: string; snapshot_hash: string; requirement_count: number; test_count: number;
  campaign_snapshot: { id: string; project_id: string; name: string; objective: string | null; status: 'APPROVED' };
  readiness_at_creation: CampaignReadiness; execution_status: RunStatus; qa_outcome: RunOutcome;
  created_at: string; started_at: string | null; completed_at: string | null; execution_error_code: 'RUN_EXECUTION_FAILED' | null;
}
export interface RunRequirement { id: string; run_id: string; original_requirement_id: string; position: number; content: CampaignRequirement; approval: ApprovalEvidence }
export interface RunTest {
  id: string; run_id: string; original_test_specification_id: string; position: number; content: CampaignTestSpecification; approval: ApprovalEvidence;
  linked_requirement_snapshot_ids: string[]; execution_status: 'NOT_STARTED' | 'RUNNING' | 'COMPLETED' | 'BLOCKED'; qa_result: 'NOT_EVALUATED' | 'PASS' | 'FAIL' | 'SKIP';
}

// Closed wire payload variants; generic presentation uses only the server projection.
export type RunEvidencePayload = {variant:'synthetic-observation-v1';strategy:'synthetic-position-v1';position:number;outcome:'PASS'|'FAIL'|'SKIP'};
export interface EvidencePresentation {
  variant:string;display_label:string;details:{label:string;value:string}[];
}
export interface RunEvidence {
  id:string;project_id:string;campaign_id:string;run_id:string;run_test_id:string;
  sequence:number;recorded_at:string;schema_version:'qa-run-evidence-v1';
  kind:'EXECUTION_OBSERVATION';source:string;summary:string;
  payload:RunEvidencePayload;
  presentation:EvidencePresentation;
}
export interface RunTestResult extends RunTest {
  evidence_count:number;evidence:import('./types').CollectionPage<RunEvidence>;
}
export interface RunResults {
  run:QARun;
  summary:{total:number;completed:number;passed:number;failed:number;skipped:number;not_evaluated:number;remaining:number};
  tests:import('./types').CollectionPage<RunTestResult>;
}
