import { useCallback, useEffect, useState, useRef } from 'react';
import { Link, Outlet, useOutletContext, useSearchParams } from 'react-router-dom';
import { campaignPath, getCampaign, getReadiness, getTraceability, listRequirements, generateTests, getRequirement } from '../api/campaigns';
import type { CampaignView, InformationMarker, TestMarker, RequirementExtraction, TestGeneration, CampaignReadiness as Readiness } from '../api/campaignTypes';
import { usePreparationAction } from '../app/usePreparationAction';
import { useResource } from '../app/useResource';
import { DateTime } from '../components/DateTime';
import { LoadingState, EmptyState, ErrorState, TruncationNotice } from '../components/Feedback';
import { CampaignStatusBadge } from '../components/CampaignStatusBadge';
import { CampaignReadiness } from '../components/CampaignReadiness';
import { AIActionSummary } from '../components/AIActionSummary';
import { PreparationRecovery } from '../components/PreparationRecovery';
import { PreparationSources } from '../components/PreparationSources';
import { RequirementBulkApproval } from '../components/RequirementBulkApproval';
import { PreparationReview } from '../components/PreparationReview';
import { TestCasesWorkspace } from '../components/TestCasesWorkspace';
import { PreparationRow } from '../components/PreparationRow';
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
    <p className="hint">Inspect Requirements, Test Cases and Traceability to understand saved preparation evidence.</p><CampaignTransition campaign={campaign} changed={transition} /></section>
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
  const [aiResult,setAIResult] = useState<{attempt:RequirementExtraction;kind:'extraction'|'revision'}>();
  const { projectId, campaignId, base, readiness } = useCampaign();
  const [params] = useSearchParams();
  const [feedback,setFeedback] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const selectedId = params.get('requirement_id');
  const [filter,setFilter] = useState('ALL'), [selected,setSelected] = useState<string[]>([]);
  const requirements = useResource(useCallback(async () => {
    const list = await listRequirements(projectId, campaignId);
    const currentIds=list.items.map(row=>row.id);
    if (!selectedId || list.items.some(item => item.id === selectedId)) return {...list,currentIds};
    const selected = await getRequirement(projectId, campaignId, selectedId);
    return { ...list, currentIds, items: [selected, ...list.items], selectedOutsideList: true };
  }, [projectId, campaignId, selectedId]));
  useEffect(() => { if (selectedId && requirements.data) document.getElementById(`requirement-${selectedId}`)?.focus(); }, [selectedId, requirements.data]);
  const traceability = useResource(useCallback(() => getTraceability(projectId, campaignId), [projectId, campaignId]));
  const visible=(!requirements.loading && !requirements.error ? requirements.data?.items ?? [] : []).filter(row=>filter==='ALL' || row.review_status===filter);
  const currentIds=new Set(requirements.data?.currentIds);
  const chosen=[...new Set(selected)].filter(id=>visible.some(row=>row.id===id) && currentIds.has(id));
  async function changed() { setFeedback('Requirement extraction completed; refreshing saved preparation data. Review remains explicit.'); await Promise.all([requirements.reload(), traceability.reload(), readiness.reload()]); heading.current?.focus(); }
  return <><p role="status">{feedback}</p><section id="requirement-results" className="panel campaign-section"><div className="panel-heading"><h2 ref={heading} tabIndex={-1}>Requirements</h2><button disabled={requirements.loading} onClick={() => { void requirements.reload(); void traceability.reload(); }}>Refresh Requirements</button><a className="button button--primary" href="#specification-sources">Add PRD / Spec</a></div>
    {aiResult && <AIActionSummary attempt={aiResult.attempt} kind={aiResult.kind} base={base} />}
    <p className="hint">Review status reflects saved human approval. Source citations support traceability; they do not imply approval.</p>
    {requirements.loading ? <LoadingState>Loading Requirements…</LoadingState> : requirements.error ? <ErrorState error={requirements.error} retry={() => void requirements.reload()} /> : requirements.data && <>
      {selectedId && <p>Selected Requirement <Link to={`${base}/requirements`}>Clear selection</Link></p>}
      {"selectedOutsideList" in requirements.data && <p className="hint">The selected Requirement is outside the bounded list and is included through a single detail read.</p>}
      <div className="actions" aria-label="Requirement status filters">{[['ALL','All'],['NEEDS_CLARIFICATION','Needs clarification'],['READY_FOR_REVIEW','Ready for review'],['APPROVED','Approved']].map(([value,label])=><button key={value} aria-pressed={filter===value} onClick={()=>{setFilter(value);setSelected([]);}}>{label} ({requirements.data!.items.filter(row=>currentIds.has(row.id) && (value==='ALL' || row.review_status===value)).length})</button>)}</div>
      <p className="hint">Counts describe returned current Requirements only; they are not global totals.</p>
      <div className="actions"><button onClick={()=>setSelected(visible.filter(row=>currentIds.has(row.id) && row.review_status!=='APPROVED').map(row=>row.id))}>Select all visible</button><button onClick={()=>setSelected([])}>Deselect all</button><span role="status">Selected: {chosen.length} visible current Requirements.</span></div>
      {!visible.length ? <EmptyState>No Requirements in this view.</EmptyState> : <div className="campaign-table-scroll" role="region" aria-label="Requirements table" tabIndex={0}><table className="campaign-table requirements-table"><caption>Requirements — returned current versions; explicitly selected history is read-only</caption>
        <thead><tr><th scope="col">Select</th><th scope="col">Requirement</th><th scope="col">Status</th><th scope="col">Acceptance criteria</th><th scope="col">Coverage</th><th scope="col">Actions / details</th></tr></thead><tbody>{visible.map(req=>{
        const trace = !traceability.error && !traceability.loading ? traceability.data?.requirements.items.find(row=>row.requirement_id===req.id) : undefined;
        return <PreparationRow key={req.id} id={`requirement-${req.id}`} initialOpen={selectedId===req.id}>{({open,setOpen,detailId})=><><td><input type="checkbox" aria-label={`Select ${req.key}`} disabled={!currentIds.has(req.id) || req.review_status==='APPROVED'} checked={chosen.includes(req.id)} onChange={event=>setSelected(event.target.checked?[...chosen,req.id]:chosen.filter(id=>id!==req.id))}/></td>
          <th scope="row"><span className="record-key">{req.key}</span><h3>{req.title}</h3></th><td><CampaignStatusBadge status={req.review_status}/></td><td>{req.acceptance_criteria.length}</td>
          <td>{trace ? <CampaignStatusBadge status={trace.coverage}/> : <span className="muted">Not included in the current traceability response.</span>}</td>
          <td><details id={detailId} open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>{req.review_status==='NEEDS_CLARIFICATION' ? 'Add info / Clarify' : 'Review / details'}</summary><p className="prose">{req.description}</p><p className="mono muted">{req.id} · {req.logical_key}</p>
          <p>{req.acceptance_criteria.length} acceptance criteria · {req.source_references.length} source references</p>
          {!currentIds.has(req.id) && <p className="notice">This detail is outside the current bounded list. Approval and selection are unavailable here.</p>}
          {req.acceptance_criteria.length > 0 && <details open className="primary-detail"><summary>Acceptance criteria</summary><ul>{req.acceptance_criteria.map(item => <li key={item.key}><strong>{item.key}</strong> <span className="prose">{item.text}</span></li>)}</ul></details>}
          <Markers markers={req.information_markers} />
          {currentIds.has(req.id) && <><PreparationRecovery requirement={req} projectId={projectId} campaignId={campaignId} changed={changed} onRevision={attempt=>setAIResult({attempt,kind:'revision'})} />
          <PreparationReview projectId={projectId} campaignId={campaignId} objectId={req.id} kind="Requirement" status={req.review_status} blocked={req.information_markers.length > 0} changed={async () => { setFeedback('Approval recorded.'); await Promise.all([requirements.reload(),traceability.reload(),readiness.reload()]); heading.current?.focus(); }} /></>}
          <details><summary>Source evidence ({req.source_references.length})</summary><ul>{req.source_references.map((ref, index) => <li key={index}>
            <p>Source <code>{ref.source_id}</code> · lines {ref.start_line}–{ref.end_line}</p><blockquote className="prose">{ref.excerpt}</blockquote>
          </li>)}</ul></details>
          </details></td></>}</PreparationRow>;
      })}</tbody></table></div>}
      <TruncationNotice truncated={requirements.data.truncated} />
      {traceability.error && <div className="campaign-section"><p>Coverage is unavailable; Requirement review and source evidence remain visible.</p><ErrorState error={traceability.error} retry={() => void traceability.reload()} /></div>}
      {traceability.data?.requirements.truncated && <p className="hint">Coverage comes from a bounded traceability list; missing rows are unknown, not coverage gaps.</p>}
    </>}
    <RequirementBulkApproval projectId={projectId} campaignId={campaignId} rows={visible.filter(row=>currentIds.has(row.id))} selected={chosen} changed={async()=>{await Promise.all([requirements.reload(),traceability.reload(),readiness.reload()]);heading.current?.focus();}} />
  </section><PreparationSources projectId={projectId} campaignId={campaignId} changed={changed} onResult={(attempt,kind)=>{if(attempt.status==='SUCCEEDED')setAIResult({attempt,kind});}} /></>;
}

