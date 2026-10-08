import { StateBadge } from './StatusBadge';
import type { PreparationStatus, ReviewStatus, CoverageStatus, ReadinessStatus } from '../api/campaignTypes';

type Status = PreparationStatus | ReviewStatus | CoverageStatus | ReadinessStatus;
const labels: Record<Status, string> = { DRAFT: 'Draft', READY_FOR_REVIEW: 'Ready for review', APPROVED: 'Approved',
  NEEDS_CLARIFICATION: 'Needs clarification', COVERED: 'Covered', PARTIAL: 'Partial', NOT_COVERED: 'Not covered',
  READY: 'Ready', NOT_READY: 'Not ready' };
export function CampaignStatusBadge({ status }: { status: Status }) {
  return <StateBadge status={status} label={labels[status]} />;
}
