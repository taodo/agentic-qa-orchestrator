import { useCallback, useEffect, useState, useRef } from 'react';
import { Link, Outlet, useOutletContext, useSearchParams } from 'react-router-dom';
import { campaignPath, getCampaign, getReadiness, getTraceability, listRequirements, listTestSpecifications, getRequirement, getTestSpecification } from '../api/campaigns';
import type { CampaignView, InformationMarker, TestMarker, CampaignReadiness as Readiness } from '../api/campaignTypes';
import { useResource } from '../app/useResource';
import { DateTime } from '../components/DateTime';
import { LoadingState, EmptyState, ErrorState, TruncationNotice } from '../components/Feedback';
import { CampaignStatusBadge } from '../components/CampaignStatusBadge';
import { CampaignReadiness } from '../components/CampaignReadiness';
import { PreparationRecovery } from '../components/PreparationRecovery';
import { PreparationSources } from '../components/PreparationSources';
import { PreparationReview } from '../components/PreparationReview';
import { PreparationImport, PreparationGeneration } from '../components/PreparationTests';
import { useWorkspaceContext } from '../app/WorkspaceContext';
import { PageHeader, SectionHeader } from '../components/WorkspaceUI';
import { CampaignTransition } from '../components/CampaignTransition';

interface CampaignContext { projectId: string; campaignId: string; campaign: CampaignView; base: string; readiness: ReturnType<typeof useResource<Readiness>>; transition: (value: CampaignView) => Promise<void> }
export function useCampaign() { return useOutletContext<CampaignContext>(); }
export function CampaignDetailPage({ projectId, campaignId }: { projectId: string; campaignId: string }) {
  const campaign = useResource(useCallback(() => getCampaign(projectId, campaignId), [projectId, campaignId]));
  const base = campaignPath(projectId, campaignId);
  return <><PageHeader title={campaign.data?.name || 'QA Campaign'} eyebrow="QA Campaign / Workspace"
    breadcrumb={<Link className="muted" to={`/projects/${encodeURIComponent(projectId)}`}>← Project Campaigns</Link>} />
    {campaign.loading ? <LoadingState>Loading Campaign…</LoadingState> : campaign.error ? <>
      {campaign.error.status === 404 && <h2>Campaign not found</h2>}
      <ErrorState error={campaign.error} retry={() => void campaign.reload()} /></> : campaign.data && <CampaignWorkspace initial={campaign.data} projectId={projectId} campaignId={campaignId} base={base} />}
  </>;
}

function CampaignWorkspace({ initial, projectId, campaignId, base }: { initial: CampaignView; projectId: string; campaignId: string; base: string }) {
  const [campaign,setCampaign] = useState(initial);
  const readiness = useResource(useCallback(() => getReadiness(projectId,campaignId),[projectId,campaignId]));
  async function transition(value: CampaignView) { setCampaign(value); await readiness.reload(); }
  useWorkspaceContext(projectId, campaignId, campaign.name);
  return <Outlet context={{ projectId,campaignId,campaign,base,readiness,transition } satisfies CampaignContext} />;
}

export function CampaignOverviewPage() {
  const { campaign, base, readiness, transition } = useCampaign();
  return <><section className="panel overview-panel"><SectionHeader title="Overview" /><p className="eyebrow">CAMPAIGN OBJECTIVE</p><p className="prose">{campaign.objective || 'No objective provided.'}</p>
    <dl className="metadata"><div><dt>Created</dt><dd><DateTime value={campaign.created_at} /></dd></div><div><dt>Updated</dt><dd><DateTime value={campaign.updated_at} /></dd></div></dl>
    <p className="hint">Inspect Requirements, Test Specifications and Traceability to understand saved preparation evidence.</p><CampaignTransition campaign={campaign} changed={transition} /></section>
    <div className="campaign-section"><SectionHeader title="Campaign readiness"><button disabled={readiness.loading} onClick={() => void readiness.reload()}>Refresh readiness</button></SectionHeader></div>
    {readiness.loading ? <LoadingState>Loading readiness…</LoadingState> : readiness.error ? <ErrorState error={readiness.error} retry={() => void readiness.reload()} />
      : readiness.data && <CampaignReadiness value={readiness.data} base={base} />}
  </>;
}

function Markers({ markers }: { markers: (InformationMarker | TestMarker)[] }) {
  return markers.length ? <div className="clarification"><h4>Clarification blockers</h4><ul>{markers.map((marker, index) =>
    <li key={index}><strong>{marker.kind.replaceAll('_', ' ').toLowerCase()}: </strong><span className="prose">{marker.description}</span></li>)}</ul></div> : null;
}

