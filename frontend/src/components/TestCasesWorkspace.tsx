import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { listTestSpecifications, getTestSpecification } from '../api/campaigns';
import type { CampaignTestSpecification } from '../api/campaignTypes';
import { useResource } from '../app/useResource';
import { DateTime } from './DateTime';
import { CampaignStatusBadge } from './CampaignStatusBadge';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from './Feedback';
import { PreparationRow } from './PreparationRow';
import { PreparationBulkApproval } from './RequirementBulkApproval';
import { PreparationReview } from './PreparationReview';
import { PreparationImport, PreparationGeneration } from './PreparationTests';
import type { PreparationScope } from './PreparationSources';
import { downloadTestCases } from './testCaseCsv';

function reviewBlocked(test:CampaignTestSpecification) {
  return !!(test.information_markers.length || test.unresolved_requirement_refs.length || !test.requirement_ids.length || !test.required_evidence.length || test.overall_expected_result===null || test.steps.some(step=>step.expected===null));
}
function TestCaseDetails({test,base,reviewable,...scope}:{test:CampaignTestSpecification;base:string;reviewable:boolean}&PreparationScope) {
  return <>
    <p className="mono muted">{test.id} · {test.logical_key}</p>
    <dl className="metadata"><div><dt>Origin</dt><dd>{test.provenance.origin==='IMPORT'?'Imported':'AI-generated'}</dd></div><div><dt>Created</dt><dd><DateTime value={test.created_at}/></dd></div><div><dt>Updated</dt><dd><DateTime value={test.updated_at}/></dd></div><div><dt>Expected result</dt><dd>{test.overall_expected_result===null?'Missing':'Provided'}</dd></div></dl>
    {test.information_markers.length>0 && <div className="clarification"><h4>Clarification blockers</h4><ul>{test.information_markers.map((marker,i)=><li key={i}><strong>{marker.kind.replaceAll('_',' ').toLowerCase()}: </strong><span className="prose">{marker.description}</span></li>)}</ul></div>}
    {test.unresolved_requirement_refs.length>0 && <p className="notice prose">Unresolved Requirement references: {test.unresolved_requirement_refs.join(', ')}</p>}
    {reviewable || test.review_status==='APPROVED' ? <PreparationReview {...scope} objectId={test.id} kind="Test Case" status={test.review_status} blocked={!reviewable || reviewBlocked(test)}/> : <p className="notice">Outside the returned current list: read-only audit content. Approval, selection and export are unavailable here.</p>}
    <h4>Preconditions</h4>{test.preconditions.length?<ul>{test.preconditions.map((item,i)=><li className="prose" key={i}>{item}</li>)}</ul>:<p>None specified.</p>}
    <h4>Steps and expected behavior</h4><ol className="test-steps">{test.steps.map(step=><li key={step.index}><p className="prose">{step.action}</p><p className="prose muted">Expected: {step.expected??'Not specified; clarification required.'}</p></li>)}</ol>
    <h4>Overall expected result</h4><p className="prose">{test.overall_expected_result??'Not specified; clarification required.'}</p>
    <h4>Required evidence</h4>{test.required_evidence.length?<ul>{test.required_evidence.map((item,i)=><li className="prose" key={i}>{item}</li>)}</ul>:<p>Not specified; clarification required.</p>}
    <h4>Linked Requirements</h4>{test.requirement_ids.length?<ul className="reference-chips">{test.requirement_ids.map(id=><li key={id}><Link to={`${base}/requirements?requirement_id=${encodeURIComponent(id)}`}>{id}</Link></li>)}</ul>:<p>No current Requirement links.</p>}
    <details className="secondary-detail"><summary>Provenance and audit identity</summary><dl className="metadata"><div><dt>Record</dt><dd><code>{test.provenance.record_id}</code></dd></div><div><dt>Source hash</dt><dd><code>{test.provenance.content_hash}</code></dd></div><div><dt>Contract</dt><dd>{test.provenance.contract_version}</dd></div><div><dt>Source lines</dt><dd>{test.provenance.start_line==null?'Not applicable':`${test.provenance.start_line}–${test.provenance.end_line}`}</dd></div></dl></details>
    <Link to={`${base}/traceability`}>Inspect Requirement links</Link>
  </>;
}
export function TestCasesWorkspace({projectId,campaignId,base,campaignName,reloadReadiness}:{projectId:string;campaignId:string;base:string;campaignName:string;reloadReadiness:()=>Promise<void>}) {
  const [params]=useSearchParams(), selectedId=params.get('test_spec_id'), location=useLocation();
  const [filter,setFilter]=useState('ALL'), [selected,setSelected]=useState<string[]>([]), [feedback,setFeedback]=useState('');
  const [importOpen,setImportOpen]=useState(location.hash==='#test-import'), [generationOpen,setGenerationOpen]=useState(location.hash==='#test-generation');
  useEffect(()=>{
    if(location.hash==='#test-import')setImportOpen(true);
    if(location.hash==='#test-generation')setGenerationOpen(true);
  },[location.hash]);
  const heading=useRef<HTMLHeadingElement>(null);
  const tests=useResource(useCallback(async()=>{
    const list=await listTestSpecifications(projectId,campaignId);
    const selectedDetail=selectedId && !list.items.some(test=>test.id===selectedId) ? await getTestSpecification(projectId,campaignId,selectedId):undefined;
    return {...list,selectedDetail};
  },[projectId,campaignId,selectedId]));
  useEffect(()=>{if(selectedId && tests.data)document.getElementById(`test-${selectedId}`)?.focus();},[selectedId,tests.data]);
  const current=!tests.loading && !tests.error ? tests.data?.items??[]:[];
  const visible=current.filter(test=>filter==='ALL' || test.review_status===filter);
  const chosen=visible.filter(test=>selected.includes(test.id));
  async function changed(){await Promise.all([tests.reload(),reloadReadiness()]);heading.current?.focus();}
  function exportCsv(scope:'visible'|'selected') {
    const cases=scope==='visible'?visible:chosen;if(!cases.length)return;
    try {downloadTestCases(cases,campaignName,scope);setFeedback(`Exported ${cases.length} ${scope} current Test Case(s). Only returned records were included.`);}
    catch {setFeedback('CSV export could not be created. No export request was sent.');}
  }
  const reviewScope={projectId,campaignId,changed:async()=>{setFeedback('Approval recorded.');await changed();}};
  return <><p role="status">{feedback}</p><section id="test-specification-results" className="panel"><div className="panel-heading"><h2 ref={heading} tabIndex={-1}>Test Cases</h2><button disabled={tests.loading} onClick={()=>void tests.reload()}>Refresh Test Cases</button></div>
    <div className="actions"><a href="#test-import" onClick={()=>setImportOpen(true)}>Import Existing Tests</a><Link to={`${base}/traceability`}>Design tests in Traceability</Link><a href="#test-generation" onClick={()=>setGenerationOpen(true)}>Secondary generation selection</a></div>
    <p className="hint">Executor-neutral Test Cases. Approval is human review, separate from coverage, Campaign readiness and execution results. Traceability is the primary AI generation workbench.</p>
    {tests.loading?<LoadingState>Loading Test Cases…</LoadingState>:tests.error?<ErrorState error={tests.error} retry={()=>void tests.reload()}/>:tests.data && <>
      {selectedId && <p>Selected Test Case <Link to={`${base}/test-specifications`}>Clear selection</Link></p>}
      <div className="actions" aria-label="Test Case status filters">{[['ALL','All'],['NEEDS_CLARIFICATION','Needs clarification'],['READY_FOR_REVIEW','Ready for review'],['APPROVED','Approved']].map(([value,label])=><button key={value} aria-pressed={filter===value} onClick={()=>{setFilter(value);setSelected([]);}}>{label} ({current.filter(test=>value==='ALL' || test.review_status===value).length})</button>)}</div>
      <p className="hint">Counts, selection and CSV exports cover returned current records only, never global Campaign totals. Approved cases can be selected for export but are never resubmitted for approval.</p>
      <div className="actions"><button onClick={()=>setSelected(visible.map(test=>test.id))}>Select all visible</button><button onClick={()=>setSelected([])}>Deselect all</button><span role="status">Selected: {chosen.length} visible current Test Cases.</span><button disabled={!visible.length} onClick={()=>exportCsv('visible')}>Export visible CSV</button><button disabled={!chosen.length} onClick={()=>exportCsv('selected')}>Export selected CSV</button></div>
    </>}
    <PreparationBulkApproval {...reviewScope} compact kind="Test Case" rows={visible.map(test=>({id:test.id,key:test.key,eligible:test.review_status==='READY_FOR_REVIEW' && !reviewBlocked(test)}))} selected={chosen.map(test=>test.id)}/>
    {!tests.loading && !tests.error && tests.data && <>
      {!visible.length?<EmptyState>No Test Cases in this view.</EmptyState>:<div className="campaign-table-scroll" role="region" aria-label="Test Cases table" tabIndex={0}><table className="campaign-table test-cases-table"><caption>Test Cases — returned current versions</caption><thead><tr>{['Select','Test Case','Requirement(s)','Type','Priority','Status','Steps','Actions'].map(label=><th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{visible.map(test=><PreparationRow key={test.id} id={`test-${test.id}`} initialOpen={selectedId===test.id}>{({open,setOpen,detailId})=><>
        <td><input type="checkbox" aria-label={`Select ${test.key}`} checked={chosen.some(item=>item.id===test.id)} onChange={event=>setSelected(event.target.checked?[...chosen.map(item=>item.id),test.id]:chosen.filter(item=>item.id!==test.id).map(item=>item.id))}/></td>
        <th scope="row"><span className="record-key">{test.key}</span><h3>{test.title}</h3></th><td>{test.requirement_ids.length} linked</td><td>{test.test_type}</td><td>{test.priority}</td><td><CampaignStatusBadge status={test.review_status}/></td><td>{test.steps.length}</td>
        <td><details id={detailId} open={open} onToggle={event=>setOpen(event.currentTarget.open)}><summary>Review / details</summary><TestCaseDetails {...reviewScope} test={test} base={base} reviewable/></details></td>
      </>}</PreparationRow>)}</tbody></table></div>}
      <TruncationNotice truncated={tests.data.truncated}/>{tests.data.truncated && <p className="notice">CSV exports are bounded to returned visible/selected current Test Cases. Additional Campaign cases are not included.</p>}
      {tests.data.selectedDetail && <section id={`test-${tests.data.selectedDetail.id}`} tabIndex={-1} aria-label="Selected Test Case audit detail"><h3>{tests.data.selectedDetail.title}</h3><p>The selected Test Case is outside the bounded current list and is included through a single detail read. It may be historical; it is read-only and excluded from table counts, selection, approval and CSV.</p><CampaignStatusBadge status={tests.data.selectedDetail.review_status}/><TestCaseDetails {...reviewScope} test={tests.data.selectedDetail} base={base} reviewable={false}/></section>}
    </>}
  </section><details id="test-import-actions" className="panel campaign-section" open={importOpen} onToggle={event=>setImportOpen(event.currentTarget.open)}><summary>Import Existing Tests</summary><PreparationImport projectId={projectId} campaignId={campaignId} changed={changed}/></details>
    <details id="test-generation-actions" className="panel campaign-section" open={generationOpen} onToggle={event=>setGenerationOpen(event.currentTarget.open)}><summary>Secondary generation selection</summary><PreparationGeneration projectId={projectId} campaignId={campaignId} changed={changed}/></details>
  </>;
}
