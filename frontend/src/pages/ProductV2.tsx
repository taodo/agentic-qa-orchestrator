import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useCampaign, CampaignReadinessPage } from './CampaignDetailPage';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { candidates, listSpecifications, uploadDocument, editTest, exportTests, testEditEvidence, type ExecutionCandidate } from '../api/productV2';
import { extractRequirements, retryExtraction, listRequirements, generateTests } from '../api/campaigns';
import { createRun, startRun, listRuns, runsPath } from '../api/runs';
import type { CampaignSource, CampaignTestSpecification, RequirementExtraction, TestGeneration } from '../api/campaignTypes';
import { SectionHeader } from '../components/WorkspaceUI';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from '../components/Feedback';
import { PreparationBulkApproval, RequirementBulkApproval } from '../components/RequirementBulkApproval';
import { StateBadge } from '../components/StatusBadge';
import { AIActionSummary } from '../components/AIActionSummary';
import { DateTime } from '../components/DateTime';

export const designStatus = (status:string) => status==='READY_FOR_REVIEW'?'READY':status==='NEEDS_CLARIFICATION'?'NEEDS_INFO':status==='APPROVED'?'READY':status;
function DesignStatus({test}:{test:CampaignTestSpecification}) {return <><span className="badge">{designStatus(test.review_status)}</span><span className="muted"> {test.review_status==='APPROVED'?'Approved':'Not approved'}</span></>;}

export function SpecificationPage() {
  const {projectId:p,campaignId:c,base,readiness}=useCampaign();
  const sources=useResource(useCallback(()=>listSpecifications(p,c),[p,c]));
  const [file,setFile]=useState<File>(), [notice,setNotice]=useState('');
  const action=usePreparationAction<CampaignSource>();
  const alive=useRef(true);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  async function upload() {
    if(!file || action.busy)return;
    if(!/\.(pdf|docx|md|txt)$/i.test(file.name) || file.size>2*1024*1024){setNotice('Choose PDF, DOCX, Markdown or text up to 2 MiB. Text content is limited to 65,536 bytes.');return;}
    const selected=file;setNotice('');
    await action.run(async()=>{
      const bytes=new Uint8Array(await selected.arrayBuffer());
      if(!alive.current)throw new Error('Navigation ended upload');
      let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      return uploadDocument(p,c,selected.name,btoa(binary));
    },async()=>{setFile(undefined);await sources.reload();});
  }
  return <><SectionHeader title="Specification"/><p>Upload your specification, then explicitly analyze its supported product behavior. Uploading never calls AI.</p>
    <section className="panel upload-zone" onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();if(!action.busy)setFile(event.dataTransfer.files[0]);}}>
      <label>Specification file<input type="file" accept=".pdf,.docx,.md,.txt" disabled={action.busy} onChange={event=>setFile(event.target.files?.[0])}/></label>
      <p>Drop a PDF, DOCX, Markdown or text file here, or choose a file. Up to 2 MiB; extracted text stays bounded. Images and visual layouts are not analyzed.</p>
      {file && <p>{file.name} · {file.size.toLocaleString()} bytes</p>}
      <button className="button--primary" disabled={!file || action.busy || action.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void upload()}>{action.busy?'Processing specification…':'Upload specification'}</button>
      <p role="status">{notice}</p>{action.error && <ErrorState error={action.error}/>}</section>
    {sources.loading?<LoadingState>Loading specifications…</LoadingState>:sources.error?<ErrorState error={sources.error} retry={()=>void sources.reload()}/>:sources.data && <>
      {!sources.data.items.length && <EmptyState>Add a specification to begin test design.</EmptyState>}
      {sources.data.items.filter(source=>(source.purpose??'SPECIFICATION')==='SPECIFICATION' && !source.clarification_requirement_id).map(source=><section className="panel" key={source.id}>
        <h3>{source.name}</h3><p>{source.source_type} · {source.status==='INGESTED'?'Ready to analyze':'Not readable'} · {source.original_bytes.toLocaleString()} bytes · {source.line_count} normalized lines</p>
        {source.document && <p className="notice">{source.document.limitations.map(value=>value.replaceAll('_',' ').toLowerCase()).join('. ')}. Source coordinates preserve extracted text only.</p>}
        {source.status==='INGESTED'?<AnalyzeSource source={source} changed={async()=>{await Promise.all([sources.reload(),readiness.reload()]);}}/>:<p role="alert">{source.error_code}: upload a supported, readable specification.</p>}
      </section>)}<TruncationNotice truncated={sources.data.truncated}/></>}
    <Link className="button" to={base+'/test-design'}>Continue to Test Design</Link>
  </>;
}
function AnalyzeSource({source,changed}:{source:CampaignSource;changed:()=>Promise<void>}) {
  const {projectId:p,campaignId:c,base}=useCampaign();const action=usePreparationAction<RequirementExtraction>();
  const latest=action.result??source.latest_extraction;
  const allowed=!latest || latest.status==='FAILED' && latest.retryable;
  return <><button className="button--primary" disabled={!allowed || action.busy || action.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void action.run(()=>latest?retryExtraction(p,c,latest.id):extractRequirements(p,c,source.id),changed)}>{action.busy?'Analyzing…':latest?.status==='FAILED'?'Retry analysis (new AI call)':latest?.status==='SUCCEEDED'?'Analysis complete':'Analyze specification'}</button>
    {action.error && <ErrorState error={action.error}/>}{latest?.status==='FAILED' && <p role="alert">Analysis could not produce accepted findings. {latest.error_code}. No automatic retry.</p>}
    {latest?.status==='STARTED' && <p className="notice">Analysis completion is uncertain. Inspect Audit; do not replay it.</p>}
    {latest?.status==='SUCCEEDED' && <p role="status">Analysis saved. Review the supported findings in Test Design.</p>}
    {latest && <details><summary>Analysis audit</summary><AIActionSummary attempt={latest} kind="extraction" base={base} navigation={false}/></details>}
  </>;
}

