import { useCallback, useId, useState, type FormEvent } from 'react';
import { generateTests, importTests, listRequirements } from '../api/campaigns';
import type { TestGeneration, TestImport } from '../api/campaignTypes';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { validDocument, type PreparationScope } from './PreparationSources';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from './Feedback';

const sample = { key: 'LOGIN', title: 'Sign in', requirement_refs: ['LOGIN'], test_type: 'FUNCTIONAL', priority: 'HIGH',
  preconditions: ['Existing user'], steps: [{ index: 1, action: 'Sign in', expected: 'User is signed in' }],
  overall_expected_result: 'User is signed in', required_evidence: ['Observed sign-in state'], information_markers: [] };
export const CSV_COLUMNS = 'key,title,requirement_refs,test_type,priority,preconditions,steps,overall_expected_result,required_evidence,information_markers';
export const CSV_TEMPLATE = CSV_COLUMNS+'\n'+Object.entries(sample).map(([key,value]) => {
  const cell = ['key','title','test_type','priority'].includes(key) ? String(value) : JSON.stringify(value);
  return '"'+cell.replaceAll('"','""')+'"';
}).join(',');
const { key: sampleKey, ...design } = sample;
export const MARKDOWN_TEMPLATE = '# Test cases\n\n## '+sampleKey+'\n```json\n'+JSON.stringify(design,null,2)+'\n```';

export function PreparationImport({ projectId, campaignId, changed }: PreparationScope) {
  const action = usePreparationAction<TestImport>(), [validation, setValidation] = useState(''); const id = useId();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    const name=String(data.get('name') || '').trim(), content=String(data.get('content') || '');
    const format=data.get('format') === 'MARKDOWN' ? 'MARKDOWN' : 'CSV';
    if (!validDocument(name,content)) { setValidation('Enter a name of 1–200 characters and non-empty content up to 65,536 UTF-8 bytes.'); return; }
    setValidation(''); await action.run(() => importTests(projectId,campaignId,{name,format,content}), async result => { if (result.status === 'IMPORTED') await changed(); });
  }
  return <section id="test-import" className="panel campaign-section"><h2>Import Existing Tests</h2><p>CSV and Markdown are supported. XLSX is not supported yet.</p>
    <p className="hint">Paste strict template text; up to 65,536 UTF-8 bytes, 4,096 lines and 100 cases. Unknown, ambiguous or foreign Requirement references become unresolved clarification markers, never fuzzy-matched links.</p>
    <details className="import-help"><summary>Import format help and templates</summary><h3>CSV</h3>
      <p>Exact header order; no extra columns. key, title, test_type and priority are plain cells. Every other cell is JSON. CSV quotes within cells must be doubled.</p><pre>{CSV_TEMPLATE}</pre>
      <h3>Markdown</h3><p>Exact # Test cases heading, then ## KEY immediately followed by a json fenced object. The key comes only from the section heading. No extra prose or fields.</p><pre>{MARKDOWN_TEMPLATE}</pre>
      <p>Replace LOGIN with an exact Campaign Requirement UUID, source-qualified logical key or unambiguous local key. Unknown references block approval. Types: FUNCTIONAL, REGRESSION, SMOKE, NEGATIVE, BOUNDARY, INTEGRATION, API, WEB, DATA, OTHER. Priority: LOW, MEDIUM, HIGH, CRITICAL. Steps use contiguous indices 1–20. Unknown expected behavior uses null and a MISSING_INFORMATION marker; required_evidence is an array of strings. information_markers contain kind and description. Formulas, scripts and links remain inert text.</p>
    </details>
    <form aria-label="Import Test Cases" onSubmit={submit}><fieldset disabled={action.busy}><legend>Existing test input</legend>
      <label htmlFor={id+'name'}>Import name</label><input id={id+'name'} name="name" required maxLength={200} />
      <label htmlFor={id+'format'}>Import format</label><select id={id+'format'} name="format"><option value="CSV">CSV</option><option value="MARKDOWN">Markdown</option></select>
      <label htmlFor={id+'content'}>Test case content</label><textarea id={id+'content'} name="content" required maxLength={65536} rows={8} />
      <button type="submit">{action.busy ? 'Importing…' : 'Import Test Cases'}</button>
    </fieldset><p role="status">{validation}{action.busy && 'Importing Test Cases…'}{action.result && <>Test import complete. Status: {action.result.status}. Cases: {action.result.test_count}.{action.result.error_code && <> Code: {action.result.error_code}.</>} Identical input may return an existing result, not new records.</>}</p>{action.error && <ErrorState error={action.error} />}</form>
  </section>;
}

export function PreparationGeneration({ projectId, campaignId, changed }: PreparationScope) {
  const requirements = useResource(useCallback(() => listRequirements(projectId,campaignId),[projectId,campaignId]));
  const action = usePreparationAction<TestGeneration>(), [selected,setSelected] = useState<string[]>([]), [validation,setValidation] = useState('');
  const eligible = new Set(requirements.data?.items.map(row => row.id));
  const chosen = [...new Set(selected)].filter(id => eligible.has(id));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (requirements.loading || requirements.error || !chosen.length || chosen.length > 20) { setValidation('Select 1–20 listed Requirements explicitly.'); return; }
    setValidation(''); await action.run(() => generateTests(projectId,campaignId,chosen), async result => { if (result.status === 'SUCCEEDED') await changed(); });
  }
  return <section id="test-generation" className="panel campaign-section"><h2>Generate from Requirements</h2><p className="hint">This explicit action may call the configured model. Select 1–20 Requirements. Nothing is selected automatically. Clarification markers carry forward into generated specifications; generation does not approve or execute tests.</p>
    {requirements.loading ? <LoadingState>Loading generation Requirements…</LoadingState> : requirements.error ? <ErrorState error={requirements.error} retry={() => void requirements.reload()} /> : requirements.data && <>
      {!requirements.data.items.length && <EmptyState>No Requirements to select. Add a specification and extract Requirements first.</EmptyState>}
      <form aria-label="Generate Test Specifications" onSubmit={submit}><fieldset disabled={action.busy}><legend>Explicit Requirement selection</legend>
        <div className="generation-selection">{requirements.data.items.map(row => <label key={row.id}><input type="checkbox" checked={chosen.includes(row.id)} disabled={!chosen.includes(row.id) && chosen.length >= 20}
          onChange={event => setSelected(current => event.target.checked ? [...new Set([...current,row.id])] : current.filter(id => id !== row.id))} />{row.logical_key} — {row.title} ({row.review_status})</label>)}</div>
        <p role="status">Selected: {chosen.length} of at most 20. The bounded list may omit other Requirements.</p>
        <button type="submit" disabled={!chosen.length}>{action.busy ? 'Generating…' : 'Generate Test Specifications'}</button>
      </fieldset><p role="status">{validation}{action.busy && 'Generating Test Specifications…'}{action.result && <>{action.result.status === 'SUCCEEDED' ? 'Test Specifications generated. Review is required.' : 'Test generation did not complete successfully.'} Status: {action.result.status}.{action.result.error_code && <> Code: {action.result.error_code}.</>} Equivalent selections may return an existing terminal attempt; unresolved attempts require operator attention.</>}</p>
      {action.error && <ErrorState error={action.error} />}</form><TruncationNotice truncated={requirements.data.truncated} />
    </>}
  </section>;
}
