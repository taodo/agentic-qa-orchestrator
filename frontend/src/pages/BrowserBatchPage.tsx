import { useCallback,useEffect,useRef,useState } from 'react';
import { Link,useParams } from 'react-router-dom';
import { acknowledgeBrowserBatch,getBrowserBatch,listBrowserBatches,batchPagePath,type BrowserBatch } from '../api/browserBatches';
import { publicError,type ApiError } from '../api/client';
import { runsPath } from '../api/runs';
import { useCampaign } from './CampaignDetailPage';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { SectionHeader } from '../components/WorkspaceUI';
import { DateTime } from '../components/DateTime';
import { EmptyState,ErrorState,LoadingState,TruncationNotice } from '../components/Feedback';
const label=(value:string)=>({PASS:'Passed',FAIL:'Failed',NEEDS_ATTENTION:'Needs attention',PREPARATION_ERROR:'Preparation error',EXECUTION_ERROR:'Execution error',NOT_EXECUTED:'Not executed',READY:'Ready',PENDING:'Waiting',PREPARING:'Preparing',RUNNING:'Running',INTERRUPTED:'Interrupted',SKIP:'Skipped'}[value]??value);
const active=(batch:BrowserBatch)=>!batch.reconciliation_required && !batch.interruption_acknowledged_at && (batch.processing||batch.status==='CREATED'||batch.run?.execution_status==='CREATED'||batch.status==='COMPLETED' && !batch.run && batch.summary.runnable>0);
export function BrowserBatchHistoryPanel() {
 const {projectId:p,campaignId:c,base}=useCampaign();const history=useResource(useCallback(()=>listBrowserBatches(p,c),[p,c]));
 if(history.error?.code==='HTTP_ERROR')return null; // Public hosts do not mount real browser routes.
 return <section className="panel"><div className="panel-heading"><h2>Browser batches</h2><button disabled={history.loading} onClick={()=>void history.reload()}>Refresh browser batches</button></div>
 {history.loading?<LoadingState>Loading browser batches…</LoadingState>:history.error?<ErrorState error={history.error}/>:history.data && <>
 {!history.data.items.length?<EmptyState>No browser batches submitted.</EmptyState>:<ul>{history.data.items.map(batch=><li key={batch.id}><Link to={batchPagePath(base,batch.id)}>Browser batch · {batch.selected_count} selected</Link> · {batch.browser_mode==='HEADED'?'Headed':'Headless'} · Preparation {batch.status} · {batch.execution_status??'No execution Run'} {batch.qa_outcome && `· QA ${batch.qa_outcome}`} · <DateTime value={batch.created_at}/></li>)}</ul>}<TruncationNotice truncated={history.data.truncated}/></>}
 </section>;
}
export function BrowserBatchPage(){const {batchId=''}=useParams();return <BatchResults key={batchId} batchId={batchId}/>;}
export function BatchResults({batchId}:{batchId:string}) {
 const {projectId:p,campaignId:c,base}=useCampaign();const [after,setAfter]=useState(0),[batch,setBatch]=useState<BrowserBatch>(),[error,setError]=useState<ApiError>(),[loading,setLoading]=useState(true),[revision,setRevision]=useState(0);
 const requestGate=useRef(false),ack=usePreparationAction<BrowserBatch>();
 useEffect(()=>{
  let live=true,inflight=false,timer:ReturnType<typeof setTimeout>|undefined;const controller=new AbortController();setLoading(true);setError(undefined);setBatch(undefined);
  async function load(){if(!live||inflight)return;inflight=true;requestGate.current=true;
   try{const value=await getBrowserBatch(p,c,batchId,after,controller.signal);if(!live)return;setBatch(value);setError(undefined);setLoading(false);if(active(value))timer=setTimeout(()=>void load(),1500);}
   catch(failure){if(live){setError(publicError(failure));setLoading(false);}}
   finally{inflight=false;if(live)requestGate.current=false;}
  }
  void load();return()=>{live=false;controller.abort();if(timer)clearTimeout(timer);requestGate.current=false;};
 },[p,c,batchId,after,revision]);
 return <><Link to={base+'/results'}>← Results</Link><SectionHeader title="Browser batch Results"/>
 <button disabled={loading||requestGate.current} onClick={()=>setRevision(v=>v+1)}>Refresh saved batch</button>
 {loading?<LoadingState>Loading batch progress…</LoadingState>:error?<ErrorState error={error}/>:batch && <>
 <p>{batch.reconciliation_required?'Interrupted — review required':batch.processing?'Preparing / running':batch.run?.execution_status??(batch.status==='COMPLETED'?'Preparation complete':'Preparation '+batch.status)} · {batch.browser_mode==='HEADED'?'Headed':'Headless'}</p>
 <section className="panel" aria-label="Whole batch summary"><h2>All {batch.selected_count} selected tests</h2><dl className="metadata">{[['Runnable','runnable'],['Passed','passed'],['Failed','failed'],['Needs attention','needs_attention'],['Preparation errors','preparation_errors'],['Not evaluated','not_evaluated']].map(([title,key])=><div key={key}><dt>{title}</dt><dd>{batch.summary[key]??'Unavailable'}</dd></div>)}</dl>
 {batch.duration_seconds!==null && <p>Execution duration: {batch.duration_seconds.toFixed(2)} seconds</p>}
 {!batch.run && batch.status==='COMPLETED' && batch.summary.runnable===0 && <p>No runnable tests. No execution Run or QA outcome was created.</p>}
 {!batch.run && batch.status==='COMPLETED' && batch.summary.runnable>0 && <p>Runnable tests await Run materialization. No execution results have been recorded yet.</p>}
 <details className="secondary-detail"><summary>Immutable Target and audit context</summary><p>{batch.target_snapshot.name} · {batch.target_snapshot.environment}</p><p className="prose">{batch.target_snapshot.base_url}</p><p>Preparation: {batch.status}</p>{batch.run && <Link to={runsPath(p,c,batch.run.id)}>View sealed Run and runtime audit</Link>}</details></section>
 {batch.reconciliation_required && <aside className="notice"><h2>Review this interruption</h2><p>Uncertain browser/model work will not be replayed. Inspect saved results before explicitly starting another batch. Acknowledgement preserves STARTED history and never retries work.</p>
 {!batch.interruption_acknowledged_at && <button disabled={ack.busy||ack.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void ack.run(()=>acknowledgeBrowserBatch(p,c,batchId),async()=>{setRevision(v=>v+1);})}>Acknowledge reviewed interruption</button>}{ack.error && <ErrorState error={ack.error}/>}</aside>}
 <div className="campaign-table-scroll"><table className="campaign-table"><caption>Selected tests — preparation exceptions and execution evidence</caption><thead><tr><th>Test</th><th>Outcome</th><th>Result / next step</th><th>Evidence</th></tr></thead><tbody>{batch.items.items.map(item=><tr key={item.id}><th scope="row">{item.key}<h3>{item.title}</h3></th><td>{label(item.outcome)}</td><td>{item.reason && <p>{item.reason.replaceAll('_',' ').toLowerCase()}</p>}{item.affected_step!==null && <p>Step {item.affected_step}</p>}{item.hint && <p className="prose">{item.hint}</p>}{item.evidence?.items.map(evidence=><p key={evidence.id} className="prose">{evidence.summary}</p>)}</td><td>{item.run_test_id && batch.run?<><p>{item.evidence_count??'Unavailable'} saved evidence record(s)</p><Link to={runsPath(p,c,batch.run.id)}>Inspect execution evidence</Link></>:<p>No execution evidence</p>}</td></tr>)}</tbody></table></div>
 <div className="actions"><button disabled={after===0} onClick={()=>setAfter(0)}>First selected tests</button><button disabled={!batch.items.truncated} onClick={()=>setAfter(batch.items.items.at(-1)?.position??after)}>Next selected tests</button></div><TruncationNotice truncated={batch.items.truncated}/>
 </>}
 </>;
}
