import { act,fireEvent,render,screen,waitFor,within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach,expect,it,vi } from 'vitest';
import { App } from '../app/App';
import { campaign,readiness,specification } from '../test/campaigns';
import { response,page,project,deferred } from '../test/fixtures';
const base=`/projects/${campaign.project_id}/campaigns/${campaign.id}`,api='/api/v1'+base;
const test={...specification,requirement_ids:[],preconditions:[]};
const capability={planning:'AVAILABLE',execution:'AVAILABLE',automatic:'AVAILABLE',source_free_review:'AVAILABLE',local_operator_review:'AVAILABLE',automatic_reason:null};
const target={schema_version:'web-target-snapshot-v1',target_id:'target',project_id:project.id,name:'Frozen target',type:'WEB',environment:'LOCAL',base_url:'https://generic.invalid'};
const item=(id:string,outcome:string)=>({id,test_id:id,position:Number(id),key:'CASE-'+id,title:'Case '+id,preparation_status:outcome==='NEEDS_ATTENTION'?'NEEDS_ATTENTION':'RUNNABLE',outcome,reason:outcome==='NEEDS_ATTENTION'?'GROUNDING_UNAVAILABLE':null,affected_step:outcome==='NEEDS_ATTENTION'?1:null,hint:outcome==='NEEDS_ATTENTION'?'Provide a visible supported control in the Test intent.':null,run_test_id:null,execution_status:null,qa_result:null,evidence_count:null,evidence:null});
const batch={id:'batch-a',project_id:project.id,campaign_id:campaign.id,status:'COMPLETED',browser_mode:'HEADLESS',target_snapshot:target,selected_count:3,summary:{runnable:2,passed:1,failed:1,needs_attention:1,preparation_errors:0,not_evaluated:0},run:{id:'run',execution_status:'COMPLETED',qa_outcome:'FAIL'},processing:false,reconciliation_required:false,interruption_acknowledged_at:null,duration_seconds:2,items:page([item('1','FAIL'),item('2','PASS'),item('3','NEEDS_ATTENTION')])};
function routes(extra:(url:string,options?:RequestInit)=>Response|Promise<Response>|undefined=()=>undefined){vi.mocked(fetch).mockImplementation(async(input,options)=>{
 const url=String(input),special=extra(url,options);if(special)return special;
 if(url===api)return response(campaign);if(url===api+'/readiness')return response(readiness);
 if(url===api+'/browser/capability')return response(capability);
 if(url.includes('/execution-candidates?'))return response(page([{test,content_hash:'a'.repeat(64),eligible:false,reason:'Missing legacy traceability'}]));
 if(url.includes('/test-design?'))return response({items:[{test,content_hash:'a'.repeat(64),approvable:false}],total:1,page:1,total_pages:1,page_size:10});
 if(url===api+'/requirements?limit=50')return response(page([]));
 if(url.startsWith(api+'/browser/batches/batch-a?'))return response(batch);
 return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
function open(path:string){return render(<MemoryRouter initialEntries={[base+'/'+path]}><App/></MemoryRouter>);}
const writes=()=>vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST');
afterEach(()=>vi.useRealTimers());
it('runs imported no-Spec approved tests through the normal Headless dialog once, without technical ceremony',async()=>{
 const pending=deferred<Response>();routes((url,options)=>url===api+'/browser/batches' && options?.method==='POST'?pending.promise:undefined);
 open('execution');fireEvent.click(await screen.findByRole('checkbox',{name:'Run PAY'}));
 const primary=await screen.findByRole('button',{name:'Run selected'});expect(primary).toBeEnabled();
 expect(screen.queryByRole('button',{name:'Run selected (Synthetic)'})).not.toBeInTheDocument();
 expect(document.querySelector('details')?.open).toBe(false);
 fireEvent.click(primary);const dialog=screen.getByRole('dialog');expect(within(dialog).getByLabelText('Headless')).toBeChecked();
 fireEvent.click(within(dialog).getByRole('button',{name:'Run'}));fireEvent.click(within(dialog).getByRole('button',{name:'Submitting…'}));
 await waitFor(()=>expect(writes()).toHaveLength(1));expect(JSON.parse(writes()[0][1]!.body as string)).toEqual({idempotency_key:expect.any(String),test_specification_ids:[test.id],browser_mode:'HEADLESS'});
 await act(async()=>pending.resolve(response(batch)));await screen.findByRole('heading',{name:'Browser batch Results'});
 expect(writes()).toHaveLength(1);expect(screen.getByText('All 3 selected tests')).toBeInTheDocument();
 expect(screen.getByText('Needs attention',{selector:'td'})).toBeInTheDocument();expect(screen.getByText('Step 1')).toBeInTheDocument();
 expect(screen.getByText('Provide a visible supported control in the Test intent.')).toBeInTheDocument();
 expect(screen.getByText('Failed',{selector:'td'})).toBeInTheDocument();expect(screen.getByText('Passed',{selector:'td'})).toBeInTheDocument();
});
it('persists Headed selection and explicit same-key retry; never auto-retries',async()=>{
 routes((url,options)=>url===api+'/browser/batches' && options?.method==='POST'?response({error:{code:'BROWSER_BATCH_NOT_CONFIGURED',message:'Configure the runtime'}},409):undefined);
 open('execution');fireEvent.click(await screen.findByRole('checkbox',{name:'Run PAY'}));fireEvent.click(await screen.findByRole('button',{name:'Run selected'}));
 fireEvent.click(screen.getByLabelText('Headed'));fireEvent.click(screen.getByRole('button',{name:'Run'}));await screen.findByText('BROWSER_BATCH_NOT_CONFIGURED');
 expect(writes()).toHaveLength(1);fireEvent.click(screen.getByRole('button',{name:'Retry same request'}));await waitFor(()=>expect(writes()).toHaveLength(2));
 expect(writes()[1][1]!.body).toBe(writes()[0][1]!.body);expect(JSON.parse(writes()[0][1]!.body as string).browser_mode).toBe('HEADED');
});
it('offers Import/Generate alternatives and human source-free approval rather than inventing a Requirement',async()=>{
 const needs={...test,review_status:'NEEDS_CLARIFICATION',information_markers:[{kind:'MISSING_TRACEABILITY',description:'No Specification links'}]};
 routes(url=>url.includes('/test-design?')?response({items:[{test:needs,content_hash:'a'.repeat(64),approvable:false}],total:1,page:1,total_pages:1,page_size:10}):undefined);
 open('test-design');await screen.findByRole('heading',{name:test.title});
 expect(screen.getByRole('link',{name:'Import Test Cases'})).toHaveAttribute('href',base+'/test-specifications#test-import');
 expect(screen.getByRole('link',{name:'Generate from Specs'})).toBeInTheDocument();
 fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));expect(screen.getByRole('button',{name:'Approve selected (1)'})).toBeEnabled();
 expect(writes()).toHaveLength(0);expect(screen.getByRole('button',{name:'Run selected'})).toBeDisabled();
});
it('shows zero-runnable preparation truth without inventing PASS or a Run',async()=>{
 routes(url=>url.startsWith(api+'/browser/batches/batch-a?')?response({...batch,selected_count:1,run:null,summary:{runnable:0,passed:0,failed:0,needs_attention:1,preparation_errors:0,not_evaluated:0},items:page([item('1','NEEDS_ATTENTION')])}):undefined);
 open('browser-batches/batch-a');await screen.findByText('No runnable tests. No execution Run or QA outcome was created.');expect(writes()).toHaveLength(0);
});
it('stops terminal polling, suppresses late responses after navigation and never overlaps pending polls',async()=>{
 const pending=deferred<Response>();let reads=0;
 routes(url=>url.startsWith(api+'/browser/batches/batch-a?')?(reads++,pending.promise):undefined);
 const view=open('browser-batches/batch-a');await waitFor(()=>expect(reads).toBe(1));vi.useFakeTimers();await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});expect(reads).toBe(1);
 view.unmount();await act(async()=>pending.resolve(response(batch)));await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});expect(reads).toBe(1);expect(screen.queryByText('Case 1')).not.toBeInTheDocument();
});
it('requires explicit acknowledgement for interruption and never retries grounding or Start',async()=>{
 routes(url=>url.startsWith(api+'/browser/batches/batch-a?')?response({...batch,status:'PREPARING',run:null,reconciliation_required:true}):undefined);
 open('browser-batches/batch-a');await screen.findByRole('button',{name:'Acknowledge reviewed interruption'});expect(writes()).toHaveLength(0);expect(screen.getByText(/Uncertain browser\/model work will not be replayed/)).toBeInTheDocument();
});

