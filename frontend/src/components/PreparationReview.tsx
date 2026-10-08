import { useId, useState, type FormEvent } from 'react';
import { getRequirementReview, getTestReview, reviewRequirement, reviewTest } from '../api/campaigns';
import type { ReviewState, ReviewStatus } from '../api/campaignTypes';
import { usePreparationAction } from '../app/usePreparationAction';
import type { PreparationScope } from './PreparationSources';
import { DateTime } from './DateTime';
import { ErrorState } from './Feedback';

export function PreparationReview({ projectId, campaignId, changed, objectId, kind, status, blocked }: PreparationScope & {
  objectId: string; kind: 'Requirement' | 'Test Specification'; status: ReviewStatus; blocked: boolean;
}) {
  const action = usePreparationAction<ReviewState>(), evidence = usePreparationAction<ReviewState>();
  const id = useId(), [validation, setValidation] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const reviewer_label = String(data.get('reviewer_label') || ''), note = String(data.get('note') || '');
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(reviewer_label) || Array.from(note).length > 1000) { setValidation('Use a reviewer label starting with a letter, followed by letters, digits, underscore, period or hyphen (up to 64 characters); note up to 1,000 characters.'); return; }
    setValidation('');
    await action.run(() => (kind === 'Requirement' ? reviewRequirement : reviewTest)(projectId, campaignId, objectId, { action: 'APPROVE', reviewer_label, ...(note ? { note } : {}) }), async () => { await changed(); });
  }
  const receipt = action.result?.evidence ?? evidence.result?.evidence;
  if (status === 'APPROVED') return <div className="preparation-action"><p>Approved content is immutable. Approval never runs tests.</p>
    {!receipt && <button disabled={evidence.busy} onClick={() => void evidence.run(() => (kind === 'Requirement' ? getRequirementReview : getTestReview)(projectId, campaignId, objectId))}>{evidence.busy ? 'Loading approval evidence…' : 'View approval evidence'}</button>}
    {evidence.error && <ErrorState error={evidence.error} />}
    {evidence.result && !receipt && <p role="status">Approval evidence is unavailable in this response.</p>}
    {receipt && <dl className="metadata"><div><dt>Reviewer label (operator assertion)</dt><dd>{receipt.reviewer_label}</dd></div><div><dt>Approved time</dt><dd><DateTime value={receipt.approved_at} /></dd></div><div><dt>Review note</dt><dd className="prose">{receipt.note ?? 'No note provided.'}</dd></div></dl>}
  </div>;
  if (status !== 'READY_FOR_REVIEW' || blocked) return <p className="notice">Approval is blocked: {status === 'DRAFT' ? 'this record is still Draft.' : 'unresolved clarification or traceability facts remain.'} Clarification/revision is not yet supported. No Resolve action is available.</p>;
  return <form className="preparation-action" aria-label={'Approve '+kind} onSubmit={submit}><fieldset disabled={action.busy}><legend>Human review: {kind}</legend>
    <p className="hint">Reviewer label is an operator assertion, not an authenticated account identity. Never enter credentials or secrets in labels or notes. Approval does not execute tests.</p>
    <label htmlFor={id+'label'}>Reviewer label</label><input id={id+'label'} name="reviewer_label" required maxLength={64} />
    <label htmlFor={id+'note'}>Review note (optional)</label><textarea id={id+'note'} name="note" maxLength={1000} rows={3} />
    <button type="submit">{action.busy ? 'Recording approval…' : 'Approve '+kind}</button>
  </fieldset><p role="status">{validation}{action.busy && 'Recording approval…'}{action.result && 'Approval recorded.'}</p>{action.error && <ErrorState error={action.error} />}</form>;
}