function GenerateFromFindings({changed}:{changed:()=>Promise<void>}) {
  const {projectId:p,campaignId:c,base}=useCampaign();
  const findings=useResource(useCallback(()=>listRequirements(p,c),[p,c]));const [selected,setSelected]=useState<string[]>([]);
  const action=usePreparationAction<TestGeneration>();
  const rows=findings.data?.items??[];const approved=rows.filter(row=>selected.includes(row.id) && row.review_status==='APPROVED');
  async function refresh(){setSelected([]);await findings.reload();await changed();}
  return <details className="panel" open><summary>Generate test cases from supported findings</summary>
    <p>Review supported behavior before AI designs tests. Missing source facts remain unresolved; only explicitly approved findings are used. Choose up to 20 at a time.</p>
    {findings.loading?<LoadingState>Loading supported findings…</LoadingState>:findings.error?<ErrorState error={findings.error}/>:<>
      {!rows.length && <EmptyState>Analyze a specification first.</EmptyState>}
      {rows.map(row=><label key={row.id}><input type="checkbox" checked={selected.includes(row.id)} disabled={action.busy || !['APPROVED','READY_FOR_REVIEW'].includes(row.review_status) || row.information_markers.length>0 || (!selected.includes(row.id) && selected.length>=20)} onChange={e=>setSelected(e.target.checked?[...selected,row.id]:selected.filter(id=>id!==row.id))}/>{row.key} — {row.title} · {designStatus(row.review_status)}</label>)}
      <RequirementBulkApproval rows={rows} selected={selected} projectId={p} campaignId={c} changed={refresh}/>
      <p>Selected approved findings: {approved.length}. Approval is explicit human review, never AI approval.</p>
      <button className="button--primary" disabled={!approved.length || action.busy || action.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void action.run(()=>generateTests(p,c,approved.map(row=>row.id)),async result=>{if(result.status==='SUCCEEDED')await changed();})}>{action.busy?'Generating…':'Generate test cases'}</button>
      <TruncationNotice truncated={!!findings.data?.truncated}/><Link to={base+'/requirements'}>Inspect source findings / add missing information</Link>
    </>}{action.error && <ErrorState error={action.error}/>}{action.result && <p role="status">{action.result.status==='SUCCEEDED'?`Generated ${action.result.output?.generated_count??'an unknown number of'} test cases. Review remains explicit.`: `Generation ${action.result.status}. ${action.result.error_code??'Inspect Audit before continuing.'}`}</p>}
    {action.result && <details><summary>Generation audit</summary><AIActionSummary attempt={action.result} kind="generation" base={base} navigation={false}/></details>}
  </details>;
}