export function CampaignRequirementsPage() {
  const { projectId, campaignId, base, readiness } = useCampaign();
  const [params] = useSearchParams();
  const [feedback,setFeedback] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const selectedId = params.get('requirement_id');
  const requirements = useResource(useCallback(async () => {
    const list = await listRequirements(projectId, campaignId);
    if (!selectedId || list.items.some(item => item.id === selectedId)) return list;
    const selected = await getRequirement(projectId, campaignId, selectedId);
    return { ...list, items: [selected, ...list.items], selectedOutsideList: true };
  }, [projectId, campaignId, selectedId]));
  useEffect(() => { if (selectedId && requirements.data) document.getElementById(`requirement-${selectedId}`)?.focus(); }, [selectedId, requirements.data]);
  const traceability = useResource(useCallback(() => getTraceability(projectId, campaignId), [projectId, campaignId]));
  async function changed() { setFeedback('Requirement extraction completed; refreshing saved preparation data. Review remains explicit.'); await Promise.all([requirements.reload(), traceability.reload(), readiness.reload()]); heading.current?.focus(); }
  return <><p role="status">{feedback}</p><section className="panel campaign-section"><div className="panel-heading"><h2 ref={heading} tabIndex={-1}>Requirements</h2><button disabled={requirements.loading} onClick={() => { void requirements.reload(); void traceability.reload(); }}>Refresh Requirements</button><a className="button button--primary" href="#specification-sources">Add PRD / Spec</a></div>
    <p className="hint">Review status reflects saved human approval. Source citations support traceability; they do not imply approval.</p>
    {requirements.loading ? <LoadingState>Loading Requirements…</LoadingState> : requirements.error ? <ErrorState error={requirements.error} retry={() => void requirements.reload()} /> : requirements.data && <>
      {selectedId && <p>Selected Requirement <Link to={`${base}/requirements`}>Clear selection</Link></p>}
      {"selectedOutsideList" in requirements.data && <p className="hint">The selected Requirement is outside the bounded list and is included through a single detail read.</p>}
      {!requirements.data.items.length ? <EmptyState>No Requirements have been extracted yet.</EmptyState> : <ul className="preparation-records">{requirements.data.items.map(req => {
        const trace = !traceability.error && !traceability.loading ? traceability.data?.requirements.items.find(row => row.requirement_id === req.id) : undefined;
        return <li className="evidence-record" key={req.id} tabIndex={-1} id={`requirement-${req.id}`}><p className="record-key">{req.key}</p><p className="mono muted technical-id">{req.logical_key}</p>
          <div className="record-heading"><h3>{req.title}</h3><CampaignStatusBadge status={req.review_status} /></div><p className="prose">{req.description}</p>
          <p>{req.acceptance_criteria.length} acceptance criteria · {req.source_references.length} source references</p>
          <p className="coverage-inline">Coverage: {trace ? <CampaignStatusBadge status={trace.coverage} /> : <span className="muted">Not included in the current traceability response.</span>} <Link to={`${base}/traceability`}>Inspect Traceability</Link></p>
          {req.acceptance_criteria.length > 0 && <details open className="primary-detail"><summary>Acceptance criteria</summary><ul>{req.acceptance_criteria.map(item => <li key={item.key}><strong>{item.key}</strong> <span className="prose">{item.text}</span></li>)}</ul></details>}
          <Markers markers={req.information_markers} />
          <PreparationRecovery requirement={req} projectId={projectId} campaignId={campaignId} changed={changed} />
          <PreparationReview projectId={projectId} campaignId={campaignId} objectId={req.id} kind="Requirement" status={req.review_status} blocked={req.information_markers.length > 0} changed={async () => { setFeedback('Approval recorded.'); await Promise.all([requirements.reload(),traceability.reload(),readiness.reload()]); heading.current?.focus(); }} />
          <details><summary>Source evidence ({req.source_references.length})</summary><ul>{req.source_references.map((ref, index) => <li key={index}>
            <p>Source <code>{ref.source_id}</code> · lines {ref.start_line}–{ref.end_line}</p><blockquote className="prose">{ref.excerpt}</blockquote>
          </li>)}</ul></details>
        </li>;
      })}</ul>}
      <TruncationNotice truncated={requirements.data.truncated} />
      {traceability.error && <div className="campaign-section"><p>Coverage is unavailable; Requirement review and source evidence remain visible.</p><ErrorState error={traceability.error} retry={() => void traceability.reload()} /></div>}
      {traceability.data?.requirements.truncated && <p className="hint">Coverage comes from a bounded traceability list; missing rows are unknown, not coverage gaps.</p>}
    </>}
  </section><PreparationSources projectId={projectId} campaignId={campaignId} changed={changed} /></>;
}

