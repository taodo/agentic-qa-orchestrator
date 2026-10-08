import { useCallback, useId, useState, type FormEvent } from 'react';
import { extractRequirements, ingestSource, listSources, retryExtraction, listExtractionHistory } from '../api/campaigns';
import type { CampaignSource, RequirementExtraction } from '../api/campaignTypes';
import { AIActionSummary, type AIActionKind } from './AIActionSummary';
import { campaignPath } from '../api/campaigns';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { DateTime } from './DateTime';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from './Feedback';

export const textBytes = (value: string) => new TextEncoder().encode(value).length;
export const validDocument = (name: string, content: string) => !!name.trim() && Array.from(name.trim()).length <= 200 && !!content.trim() && textBytes(content) <= 65536;
export type PreparationScope = { projectId: string; campaignId: string; changed: () => Promise<void> };

function AttemptSummary({attempt,latest=false,kind,base,historical=false}:{attempt:RequirementExtraction;latest?:boolean;kind:AIActionKind;base:string;historical?:boolean}) {
  return <article className="evidence-record"><p>Attempt {attempt.attempt_number ?? 1} · {attempt.status} · {latest ? 'Latest/current attempt' : 'Historical attempt'}</p>
    <p>Contract: {attempt.contract_version ?? 'Unavailable'}</p>
    <p>Started: <DateTime value={attempt.started_at} /> · Finished: <DateTime value={attempt.finished_at} /></p>
    <AIActionSummary attempt={attempt} kind={kind} base={base} historical={historical} />
  </article>;
}

export function SourceExtraction({ source, projectId, campaignId, changed, initialLabel='Extract Requirements', onResult }: PreparationScope & { source: Pick<CampaignSource,'id'|'name'|'latest_extraction'>;initialLabel?:string;onResult?:(result:RequirementExtraction)=>void }) {
  const kind = initialLabel === 'Revise Requirement' ? 'revision' : 'extraction';
  const base = campaignPath(projectId,campaignId);
  const action = usePreparationAction<RequirementExtraction>();
  const history = usePreparationAction<Awaited<ReturnType<typeof listExtractionHistory>>>();
  const candidates = [action.result,history.result?.items[0],source.latest_extraction].filter((a):a is RequirementExtraction => !!a);
  const latest = candidates.sort((a,b) => (b.attempt_number ?? 1)-(a.attempt_number ?? 1))[0];
  async function refreshHistory() { await history.run(() => listExtractionHistory(projectId,campaignId,source.id)); }
  const label = action.busy ? 'Extracting…' : latest?.status === 'FAILED' ? 'Retry Extraction' : initialLabel;
  return <div className="preparation-action"><p className="hint">Extract from {source.name}. This explicit action may call the configured model; it is not a test run.</p>
    {(!latest || latest.status === 'FAILED' && latest.retryable) && <button className="button--primary" disabled={action.busy || action.error?.code === 'HOST_AUTH_REQUIRED'} onClick={() => void action.run(() => latest ? retryExtraction(projectId,campaignId,latest.id) : extractRequirements(projectId,campaignId,source.id),async result => {
      onResult?.(result);
      if(result.status === 'SUCCEEDED') await changed();
      if(history.result) await refreshHistory();
    })}>{label}</button>}
    {latest?.status === 'FAILED' && <p className="notice">Retryability: {latest.retryable ? 'Eligible. Retry Extraction is a new provider call and may consume tokens; prior failure remains recorded.' : 'Not eligible. Correct the source or provider configuration and add corrected source evidence. Refresh never retries.'}</p>}
    {latest?.status === 'STARTED' && <p className="notice">An attempt is STARTED. Inspect saved history; do not replay uncertain provider work.</p>}
    {action.busy && <p role="status">Extracting Requirements from {source.name}…</p>}
    {action.error && <ErrorState error={action.error} />}
    {action.result?.status === 'SUCCEEDED' && <p role="status">{kind === 'revision' ? 'Requirement revision complete.' : 'Requirement extraction complete.'} Review remains explicit.</p>}
    {latest && !(onResult && action.result?.status === 'SUCCEEDED') && <AttemptSummary attempt={latest} latest kind={kind} base={base} />}
    <button disabled={history.busy || action.busy} onClick={() => void refreshHistory()}>{history.busy ? 'Loading extraction history…' : history.result ? 'Refresh extraction history' : 'View extraction history'}</button>
    {history.error && <ErrorState error={history.error} />}
    {history.result && <><h4>Extraction attempt history</h4>{history.result.items.map(a => <AttemptSummary key={a.id} attempt={a} latest={a.is_latest ?? a.id === latest?.id} kind={kind} base={base} historical />)}<TruncationNotice truncated={history.result.truncated} /></>}
  </div>;
}

export function PreparationSources({ projectId, campaignId, changed, onResult }: PreparationScope & {onResult?:(attempt:RequirementExtraction,kind:'extraction'|'revision')=>void}) {
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
  return <section id="specification-sources" className="panel campaign-section" aria-labelledby={id+'heading'}><h2 id={id+'heading'}>Add PRD / Spec</h2>
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
      {source.clarification_requirement_id && <p className="hint">Clarification addendum for Requirement {source.clarification_requirement_id}. Revision remains a separate explicit model action.</p>}
      {source.status === 'INGESTED' && source.source_type !== 'PDF' ? <SourceExtraction source={source} projectId={projectId} campaignId={campaignId} changed={changed} initialLabel={source.clarification_requirement_id ? 'Revise Requirement' : 'Extract Requirements'} onResult={onResult ? attempt=>onResult(attempt,source.clarification_requirement_id ? 'revision' : 'extraction') : undefined} /> : <p className="notice">Extraction is unavailable for rejected or unsupported sources.</p>}
    </li>)}</ul>{sources.data && <TruncationNotice truncated={sources.data.truncated} />}
  </section>;
}