function useTestPage() {
  const {projectId:p,campaignId:c}=useCampaign();const [cursors,setCursors]=useState<string[]>([]);
  const after=cursors.at(-1);const data=useResource(useCallback(()=>candidates(p,c,after),[p,c,after]));
  return {data,first:()=>setCursors([]),next:()=>{const id=data.data?.items.at(-1)?.test.id;if(id)setCursors([...cursors,id]);},previous:()=>setCursors(cursors.slice(0,-1)),hasPrevious:!!cursors.length,after};
}
function Pagination({page,busy=false}:{page:ReturnType<typeof useTestPage>;busy?:boolean}) {
  return <div className="actions"><button disabled={!page.hasPrevious || busy || page.data.loading} onClick={page.previous}>Previous page</button><button disabled={!page.data.data?.truncated || busy || page.data.loading} onClick={page.next}>Next page</button><button disabled={!page.hasPrevious || busy || page.data.loading} onClick={page.first}>First page</button><p className="hint">At most 50 tests per page. Counts and select-all describe this page only.</p></div>;
}

export function TestDesignPage() {
  const {projectId:p,campaignId:c,base,readiness}=useCampaign();const page=useTestPage();const [selected,setSelected]=useState<string[]>([]),[search,setSearch]=useState(''),[filter,setFilter]=useState('ALL'),[notice,setNotice]=useState('');
  const exporting=usePreparationAction<Awaited<ReturnType<typeof exportTests>>>();
  useEffect(()=>setSelected([]),[page.after]);
  const visible=(page.data.data?.items??[]).filter(row=>(filter==='ALL' || (filter==='APPROVED'?row.test.review_status==='APPROVED':designStatus(row.test.review_status)===filter)) && (row.test.key+' '+row.test.title).toLowerCase().includes(search.toLowerCase()));
  const chosen=visible.filter(row=>selected.includes(row.test.id));
  async function changed(){setSelected([]);await Promise.all([page.data.reload(),readiness.reload()]);}
  async function download(format:'CSV'|'XLSX') {
    await exporting.run(()=>exportTests(p,c,chosen.map(row=>row.test.id),format),async result=>{
      const bytes=Uint8Array.from(atob(result.content_base64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:result.media_type}));const link=document.createElement('a');
      try{link.href=url;link.download=result.filename;document.body.appendChild(link);link.click();setNotice(`Exported ${result.count} selected cases as ${format}.`);}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),0);}
    });
  }
  return <><SectionHeader title="Test Design"/><p>Review, add information and approve the ready tests you need. Unresolved tests do not block unrelated ready work.</p>
    <section className="panel"><div className="actions"><label>Search this page<input value={search} onChange={e=>{setSearch(e.target.value);setSelected([]);}}/></label><label>Design status<select value={filter} onChange={e=>{setFilter(e.target.value);setSelected([]);}}>{['ALL','READY','NEEDS_INFO','DRAFT','APPROVED'].map(value=><option key={value}>{value}</option>)}</select></label><button disabled={page.data.loading} onClick={()=>void changed()}>Refresh tests</button></div>
      <div className="actions"><button onClick={()=>setSelected(visible.map(row=>row.test.id))}>Select visible</button><button onClick={()=>setSelected([])}>Clear selection</button><span role="status">Selected: {chosen.length} on this page</span><button disabled={!chosen.length || exporting.busy} onClick={()=>void download('CSV')}>Export CSV</button><button disabled={!chosen.length || exporting.busy} onClick={()=>void download('XLSX')}>Export XLSX</button></div>
      <p role="status">{notice}</p>{exporting.error && <ErrorState error={exporting.error}/>}
      <PreparationBulkApproval compact rows={visible.map(row=>({id:row.test.id,key:row.test.key,eligible:row.test.review_status==='READY_FOR_REVIEW' && !row.test.information_markers.length && !row.test.unresolved_requirement_refs.length && !!row.test.requirement_ids.length}))} selected={chosen.map(row=>row.test.id)} projectId={p} campaignId={c} changed={changed} kind="Test Case"/>
      {page.data.loading?<LoadingState>Loading test design…</LoadingState>:page.data.error?<ErrorState error={page.data.error}/>:!visible.length?<EmptyState>No tests on this page. Analyze a specification and generate cases, or adjust the page filter.</EmptyState>:<div className="campaign-table-scroll" role="region" aria-label="Test Design table" tabIndex={0}><table className="campaign-table"><thead><tr><th>Select</th><th>Test case</th><th>Priority</th><th>Status / approval</th><th>Review</th></tr></thead><tbody>{visible.map(row=><tr key={row.test.id}><td><input type="checkbox" aria-label={`Select ${row.test.key}`} checked={selected.includes(row.test.id)} onChange={e=>setSelected(e.target.checked?[...selected,row.test.id]:selected.filter(id=>id!==row.test.id))}/></td><th scope="row">{row.test.key}<h3>{row.test.title}</h3></th><td>{row.test.priority}</td><td><DesignStatus test={row.test}/></td><td><TestReview row={row} changed={changed}/></td></tr>)}</tbody></table></div>}
      <Pagination page={page}/>
    </section><GenerateFromFindings changed={changed}/><Link className="button" to={base+'/execution'}>Continue to Execution</Link></>;
}