export function CampaignTestsPage() {
  const { projectId, campaignId, base, readiness } = useCampaign();
  const [params] = useSearchParams();
  const [feedback,setFeedback] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const selectedId = params.get('test_spec_id');
  const tests = useResource(useCallback(async () => {
    const list = await listTestSpecifications(projectId, campaignId);
    if (!selectedId || list.items.some(item => item.id === selectedId)) return list;
    const selected = await getTestSpecification(projectId, campaignId, selectedId);
    return { ...list, items: [selected, ...list.items], selectedOutsideList: true };
  }, [projectId, campaignId, selectedId]));
  useEffect(() => { if (selectedId && tests.data) document.getElementById(`test-${selectedId}`)?.focus(); }, [selectedId, tests.data]);
  async function changed() { await Promise.all([tests.reload(),readiness.reload()]); heading.current?.focus(); }
  return <><p role="status">{feedback}</p><section className="panel"><div className="panel-heading"><h2 ref={heading} tabIndex={-1}>Test Specifications</h2><button disabled={tests.loading} onClick={() => void tests.reload()}>Refresh Test Specifications</button></div>
    <div className="actions"><a href="#test-import">Import Existing Tests</a><a href="#test-generation">Generate from Requirements</a></div>
    <p className="hint">Executor-neutral designs. Imported and AI-generated specifications share the same review rules.</p>
    {tests.loading ? <LoadingState>Loading Test Specifications…</LoadingState> : tests.error ? <ErrorState error={tests.error} retry={() => void tests.reload()} /> : tests.data && <>
      {selectedId && <p>Selected Test Specification <Link to={`${base}/test-specifications`}>Clear selection</Link></p>}
      {"selectedOutsideList" in tests.data && <p className="hint">The selected Test Specification is outside the bounded list and is included through a single detail read.</p>}
      {!tests.data.items.length ? <EmptyState>No Test Specifications have been imported or generated yet.</EmptyState> : <ul className="preparation-records">{tests.data.items.map(test => <li className="evidence-record" key={test.id} tabIndex={-1} id={`test-${test.id}`}>
        <p className="record-key">{test.key}</p><p className="mono muted technical-id">{test.logical_key}</p><div className="record-heading"><h3>{test.title}</h3><CampaignStatusBadge status={test.review_status} /></div>
        <dl className="metadata"><div><dt>Origin</dt><dd>{test.provenance.origin === 'IMPORT' ? 'Imported' : 'AI-generated'}</dd></div><div><dt>Test type</dt><dd>{test.test_type}</dd></div><div><dt>Priority</dt><dd>{test.priority}</dd></div>
          <div><dt>Linked Requirements</dt><dd>{test.requirement_ids.length}</dd></div><div><dt>Steps</dt><dd>{test.steps.length}</dd></div><div><dt>Expected result</dt><dd>{test.overall_expected_result === null ? 'Missing' : 'Provided'}</dd></div></dl>
        <Markers markers={test.information_markers} />
        <PreparationReview projectId={projectId} campaignId={campaignId} objectId={test.id} kind="Test Specification" status={test.review_status} blocked={test.information_markers.length > 0 || test.unresolved_requirement_refs.length > 0 || !test.requirement_ids.length || !test.required_evidence.length || test.overall_expected_result === null || test.steps.some(step => step.expected === null)} changed={async () => { setFeedback('Approval recorded.'); await changed(); }} />
        {test.unresolved_requirement_refs.length > 0 && <p className="notice prose">Unresolved Requirement references: {test.unresolved_requirement_refs.join(', ')}</p>}
        <details open className="primary-detail"><summary>Test design</summary>{test.preconditions.length > 0 && <><h4>Preconditions</h4><ul>{test.preconditions.map((item, index) => <li className="prose" key={index}>{item}</li>)}</ul></>}
          <h4>Steps and expected behavior</h4><ol className="test-steps">{test.steps.map(step => <li key={step.index}><p className="prose">{step.action}</p><p className="prose muted">Expected: {step.expected ?? 'Not specified; clarification required.'}</p></li>)}</ol>
          <h4>Overall expected result</h4><p className="prose">{test.overall_expected_result ?? 'Not specified; clarification required.'}</p>
          <h4>Required evidence</h4>{test.required_evidence.length ? <ul>{test.required_evidence.map((item, index) => <li className="prose" key={index}>{item}</li>)}</ul> : <p>Not specified; clarification required.</p>}
        </details><div className="requirement-links"><h4>Linked Requirements</h4>{test.requirement_ids.length ? <ul className="reference-chips">{test.requirement_ids.map(id => <li key={id}><Link to={`${base}/requirements?requirement_id=${encodeURIComponent(id)}`}>{id}</Link></li>)}</ul> : <p className="hint">No current Requirement links.</p>}</div>
        <details className="secondary-detail"><summary>Provenance and audit identity</summary><dl className="metadata"><div><dt>Record</dt><dd><code>{test.provenance.record_id}</code></dd></div><div><dt>Source hash</dt><dd><code>{test.provenance.content_hash}</code></dd></div><div><dt>Contract</dt><dd>{test.provenance.contract_version}</dd></div><div><dt>Source lines</dt><dd>{test.provenance.start_line == null ? 'Not applicable' : `${test.provenance.start_line}–${test.provenance.end_line}`}</dd></div></dl></details>
        <Link to={`${base}/traceability`}>Inspect Requirement links</Link>
      </li>)}</ul>}<TruncationNotice truncated={tests.data.truncated} />
    </>}
  </section><PreparationImport projectId={projectId} campaignId={campaignId} changed={changed} /><PreparationGeneration projectId={projectId} campaignId={campaignId} changed={changed} /></>;
}