it('warns without blocking large Headed selections',async()=>{
 const tests=Array.from({length:30},(_,n)=>({test:{...test,id:'selected-'+n,key:'CASE'+n},content_hash:'a'.repeat(64),eligible:false,reason:'No legacy links'}));
 routes(url=>url.includes('/execution-candidates?')?response(page(tests)):undefined);
 open('execution');await screen.findByRole('checkbox',{name:'Run CASE29'});fireEvent.click(screen.getByRole('button',{name:'Select all eligible on this page'}));fireEvent.click(await screen.findByRole('button',{name:'Run selected'}));fireEvent.click(screen.getByLabelText('Headed'));
 expect(screen.getByText(/Headed mode is best suited/)).toBeInTheDocument();expect(screen.getByRole('button',{name:'Run'})).toBeEnabled();expect(writes()).toHaveLength(0);
});
it('serially polls active progress and stops when persisted execution is terminal',async()=>{
 const pending=deferred<Response>();let reads=0;
 routes(url=>url.startsWith(api+'/browser/batches/batch-a?')?(++reads===1?response({...batch,status:'PREPARING',run:null,processing:true}):reads===2?pending.promise:response(batch)):undefined);
 vi.useFakeTimers();const view=open('browser-batches/batch-a');await act(async()=>{});expect(screen.getByText(/Preparing \/ running/)).toBeInTheDocument();
 await act(async()=>{await vi.advanceTimersByTimeAsync(1500);});expect(reads).toBe(2);
 await act(async()=>{await vi.advanceTimersByTimeAsync(6000);});expect(reads).toBe(2);
 await act(async()=>pending.resolve(response(batch)));await act(async()=>{await vi.advanceTimersByTimeAsync(6000);});expect(reads).toBe(2);view.unmount();
});