function TestReview({row,changed}:{row:ExecutionCandidate;changed:()=>Promise<void>}) {
  const {projectId:p,campaignId:c,base}=useCampaign();const test=row.test;
  const [editing,setEditing]=useState(false),[title,setTitle]=useState(test.title),[steps,setSteps]=useState(test.steps),[expected,setExpected]=useState(test.overall_expected_result??''),[resolved,setResolved]=useState(false),[priority,setPriority]=useState(test.priority),[preconditions,setPreconditions]=useState(test.preconditions.join('\n')),[evidence,setEvidence]=useState(test.required_evidence.join('\n'));
  const action=usePreparationAction<CampaignTestSpecification>();
  const audit=usePreparationAction<Awaited<ReturnType<typeof testEditEvidence>>>();
  return <details><summary>{test.information_markers.length?'Add information':'Review / edit'}</summary>
    {test.information_markers.map((marker,i)=><p className="notice" key={i}>{marker.description}</p>)}
    <p>Expected result: {test.overall_expected_result??'Needs information'}</p><ol>{test.steps.map(step=><li key={step.index}>{step.action}<br/>Expected: {step.expected??'Needs information'}</li>)}</ol>
    <details><summary>Supporting source findings</summary>{test.requirement_ids.map((id,i)=><p key={id}><Link to={`${base}/requirements?requirement_id=${encodeURIComponent(id)}`}>View supporting finding {i+1} and its source evidence</Link></p>)}</details>
    {!row.eligible && <p className="hint">Execution: {row.reason}</p>}
    {!!test.unresolved_requirement_refs.length && <p className="notice">Resolve supporting source links in Audit before editing this test. Human facts cannot invent traceability.</p>}
    <button disabled={!!test.unresolved_requirement_refs.length} onClick={()=>setEditing(!editing)}>Edit / provide facts</button>{editing && <form aria-label={`Edit ${test.key}`} onSubmit={event=>{event.preventDefault();const data=new FormData(event.currentTarget);
      const {key,test_type,information_markers}=test;
      const required_evidence=evidence.split("\n").filter(Boolean), preconditionLines=preconditions.split("\n").filter(Boolean);
      void action.run(()=>editTest(p,c,test.id,{previous_hash:row.content_hash,reviewer_label:String(data.get('reviewer_label')),note:String(data.get('note')),
        design:{key,title,test_type,priority,preconditions:preconditionLines,steps,overall_expected_result:expected||null,required_evidence,information_markers:resolved?[]:information_markers}}),async()=>{setEditing(false);await changed();});
    }}><fieldset disabled={action.busy}><legend>Human-reviewed test version</legend><p>Saving creates a new version and requires fresh approval. Original PRD and earlier Run evidence stay unchanged. Enter facts, never credentials.</p>
      <label>Title<input value={title} maxLength={200} required onChange={e=>setTitle(e.target.value)}/></label>
      <label>Priority<select value={priority} onChange={e=>setPriority(e.target.value as typeof priority)}>{["LOW","MEDIUM","HIGH","CRITICAL"].map(value=><option key={value}>{value}</option>)}</select></label><label>Preconditions (one per line)<textarea value={preconditions} onChange={e=>setPreconditions(e.target.value)} maxLength={10240}/></label><label>Required evidence (one per line)<textarea value={evidence} onChange={e=>setEvidence(e.target.value)} maxLength={10240}/></label>
      {steps.map((step,i)=><div key={step.index}><label>Step {step.index}<textarea maxLength={2000} required value={step.action} onChange={e=>setSteps(steps.map((s,j)=>j===i?{...s,action:e.target.value}:s))}/></label><label>Expected for step {step.index}<textarea maxLength={2000} value={step.expected??''} onChange={e=>setSteps(steps.map((s,j)=>j===i?{...s,expected:e.target.value||null}:s))}/></label></div>)}
      <label>Overall expected result<textarea maxLength={4000} value={expected} onChange={e=>setExpected(e.target.value)}/></label><label>Reviewer label<input name="reviewer_label" required maxLength={64}/></label><label>Facts / reason for this change<textarea name="note" required maxLength={1000}/></label>
      {!!test.information_markers.length && <label><input type="checkbox" checked={resolved} onChange={e=>setResolved(e.target.checked)}/>The facts above resolve the listed missing information. Backend completeness and traceability checks still apply.</label>}
      <button disabled={action.error?.code==='HOST_AUTH_REQUIRED'} type="submit">{action.busy?'Saving…':'Save new test version'}</button></fieldset>{action.error && <ErrorState error={action.error}/>}</form>}
    <details><summary>Version / provenance audit</summary><p>{test.provenance.origin} · {test.logical_key}</p><p>Record: {test.provenance.record_id}</p><p>Source hash: {test.provenance.content_hash}</p>{test.provenance.origin==='HUMAN_EDIT' && <><button onClick={()=>void audit.run(()=>testEditEvidence(p,c,test.id))}>View human review evidence</button>{audit.error && <ErrorState error={audit.error}/>} {audit.result && <><p>Human-reviewed Version {audit.result.version}. Reviewer: {audit.result.reviewer_label}</p><p className="prose">{audit.result.note}</p><p>Human information source: {audit.result.source_id}. Previous test: {audit.result.previous_id}. Original PRD evidence is unchanged.</p></>}</>}</details>
  </details>;
}