export function CampaignTestsPage() {
  const {projectId,campaignId,base,campaign,readiness}=useCampaign();
  return <TestCasesWorkspace projectId={projectId} campaignId={campaignId} base={base} campaignName={campaign.name} reloadReadiness={readiness.reload}/>;
}

export function CampaignTraceabilityPage() {
  const { projectId, campaignId, base, readiness } = useCampaign();
  const resource = useResource(useCallback(() => getTraceability(projectId, campaignId), [projectId, campaignId]));
  const names = useResource(useCallback(() => listRequirements(projectId, campaignId), [projectId, campaignId]));
  const action=usePreparationAction<TestGeneration>();
  const [selected,setSelected]=useState<string[]>([]), [dismissed,setDismissed]=useState<string>();
  const resultHeading=useRef<HTMLHeadingElement>(null);
  const rows=!resource.loading && !resource.error ? resource.data?.requirements.items ?? [] : [];
  const eligible=rows.filter(row=>row.review_status==='APPROVED').map(row=>row.requirement_id);
  const chosen=[...new Set(selected)].filter(id=>eligible.includes(id)).slice(0,20);
  useEffect(()=>{if(action.result)resultHeading.current?.focus();},[action.result]);
  async function generate(ids:string[]) {
    if(action.busy || !ids.length || ids.length>20 || ids.some(id=>!eligible.includes(id)))return;
    setDismissed(undefined);
    await action.run(()=>generateTests(projectId,campaignId,ids),async result=>{
      if(result.status==='SUCCEEDED')await Promise.all([resource.reload(),names.reload(),readiness.reload()]);
    });
  }
  return <section className="panel"><div className="panel-heading"><h2>Traceability</h2><button disabled={resource.loading || action.busy} onClick={() => { void resource.reload(); void names.reload(); }}>Refresh Traceability</button></div>
    <h3>Test Design Workbench</h3><p className="hint">Generate only from current APPROVED Requirements. One explicit attempt may call the model; generation does not approve or execute tests.</p>
    <p className="hint">Only current preparation is represented; tests retired by Requirement revision do not count toward coverage. Coverage means linkage to approved test cases. It does not represent execution results or code coverage.</p>
    {names.error && <p className="hint" role="status">Requirement names are unavailable. Requirement UUIDs identify the coverage rows.</p>}
    {action.error && <ErrorState error={action.error}/>}
    {action.busy && <p role="status">Generating Test Cases…</p>}
    {action.result && dismissed!==action.result.id && <section aria-label="Generation completion" className="campaign-section"><h3 ref={resultHeading} tabIndex={-1}>Test generation {action.result.status==='SUCCEEDED' ? 'completed' : action.result.status==='FAILED' ? 'FAILED' : 'started'}</h3>
      <AIActionSummary attempt={action.result} kind="generation" base={base} navigation={false}/>
      {action.result.status==='SUCCEEDED' && <div className="actions"><Link className="button button--primary" to={`${base}/test-specifications#test-specification-results`}>Go to Test Cases</Link><button onClick={()=>setDismissed(action.result!.id)}>Stay on Traceability</button></div>}
    </section>}
    <div className="actions"><button disabled={action.busy || !eligible.length} onClick={()=>setSelected(eligible.slice(0,20))}>Select all approved visible</button><button disabled={action.busy} onClick={()=>setSelected([])}>Deselect all</button>
      <span role="status">Selected: {chosen.length} of at most 20.</span><button disabled={action.busy || !chosen.length} onClick={()=>void generate(chosen)}>Generate tests for selected</button></div>
    {eligible.length>20 && <p className="notice">More than 20 approved rows are visible. Select all takes only the first 20 in displayed order; narrow selection for another batch.</p>}
    {resource.loading ? <LoadingState>Loading Traceability…</LoadingState> : resource.error ? <ErrorState error={resource.error} retry={() => void resource.reload()} /> : resource.data && <>
      {!resource.data.requirements.items.length ? <EmptyState>No Requirements to assess for traceability.</EmptyState> : <div className="campaign-table-scroll" role="region" aria-label="Requirement coverage table" tabIndex={0}>
        <table className="campaign-table"><caption>Requirement coverage — returned records</caption><thead><tr><th scope="col">Requirement</th><th scope="col">Review</th><th scope="col">Linked tests</th><th scope="col">Approved tests</th><th scope="col">Coverage</th><th scope="col">Select / generate</th></tr></thead>
          <tbody>{resource.data.requirements.items.map(row => {
            const req = (!names.error && !names.loading ? names.data?.items : undefined)?.find(item => item.id === row.requirement_id);
            const links = resource.data!.links.items.filter(item => item.requirement_id === row.requirement_id);
            return <tr key={row.requirement_id}><th scope="row"><Link to={`${base}/requirements?requirement_id=${encodeURIComponent(row.requirement_id)}`}>{req?.key ?? row.requirement_id}</Link>{req && <p>{req.title}</p>}
              <details><summary>Returned test links ({links.length})</summary><p className="mono muted">{row.requirement_id}{req && <> · {req.logical_key}</>}</p>{links.length ? <ul>{links.map(link => <li key={link.test_spec_id}><Link to={`${base}/test-specifications?test_spec_id=${encodeURIComponent(link.test_spec_id)}`}>{link.test_spec_id}</Link> <CampaignStatusBadge status={link.test_review_status} /></li>)}</ul>
                : <p>{row.linked_test_count === 0 ? 'No linked tests. This is a coverage gap.' : 'Links are not included in this bounded response.'}</p>}</details>
            </th><td><CampaignStatusBadge status={row.review_status} /></td><td>{row.linked_test_count === 0 ? '0 — coverage gap' : row.linked_test_count}</td><td>{row.approved_test_count}</td><td><CampaignStatusBadge status={row.coverage} /></td><td><label><input type="checkbox" aria-label={`Select ${req?.key ?? row.requirement_id} for generation`} checked={chosen.includes(row.requirement_id)} disabled={action.busy || row.review_status!=='APPROVED' || (!chosen.includes(row.requirement_id) && chosen.length>=20)} onChange={event=>setSelected(event.target.checked?[...chosen,row.requirement_id]:chosen.filter(id=>id!==row.requirement_id))}/>Select</label>
              <button disabled={action.busy || row.review_status!=='APPROVED'} onClick={()=>void generate([row.requirement_id])}>Generate Tests</button>{row.review_status!=='APPROVED' && <p className="hint">Approve this Requirement before generating tests.</p>}</td></tr>;
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
