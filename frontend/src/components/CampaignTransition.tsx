import { transitionCampaign } from '../api/campaigns';
import type { CampaignView } from '../api/campaignTypes';
import { usePreparationAction } from '../app/usePreparationAction';
import { ErrorState } from './Feedback';

export function CampaignTransition({ campaign, changed }: { campaign: CampaignView; changed: (value: CampaignView) => Promise<void> }) {
  const action = usePreparationAction<CampaignView>();
  const next = campaign.status === 'DRAFT' ? 'READY_FOR_REVIEW' : 'APPROVED';
  const label = campaign.status === 'DRAFT' ? 'Submit Campaign for Review' : 'Approve Campaign Preparation';
  return <div className="preparation-action"><p className="hint">Campaign preparation approval is separate from derived readiness. Blockers can remain after approval; no tests are executed.</p>
    {campaign.status !== 'APPROVED' && <button disabled={action.busy} onClick={() => void action.run(() => transitionCampaign(campaign.project_id,campaign.id,next),changed)}>{action.busy ? 'Updating preparation…' : label}</button>}
    <p role="status">{action.busy && 'Updating Campaign preparation…'}{action.result && 'Campaign preparation updated. Readiness is assessed separately.'}</p>{action.error && <ErrorState error={action.error} />}
  </div>;
}