export function CampaignTraceabilityPage() {
  const { projectId, campaignId, base } = useCampaign();
  const resource = useResource(useCallback(() => getTraceability(projectId, campaignId), [projectId, campaignId]));
  const names = useResource(useCallback(() => listRequirements(projectId, campaignId), [projectId, campaignId]));
  return <section className="panel"><div className="panel-heading"><h2>Traceability</h2><button disabled={resource.loading} onClick={() => { void resource.reload(); void names.reload(); }}>Refresh Traceability</button></div>
    <p className="hint">Only current preparation is represented; tests retired by Requirement revision do not count toward coverage. Coverage means linkage to approved test specifications. It does not represent execution results or code coverage.</p>
    {names.error && <p className="hint" role="status">Requirement names are unavailable. Requirement UUIDs identify the coverage rows.</p>}
    {resource.loading ? <LoadingState>Loading Traceability…</LoadingState> : resource.error ? <ErrorState error={resource.error} retry={() => void resource.reload()} /> : resource.data && <>
      {!resource.data.requirements.items.length ? <EmptyState>No Requirements to assess for traceability.</EmptyState> : <div className="campaign-table-scroll" role="region" aria-label="Requirement coverage table" tabIndex={0}>
        <table className="campaign-table"><caption>Requirement coverage — returned records</caption><thead><tr><th scope="col">Requirement</th><th scope="col">Review</th><th scope="col">Linked tests</th><th scope="col">Approved tests</th><th scope="col">Coverage</th></tr></thead>
          <tbody>{resource.data.requirements.items.map(row => {
            const req = (!names.error && !names.loading ? names.data?.items : undefined)?.find(item => item.id === row.requirement_id);
            const links = resource.data!.links.items.filter(item => item.requirement_id === row.requirement_id);
            return <tr key={row.requirement_id}><th scope="row"><Link to={`${base}/requirements?requirement_id=${encodeURIComponent(row.requirement_id)}`}>{req?.logical_key ?? row.requirement_id}</Link>{req && <p>{req.title}</p>}
              <details><summary>Returned test links ({links.length})</summary>{links.length ? <ul>{links.map(link => <li key={link.test_spec_id}><Link to={`${base}/test-specifications?test_spec_id=${encodeURIComponent(link.test_spec_id)}`}>{link.test_spec_id}</Link> <CampaignStatusBadge status={link.test_review_status} /></li>)}</ul>
                : <p>{row.linked_test_count === 0 ? 'No linked tests. This is a coverage gap.' : 'Links are not included in this bounded response.'}</p>}</details>
            </th><td><CampaignStatusBadge status={row.review_status} /></td><td>{row.linked_test_count === 0 ? '0 — coverage gap' : row.linked_test_count}</td><td>{row.approved_test_count}</td><td><CampaignStatusBadge status={row.coverage} /></td></tr>;
          })}</tbody></table>
      </div>}
      {resource.data.requirements.truncated && <p className="notice">Requirement coverage is bounded; additional Requirements are not shown. This is not a complete matrix.</p>}
      {resource.data.links.truncated && <p className="notice">Test links are bounded; additional links are not shown. Linked and approved counts include all stored links.</p>}
      {!names.error && !names.loading && names.data?.truncated && <p className="hint">Requirement names come from a bounded list; UUIDs identify rows whose names are not included.</p>}
    </>}
  </section>;
}

export function CampaignReadinessPage() {
  const { base, readiness } = useCampaign();
  return <><SectionHeader title="Readiness assessment"><button disabled={readiness.loading} onClick={() => void readiness.reload()}>Refresh readiness</button></SectionHeader>
    {readiness.loading ? <LoadingState>Loading readiness…</LoadingState> : readiness.error ? <ErrorState error={readiness.error} retry={() => void readiness.reload()} /> : readiness.data && <CampaignReadiness value={readiness.data} base={base} />}
  </>;
}
