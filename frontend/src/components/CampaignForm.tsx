import { useEffect, useRef, useState, type FormEvent } from 'react';
import { createCampaign } from '../api/campaigns';
import { publicError, type ApiError } from '../api/client';
import type { CampaignView } from '../api/campaignTypes';
import { ErrorState } from './Feedback';

export function CampaignForm({ projectId, onCreated }: { projectId: string; onCreated: (campaign: CampaignView) => void }) {
  const gate = useRef(false), active = useRef(true);
  const [busy, setBusy] = useState(false), [feedback, setFeedback] = useState('');
  const [error, setError] = useState<ApiError>();
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (gate.current) return;
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name') || '').trim(), objective = String(data.get('objective') || '');
    if (!name || Array.from(name).length > 200 || Array.from(objective).length > 4000) {
      setFeedback('Enter a name of 1–200 characters and an optional objective of at most 4,000 characters.'); return;
    }
    gate.current = true; setBusy(true); setError(undefined); setFeedback('');
    try {
      const campaign = await createCampaign(projectId, { name, ...(objective ? { objective } : {}) });
      if (active.current) onCreated(campaign);
    } catch (failure) { if (active.current) setError(publicError(failure)); }
    finally { gate.current = false; if (active.current) setBusy(false); }
  }
  return <section className="panel"><h2>Create Campaign</h2><p className="hint">Group requirements and test cases for one QA initiative. Creation starts preparation; it does not run tests.</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <label htmlFor="campaign-name">Campaign name <span className="muted">required</span></label>
      <input id="campaign-name" name="name" required maxLength={200} aria-describedby="campaign-name-hint" />
      <p id="campaign-name-hint" className="hint">1–200 characters.</p>
      <label htmlFor="campaign-objective">Objective <span className="muted">optional</span></label>
      <textarea id="campaign-objective" name="objective" rows={4} maxLength={4000} aria-describedby="campaign-objective-hint" />
      <p id="campaign-objective-hint" className="hint">What should this campaign verify? Up to 4,000 characters.</p>
      <button type="submit">{busy ? 'Creating Campaign…' : 'Create Campaign'}</button>
    </fieldset>{error && <ErrorState error={error} />}<p role="status">{feedback}</p></form>
  </section>;
}
