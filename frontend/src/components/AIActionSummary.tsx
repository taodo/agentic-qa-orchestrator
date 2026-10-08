import type { AIActionMetadata, PreparationAttempt } from '../api/campaignTypes';
import { StateBadge } from './StatusBadge';

export type AIActionKind = 'extraction' | 'revision' | 'generation';
const labels = { extraction: 'Requirement Extraction', revision: 'Requirement Revision', generation: 'AI Test Generation' };
const categories = [['input_tokens', 'Input'], ['output_tokens', 'Output'], ['reasoning_tokens', 'Reasoning'], ['total_tokens', 'Total']] as const;
const integer = (value: number | null | undefined) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString() : 'Unavailable';

// Pure presentation: no reads, provider actions, totals reconstruction or pricing.
export function AIActionSummary({ attempt, kind, base, historical = false }: {
  attempt: PreparationAttempt & AIActionMetadata; kind: AIActionKind; base: string; historical?: boolean;
}) {
  const label = labels[kind], output = attempt.output, revised = output?.revised_requirement;
  const known = categories.some(([key]) => integer(attempt.usage?.[key]?.total) !== 'Unavailable');
  const target = revised ? `${base}/requirements?requirement_id=${encodeURIComponent(revised.id)}`
    : kind === 'generation' ? `${base}/test-specifications#test-specification-results` : `${base}/requirements#requirement-results`;
  return <section className="ai-action-summary" aria-label={`${label} result${historical ? ' '+attempt.id : ''}`}>
    <div className="panel-heading"><h4>{label} {attempt.status === 'SUCCEEDED' ? 'completed' : attempt.status === 'FAILED' ? 'failed' : 'started'}</h4><StateBadge status={attempt.status} /></div>
    <dl className="metadata ai-model-metadata"><div><dt>Configured model</dt><dd>{attempt.configured_model ?? 'Unavailable'}</dd></div>
      <div><dt>Provider model</dt><dd>{attempt.provider_model ?? 'Unavailable'}</dd></div><div><dt>Provider</dt><dd>{attempt.provider ?? 'Unavailable'}</dd></div></dl>
    {attempt.status === 'FAILED' && <p className="notice">{attempt.error_code && <code>{attempt.error_code}</code>} FAILED: This action failed. No accepted output was produced by this attempt. Retry eligibility is shown separately; no automatic retry occurred.</p>}
    {attempt.status === 'STARTED' && <p className="notice">Completion is not recorded. Do not replay uncertain provider work.</p>}
    {output ? <><dl className="metadata ai-output-counts"><div><dt>{kind === 'revision' ? 'Revised records' : 'Generated'}</dt><dd>{integer(output.generated_count)}</dd></div>
      <div><dt>Ready for review at creation</dt><dd>{integer(output.ready_for_review_count)}</dd></div><div><dt>Needs clarification at creation</dt><dd>{integer(output.needs_clarification_count)}</dd></div></dl>
      <p className="hint">These are this action’s accepted outputs at creation, including historical versions. Later approvals and Campaign totals are separate.</p>
      {revised && <p>New Requirement: <strong>{revised.key}</strong> · Version {integer(revised.version)} · <StateBadge status={revised.review_status} /><br /><span className="mono">{revised.id} · {revised.logical_key}</span></p>}
      {kind === 'revision' && output.needs_clarification_count > 0 && <p className="notice">The revised Requirement remains NEEDS_CLARIFICATION. Review its remaining markers; revision success does not resolve missing facts or approve it.</p>}
      {kind === 'generation' && output.inherited_clarification_count != null && output.inherited_clarification_count > 0 && <p className="notice">{integer(output.inherited_clarification_count)} generated Test Specification(s) require clarification because unresolved information was inherited from their selected Requirement(s). Generation does not resolve that ambiguity.</p>}
    </> : <p className="hint">Action output details are unavailable. No counts have been inferred from Campaign totals.</p>}
    <h5>Provider token usage</h5>{!known && <p className="hint">Usage unavailable. Missing provider usage is unknown, never zero.</p>}
    <dl className="ai-token-metrics">{categories.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{integer(attempt.usage?.[key]?.total)}</dd></div>)}</dl>
    <p className="hint">Provider-reported categories are independent. Reasoning is not added to output or total; unavailable categories are not calculated.</p>
    {attempt.status === 'SUCCEEDED' && <a className="button" href={target}>{kind === 'generation' ? 'View generated tests' : kind === 'revision' ? 'Review revised Requirement' : 'Review requirements'}</a>}
  </section>;
}
