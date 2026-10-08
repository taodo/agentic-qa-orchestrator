import type { CollectionPage, UUID, Timestamp } from './types';

export type PreparationStatus = 'DRAFT' | 'READY_FOR_REVIEW' | 'APPROVED';
export type ReviewStatus = PreparationStatus | 'NEEDS_CLARIFICATION';
export type CoverageStatus = 'COVERED' | 'PARTIAL' | 'NOT_COVERED';
export type ReadinessStatus = 'READY' | 'NOT_READY';
export interface CampaignView {
  id: UUID; project_id: UUID; name: string; objective: string | null;
  status: PreparationStatus; created_at: Timestamp; updated_at: Timestamp;
}
export interface InformationMarker { kind: 'AMBIGUITY' | 'MISSING_INFORMATION'; description: string }
export interface TestMarker { kind: InformationMarker['kind'] | 'UNRESOLVED_REQUIREMENT' | 'MISSING_TRACEABILITY'; description: string }
export interface SourceCitation { source_id: UUID; source_hash: string; location_type: 'LINES'; start_line: number; end_line: number; excerpt: string }
export interface CampaignRequirement {
  id: UUID; project_id: UUID; campaign_id: UUID; extraction_id: UUID;
  key: string; logical_key: string; title: string; description: string;
  acceptance_criteria: { key: string; text: string }[]; source_references: SourceCitation[];
  information_markers: InformationMarker[]; review_status: ReviewStatus; created_at: Timestamp; updated_at: Timestamp;
}
export interface CampaignTestSpecification {
  id: UUID; project_id: UUID; campaign_id: UUID; key: string; logical_key: string; title: string;
  test_type: 'FUNCTIONAL' | 'REGRESSION' | 'SMOKE' | 'NEGATIVE' | 'BOUNDARY' | 'INTEGRATION' | 'API' | 'WEB' | 'DATA' | 'OTHER';
  priority: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'; preconditions: string[];
  steps: { index: number; action: string; expected: string | null }[];
  overall_expected_result: string | null; required_evidence: string[];
  information_markers: TestMarker[]; requirement_ids: UUID[]; unresolved_requirement_refs: string[];
  provenance: { origin: 'IMPORT' | 'AI_GENERATED'; record_id: UUID; content_hash: string;
    contract_version: 'test-import-v1' | 'test-specs-v1'; start_line: number | null; end_line: number | null };
  review_status: ReviewStatus; created_at: Timestamp; updated_at: Timestamp;
}
export interface RequirementTrace {
  requirement_id: UUID; review_status: ReviewStatus; linked_test_count: number; approved_test_count: number;
  linked_test_review_states: Partial<Record<ReviewStatus, number>>; coverage: CoverageStatus;
}
export interface TraceLink { requirement_id: UUID; test_spec_id: UUID; test_review_status: ReviewStatus }
export interface CampaignTraceability {
  project_id: UUID; campaign_id: UUID;
  requirements: CollectionPage<RequirementTrace>; links: CollectionPage<TraceLink>;
}
export type ReadinessBlocker = 'CAMPAIGN_NOT_APPROVED' | 'NO_REQUIREMENTS' | 'REQUIREMENTS_NOT_APPROVED'
  | 'REQUIREMENTS_NEED_CLARIFICATION' | 'NO_TEST_SPECIFICATIONS' | 'REQUIREMENT_COVERAGE_GAP'
  | 'INVALID_REQUIREMENT_APPROVAL' | 'INVALID_TEST_APPROVAL';
export interface CampaignReadiness {
  project_id: UUID; campaign_id: UUID; campaign_preparation_status: PreparationStatus; status: ReadinessStatus;
  total_requirements: number; approved_requirements: number; clarification_requirements: number;
  total_test_specifications: number; approved_test_specifications: number;
  covered_requirements: number; partial_requirements: number; uncovered_requirements: number;
  invalid_approved_requirements: number; invalid_approved_test_specifications: number;
  blocker_codes: ReadinessBlocker[];
}

export interface CampaignSource {
  id: UUID; project_id: UUID; campaign_id: UUID; source_type: 'TEXT' | 'MARKDOWN' | 'PDF'; name: string;
  content_hash: string; raw_hash: string; normalization_version: string; original_bytes: number;
  normalized_chars: number; line_count: number; status: 'INGESTED' | 'REJECTED'; error_code: string | null; created_at: Timestamp;
}
export interface PreparationAttempt {
  id: UUID; project_id: UUID; campaign_id: UUID; status: 'STARTED' | 'SUCCEEDED' | 'FAILED';
  started_at: Timestamp; finished_at: Timestamp | null; error_code: string | null;
}
export interface RequirementExtraction extends PreparationAttempt { source_id: UUID; source_hash: string; contract_version: string }
export interface TestGeneration extends PreparationAttempt { requirement_versions: { id: UUID; snapshot_hash: string }[]; contract_version: string }
export interface TestImport {
  id: UUID; project_id: UUID; campaign_id: UUID; name: string; format: 'CSV' | 'MARKDOWN' | 'XLSX';
  raw_hash: string; content_hash: string; contract_version: string; normalization_version: string;
  original_bytes: number; status: 'IMPORTED' | 'REJECTED'; error_code: string | null; test_count: number; created_at: Timestamp;
}
export interface ApprovalCommand { action: 'APPROVE'; reviewer_label: string; note?: string }
export interface ApprovalEvidence {
  object_id: UUID; object_kind: 'REQUIREMENT' | 'TEST_SPECIFICATION'; project_id: UUID; campaign_id: UUID;
  status: 'APPROVED'; reviewer_label: string; note: string | null; content_hash: string; approved_at: Timestamp;
}
export interface ReviewState {
  project_id: UUID; campaign_id: UUID; object_id: UUID; object_kind: 'REQUIREMENT' | 'TEST_SPECIFICATION';
  review_status: ReviewStatus; evidence: ApprovalEvidence | null;
}