export function ExecutionPage() {
  const {projectId:p,campaignId:c}=useCampaign();const page=useTestPage();const navigate=useNavigate();const [selected,setSelected]=useState<string[]>([]);
  const [intent,setIntent]=useState<{idempotency_key:string;test_specification_ids:string[]}>();const action=usePreparationAction<Awaited<ReturnType<typeof createRun>>>();

  const rows=page.data.data?.items??[];
  async function runSelected(){
    const body=intent??{idempotency_key:crypto.randomUUID(),test_specification_ids:[...selected]};setIntent(body);
    await action.run(()=>createRun(p,c,body),async run=>{
      // One explicit operator intent. A Start failure goes to persisted Run detail;
      // it never causes another Create or automatic Start retry.
      try{await startRun(p,c,run.id);}finally{navigate(runsPath(p,c,run.id));}
    });
  }
  return <><SectionHeader title="Execution"/><aside className="notice synthetic-notice"><strong>SYNTHETIC execution only</strong><p>No real application, browser or API is tested. Odd snapshot positions PASS; even positions FAIL.</p></aside>
    <section className="panel"><p>Select approved eligible tests. Whole-workspace readiness does not block unrelated eligible tests.</p>
      <div className="actions"><button disabled={!!intent || action.busy || new Set([...selected,...rows.filter(row=>row.eligible).map(row=>row.test.id)]).size>500} onClick={()=>setSelected([...new Set([...selected,...rows.filter(row=>row.eligible).map(row=>row.test.id)])])}>Select all eligible on this page</button><button disabled={!!intent || action.busy} onClick={()=>setSelected([])}>Clear selection</button><span role="status">Selected: {selected.length} across pages (maximum 500)</span>
      <button className="button--primary" disabled={(!selected.length && !intent) || action.busy || action.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void runSelected()}>{action.busy?'Creating / running…':intent?'Retry same create intent':'Run selected (Synthetic)'}</button></div>
      {intent && action.error && <><p>The request retains its immutable selection for explicit retry. Refresh/navigation never retries it.</p><button onClick={()=>{setIntent(undefined);setSelected([]);}}>New selection intent</button></>}
      {action.error && <ErrorState error={action.error}/>}
      {page.data.loading?<LoadingState>Loading execution candidates…</LoadingState>:page.data.error?<ErrorState error={page.data.error}/>:<div className="campaign-table-scroll"><table className="campaign-table"><thead><tr><th>Select</th><th>Test case</th><th>Eligibility</th></tr></thead><tbody>{rows.map(row=><tr key={row.test.id}><td><input type="checkbox" aria-label={`Run ${row.test.key}`} disabled={(!row.eligible && !selected.includes(row.test.id)) || (!selected.includes(row.test.id) && selected.length>=500) || !!intent || action.busy} checked={selected.includes(row.test.id)} onChange={e=>setSelected(e.target.checked?[...selected,row.test.id]:selected.filter(id=>id!==row.test.id))}/></td><th scope="row">{row.test.key} — {row.test.title}</th><td>{row.eligible?'Approved and eligible':row.reason}</td></tr>)}</tbody></table></div>}
      {!rows.length && !page.data.loading && <EmptyState>No current tests. Generate and approve tests in Test Design.</EmptyState>}<Pagination page={page} busy={!!intent || action.busy}/>
    </section></>;
}

