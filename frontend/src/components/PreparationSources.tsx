import { useCallback, useId, useState, type FormEvent } from 'react';
import { extractRequirements, ingestSource, listSources } from '../api/campaigns';
import type { CampaignSource, RequirementExtraction } from '../api/campaignTypes';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { DateTime } from './DateTime';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from './Feedback';

export const textBytes = (value: string) => new TextEncoder().encode(value).length;
export const validDocument = (name: string, content: string) => !!name.trim() && Array.from(name.trim()).length <= 200 && !!content.trim() && textBytes(content) <= 65536;
export type PreparationScope = { projectId: string; campaignId: string; changed: () => Promise<void> };

function SourceExtraction({ source, projectId, campaignId, changed }: PreparationScope & { source: CampaignSource }) {
  const action = usePreparationAction<RequirementExtraction>();
  return <div className="preparation-action"><p className="hint">Extract from {source.name}. This explicit action may call the configured model; it is not a test run.</p>
    <button disabled={action.busy} onClick={() => void action.run(() => extractRequirements(projectId, campaignId, source.id), async result => { if (result.status === 'SUCCEEDED') await changed(); })}>{action.busy ? 'Extracting…' : 'Extract Requirements'}</button>
    {action.busy && <p role="status">Extracting Requirements from {source.name}…</p>}
    {action.error && <ErrorState error={action.error} />}
    {action.result && <p role="status">{action.result.status === 'SUCCEEDED' ? 'Requirement extraction complete.' : 'Requirement extraction did not complete successfully.'} Status: {action.result.status}.{action.result.error_code && <> Code: {action.result.error_code}.</>} Existing terminal attempts are returned without replay; unresolved attempts require operator attention.</p>}
  </div>;
}

export function PreparationSources({ projectId, campaignId, changed }: PreparationScope) {
  const sources = useResource(useCallback(() => listSources(projectId, campaignId), [projectId, campaignId]));
  const action = usePreparationAction<CampaignSource>();
  const [validation, setValidation] = useState('');
  const id = useId();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const name = String(data.get('name') || '').trim(), content = String(data.get('content') || '');
    const source_type = data.get('source_type') === 'MARKDOWN' ? 'MARKDOWN' : 'TEXT';
    if (!validDocument(name, content)) { setValidation('Enter a name of 1–200 characters and non-empty content up to 65,536 UTF-8 bytes.'); return; }
    setValidation(''); await action.run(() => ingestSource(projectId, campaignId, { name, source_type, content }), async () => { await sources.reload(); });
  }
  const rows = sources.data?.items ?? [];
  const available = action.result && !rows.some(row => row.id === action.result!.id) ? [action.result, ...rows] : rows;
  return <section className="panel campaign-section" aria-labelledby={id+'heading'}><h2 id={id+'heading'}>Add PRD / Spec</h2>
    <p>Plain text (.txt) and Markdown (.md) are supported. PDF is not supported yet.</p>
    <p className="hint">Paste or type document text. Up to 65,536 UTF-8 bytes / 4,096 lines; backend validation is authoritative. Content is inert text. Adding a source never starts extraction.</p>
    <form onSubmit={submit} aria-label="Add specification"><fieldset disabled={action.busy}><legend>Specification source</legend>
      <label htmlFor={id+'name'}>Source name</label><input id={id+'name'} name="name" required maxLength={200} />
      <label htmlFor={id+'type'}>Source type</label><select id={id+'type'} name="source_type"><option value="TEXT">Plain text (.txt)</option><option value="MARKDOWN">Markdown (.md)</option></select>
      <label htmlFor={id+'content'}>Specification content</label><textarea id={id+'content'} name="content" required maxLength={65536} rows={8} />
      <button type="submit">{action.busy ? 'Adding specification…' : 'Add Specification'}</button>
    </fieldset><p role="status">{validation}{action.busy && 'Adding specification…'}{action.result && <>Source available. Status: {action.result.status}.{action.result.error_code && <> Code: {action.result.error_code}.</>} Identical content may return an existing source.</>}</p>{action.error && <ErrorState error={action.error} />}</form>
    <div className="panel-heading campaign-section"><h3>Campaign Sources</h3><button disabled={sources.loading} onClick={() => void sources.reload()}>Refresh Sources</button></div>
    {sources.loading && <LoadingState>Loading Sources…</LoadingState>}{sources.error && <ErrorState error={sources.error} retry={() => void sources.reload()} />}
    {!sources.loading && !sources.error && !available.length && <EmptyState>No specification sources yet. Add text or Markdown above.</EmptyState>}
    <ul className="preparation-records">{available.map(source => <li className="evidence-record" key={source.id}><h3>{source.name}</h3>
      <p>{source.source_type} · <strong>{source.status}</strong>{source.error_code && <> · {source.error_code}</>}</p>
      <p className="hint">{source.original_bytes} original bytes · {source.normalized_chars} normalized characters · {source.line_count} lines · <DateTime value={source.created_at} /></p>
      {source.status === 'INGESTED' && source.source_type !== 'PDF' ? <SourceExtraction source={source} projectId={projectId} campaignId={campaignId} changed={changed} /> : <p className="notice">Extraction is unavailable for rejected or unsupported sources.</p>}
    </li>)}</ul>{sources.data && <TruncationNotice truncated={sources.data.truncated} />}
  </section>;
}