it('retains explicit browser Test Design selection across server pages',async()=>{
 const second={...test,id:'second',key:'SECOND',title:'Second test'};
 routes(url=>url.includes('/test-design?')?response({items:[{test:url.includes('page=2')?second:test,content_hash:'a'.repeat(64),approvable:false}],total:2,page:url.includes('page=2')?2:1,total_pages:2,page_size:10}):undefined);
 open('test-design');fireEvent.click(await screen.findByRole('checkbox',{name:'Select PAY'}));fireEvent.click(screen.getByRole('button',{name:'Next page'}));await screen.findByRole('checkbox',{name:'Select SECOND'});fireEvent.click(screen.getByRole('button',{name:'Select all on current page (1)'}));
 expect(screen.getByText(/2 approved browser tests selected across pages/)).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'Run selected'}));expect(screen.getByRole('dialog',{name:'Run 2 selected tests'})).toBeInTheDocument();expect(writes()).toHaveLength(0);
});

it('never labels a runnable preparation awaiting Run materialization as zero-runnable or QA success',async()=>{
 routes(url=>url.startsWith(api+'/browser/batches/batch-a?')?response({...batch,run:null,processing:false,summary:{runnable:2,passed:0,failed:0,needs_attention:1,preparation_errors:0,not_evaluated:0},duration_seconds:null,items:page([item('1','READY'),item('2','READY'),item('3','NEEDS_ATTENTION')])}):undefined);
 open('browser-batches/batch-a');await screen.findByText('Runnable tests await Run materialization. No execution results have been recorded yet.');expect(screen.queryByText(/No runnable tests/)).not.toBeInTheDocument();expect(writes()).toHaveLength(0);
});