export function ResultsPage() {
  const {projectId:p,campaignId:c}=useCampaign();const runs=useResource(useCallback(()=>listRuns(p,c),[p,c]));
  return <><SectionHeader title="Results"/><p>Saved immutable test selections and truthful SYNTHETIC outcomes. A test FAIL is a QA outcome; execution FAILED denotes a system problem.</p>
    <button disabled={runs.loading} onClick={()=>void runs.reload()}>Refresh saved results</button>
    {runs.loading?<LoadingState>Loading results…</LoadingState>:runs.error?<ErrorState error={runs.error}/>:runs.data && <>{!runs.data.items.length?<EmptyState>No Runs yet. Run selected approved tests in Execution.</EmptyState>:<section className="panel">{runs.data.items.map(run=><article key={run.id}><h3><Link to={runsPath(p,c,run.id)}>RUN-{String(run.run_number).padStart(3,'0')}</Link></h3><p>{run.test_count} selected tests · SYNTHETIC</p><p>Execution: <StateBadge status={run.execution_status}/> QA outcome: <StateBadge status={run.qa_outcome}/></p><DateTime value={run.created_at}/></article>)}</section>}<TruncationNotice truncated={runs.data.truncated}/></>}
  </>;
}
export function ProductOverviewPage() {
  const {base,readiness}=useCampaign();const value=readiness.data;
  return <><SectionHeader title="Overview"/><p>Specification → Test Design → Execution → Results</p><div className="content-grid">{[['Specification','Upload and analyze supported behavior','specification'],['Test Design','Review, clarify and approve selected cases','test-design'],['Execution','Run an immutable eligible selection','execution'],['Results','Inspect outcomes and evidence','results']].map(([title,description,path])=><section className="panel" key={path}><h3><Link to={base+'/'+path}>{title}</Link></h3><p>{description}</p></section>)}</div>
    {readiness.loading?<LoadingState>Loading workspace counts…</LoadingState>:readiness.error?<ErrorState error={readiness.error}/>:value && <dl className="metadata"><div><dt>Test Design</dt><dd>{value.total_test_specifications} current tests</dd></div><div><dt>Approved tests</dt><dd>{value.approved_test_specifications}</dd></div><div><dt>Source findings needing information</dt><dd>{value.clarification_requirements}</dd></div></dl>}
    <p className="hint">Whole-workspace readiness is available in Audit; it does not control a selected Run's eligibility.</p></>;
}
export function AuditPage() {const {base}=useCampaign();return <><SectionHeader title="Advanced / Audit"/><p>Persisted diagnostics and preparation evidence. Viewing this area never calls a provider.</p><nav className="actions"><Link to={base+'/requirements'}>Requirement versions / AI activity</Link><Link to={base+'/traceability'}>Traceability</Link><Link to={base+'/readiness'}>Whole-workspace readiness</Link><Link to={base+'/test-specifications'}>Legacy test detail / import</Link></nav><details><summary>Preparation readiness</summary><CampaignReadinessPage/></details></>;}
