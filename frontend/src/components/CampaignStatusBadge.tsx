import type { PreparationStatus, ReviewStatus, CoverageStatus, ReadinessStatus } from '../api/campaignTypes';

type Status = PreparationStatus | ReviewStatus | CoverageStatus | ReadinessStatus;
const labels: Record<Status, string> = { DRAFT: 'Draft', READY_FOR_REVIEW: 'Ready for review', APPROVED: 'Approved',
  NEEDS_CLARIFICATION: 'Needs clarification', COVERED: 'Covered', PARTIAL: 'Partial', NOT_COVERED: 'Not covered',
  READY: 'Ready', NOT_READY: 'Not ready' };
export function CampaignStatusBadge({ status }: { status: Status }) {
  const tone = ['APPROVED', 'COVERED', 'READY'].includes(status) ? 'success'
    : ['NEEDS_CLARIFICATION', 'PARTIAL', 'NOT_COVERED', 'NOT_READY'].includes(status) ? 'warning'
    : status === 'READY_FOR_REVIEW' ? 'active' : 'neutral';
  return <span className={`badge ${tone}`} title={status}>{labels[status]}</span>;
}
