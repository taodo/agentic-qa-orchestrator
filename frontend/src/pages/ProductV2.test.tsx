import { act,fireEvent,render,screen,waitFor,within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect,it,vi } from 'vitest';
import { App } from '../app/App';
import { campaign,readiness,specification,blockedSpecification,requirement } from '../test/campaigns';
import { page,response,deferred,project } from '../test/fixtures';
import type { ExecutionCandidate } from '../api/productV2';
const base=`/projects/${campaign.project_id}/campaigns/${campaign.id}`,api='/api/v1'+base;
const good:ExecutionCandidate={test:specification,content_hash:'a'.repeat(64),eligible:true,reason:null};
const blocked:ExecutionCandidate={test:blockedSpecification,content_hash:'b'.repeat(64),eligible:false,reason:'Missing source behavior'};
const run={id:'run-v2',project_id:project.id,campaign_id:campaign.id,run_number:1,idempotency_key:'intent',note:null,snapshot_version:'qa-run-selection-v2',snapshot_hash:'f'.repeat(64),campaign_snapshot:campaign,readiness_at_creation:readiness,requirement_count:1,test_count:2,execution_status:'CREATED',qa_outcome:'NOT_EVALUATED',created_at:campaign.created_at,started_at:null,completed_at:null,execution_error_code:null};
function routes(extra:(url:string,options?:RequestInit)=>Response|Promise<Response>|undefined=()=>undefined){vi.mocked(fetch).mockImplementation(async(input,options)=>{
  const url=String(input),special=extra(url,options);if(special)return special;
  if(url===api)return response(campaign);if(url===api+'/readiness')return response(readiness);
  if(url.includes('/test-design?'))return response({items:[{...good,approvable:true},{...blocked,approvable:false}],total:2,page:1,page_size:10,total_pages:1});
  if(url.includes('/execution-candidates?'))return response(page([good,blocked]));
  if(url===api+'/requirements?limit=50')return response(page([requirement]));
  if(url===api+'/sources?limit=50&purpose=SPECIFICATION')return response(page([]));
  if(url===api+'/runs?limit=50')return response(page([]));
  return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
const open=(path:string)=>render(<MemoryRouter initialEntries={[base+'/'+path]}><App/></MemoryRouter>);
const writes=()=>vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST');

it('uses product navigation and passive authoritative overview without provider writes',async()=>{
  routes();open('');await screen.findByText('129 approved / 130 current tests');
  const nav=screen.getByRole('navigation',{name:'Campaign preparation'});
  for(const name of ['Overview','Specification','Test Design','Execution','Results','Project Settings','Advanced / Audit'])expect(within(nav).getByRole('link',{name})).toBeInTheDocument();
  for(const name of ['Requirements','Traceability','Readiness','Runs'])expect(within(nav).queryByRole('link',{name})).not.toBeInTheDocument();
  expect(writes()).toHaveLength(0);
});

it('uploads inert file bytes with explicit analyze, showing format/provenance limits',async()=>{
  let uploaded=false;
  const source={id:'doc',name:'spec.md',source_type:'MARKDOWN',purpose:'SPECIFICATION',status:'INGESTED',original_bytes:12,line_count:2,document:null};
  routes((url,options)=>{
    if(url===api+'/sources?limit=50&purpose=SPECIFICATION')return response(page(uploaded?[source]:[]));
    if(url===api+'/documents'){uploaded=true;return response(source);}
    return undefined;
  });open('specification');await screen.findByText('Add a specification to begin test design.');
  const file=new File(['# Spec\nFacts'],'spec.md',{type:'application/octet-stream'});Object.defineProperty(file,'arrayBuffer',{value:()=>Promise.resolve(new TextEncoder().encode('# Spec\nFacts').buffer)});
  fireEvent.change(screen.getByLabelText('Specification file'),{target:{files:[file]}});expect(writes()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button',{name:'Upload specification'}));await screen.findByRole('button',{name:'Analyze specification'});
  expect(writes()).toHaveLength(1);const [url,options]=writes()[0];expect(url).toBe(api+'/documents');expect(JSON.parse(options!.body as string)).toEqual({name:'spec.md',content_base64:btoa('# Spec\nFacts')});
  expect(document.body).not.toHaveTextContent('Provider token usage');
});

it('does not upload unsupported files or oversized content',async()=>{
  routes();open('specification');await screen.findByText('Add a specification to begin test design.');
  fireEvent.change(screen.getByLabelText('Specification file'),{target:{files:[new File(['x'],'bad.exe')]}});fireEvent.click(screen.getByRole('button',{name:'Upload specification'}));
  expect(await screen.findByText(/Choose PDF, DOCX/)).toBeInTheDocument();expect(writes()).toHaveLength(0);
});

it('shows needs-info cases alongside ready cases and explicit selected approval/export',async()=>{
  routes();open('test-design');await screen.findByRole('heading',{name:specification.title});
  expect(screen.getByText('NEEDS_INFO',{selector:'.badge'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));expect((screen.getByRole('checkbox',{name:'Select all on current page'}) as HTMLInputElement).indeterminate).toBe(true);expect(screen.getByRole('button',{name:'Export CSV'})).toBeEnabled();expect(screen.getByRole('button',{name:'Export XLSX'})).toBeEnabled();
  expect(writes()).toHaveLength(0);fireEvent.click(screen.getByRole('button',{name:'Clear selection'}));expect(screen.getByRole('button',{name:'Export CSV'})).toBeDisabled();
});

it('retains selection across bounded pages and creates exactly that synthetic Run despite NOT_READY',async()=>{
  const second={...good,test:{...specification,id:'test-second',key:'SECOND',title:'Second case'}};
  const pending=deferred<Response>();let submitted:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url.includes('/test-design?'))return response({items:[{...good,approvable:true},{...blocked,approvable:false}],total:2,page:1,page_size:10,total_pages:1});
  if(url.includes('/execution-candidates?'))return response(page(url.includes('after_id=test-b')?[second]:[good,blocked],!url.includes('after_id=test-b')));
    if(url===api+'/runs' && options?.method==='POST'){submitted=JSON.parse(options.body as string);return pending.promise;}
    if(url===api+'/runs/run-v2/start')return response({...run,execution_status:'COMPLETED',qa_outcome:'FAIL'});
    if(url.includes('/runs/run-v2/results'))return response({run,summary:{total:2,completed:0,passed:0,failed:0,skipped:0,not_evaluated:2,remaining:2},tests:page([])});
    if(url.includes('/runs/run-v2/requirements'))return response(page([]));return undefined;
  });open('execution');const check=await screen.findByRole('checkbox',{name:'Run PAY'});expect(screen.getByRole('checkbox',{name:'Run CURRENCY'})).toBeDisabled();
  fireEvent.click(check);fireEvent.click(screen.getByRole('button',{name:'Next page'}));fireEvent.click(await screen.findByRole('checkbox',{name:'Run SECOND'}));
  expect(screen.getByText('Selected: 2 across pages (maximum 500)')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Run selected (Synthetic)'}));fireEvent.click(screen.getByRole('button',{name:'Creating / running…'}));
  await waitFor(()=>expect(submitted?.test_specification_ids).toEqual(['test-a','test-second']));expect(writes()).toHaveLength(1);
  await act(async()=>pending.resolve(response(run)));await screen.findByRole('heading',{name:'QA Run detail'});
  expect(writes()).toHaveLength(2);expect(writes()[1][0]).toBe(api+'/runs/run-v2/start');
});

it('never retries create automatically and keeps exact intent after failure',async()=>{
  routes((url,options)=>url===api+'/runs' && options?.method==='POST'?response({error:{code:'RUN_SELECTION_INVALID',message:'Selection changed'}},409):undefined);open('execution');
  fireEvent.click(await screen.findByRole('checkbox',{name:'Run PAY'}));fireEvent.click(screen.getByRole('button',{name:'Run selected (Synthetic)'}));await screen.findByText('RUN_SELECTION_INVALID');
  expect(writes()).toHaveLength(1);fireEvent.click(screen.getByRole('button',{name:'Retry same create intent'}));await waitFor(()=>expect(writes()).toHaveLength(2));
  expect(writes()[0][1]?.body).toBe(writes()[1][1]?.body);
});

it('discards a late create completion on unmount without starting a Run',async()=>{
  const pending=deferred<Response>();routes((url,options)=>url===api+'/runs' && options?.method==='POST'?pending.promise:undefined);const view=open('execution');
  fireEvent.click(await screen.findByRole('checkbox',{name:'Run PAY'}));fireEvent.click(screen.getByRole('button',{name:'Run selected (Synthetic)'}));view.unmount();await act(async()=>pending.resolve(response(run)));
  expect(writes()).toHaveLength(1);
});

it('shows saved Results as synthetic without provider or start calls',async()=>{
  routes(url=>url===api+'/runs?limit=50'?response(page([{...run,execution_status:'COMPLETED',qa_outcome:'FAIL'}])):undefined);open('results');
  await screen.findByRole('link',{name:'RUN-001'});expect(within(screen.getByRole('region',{name:'Recent Runs'})).getByText('2')).toBeInTheDocument();expect(screen.getByText('SYNTHETIC · saved history')).toBeInTheDocument();expect(writes()).toHaveLength(0);
});


it('reads browser history truthfully without detail fan-out or execution',async()=>{
  routes(url=>url===api+'/runs?limit=50'?response(page([{...run,executor_kind:'WEB_BROWSER',execution_status:'COMPLETED',qa_outcome:'PASS'}])):undefined);open('results');
  await screen.findByRole('link',{name:'RUN-001'});
  expect(screen.getByText('Saved execution history')).toBeInTheDocument();
  expect(screen.queryByText('SYNTHETIC · saved history')).not.toBeInTheDocument();
  expect(screen.queryByText(/truthful SYNTHETIC outcomes/)).not.toBeInTheDocument();
  expect(writes()).toHaveLength(0);
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/runs/'+run.id))).toBe(false);
});

it('opens Project Settings as a read-only host snapshot',async()=>{
  routes(url=>url===`/api/v1/projects/${project.id}`?response(project):undefined);
  render(<MemoryRouter initialEntries={[`/projects/${project.id}/settings`]}><App/></MemoryRouter>);
  await screen.findByRole('heading',{name:project.name});
  expect(screen.getByRole('heading',{name:'Project Settings'})).toBeInTheDocument();
  expect(await screen.findByText(/Runtime status unavailable/)).toBeInTheDocument();
  expect(writes()).toHaveLength(0);
});

it('edits missing information only through explicit new human test versions',async()=>{
  let body:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url.includes('/test-design?'))return response({items:[{...blocked,approvable:false,test:{...blockedSpecification,requirement_ids:[requirement.id],unresolved_requirement_refs:[],information_markers:[{kind:'MISSING_INFORMATION',description:'Currency behavior is unspecified.'}]}}],total:2,page:1,page_size:10,total_pages:1});
  if(url.includes('/execution-candidates?'))return response(page([{...blocked,test:{...blockedSpecification,requirement_ids:[requirement.id],unresolved_requirement_refs:[],information_markers:[{kind:'MISSING_INFORMATION',description:'Currency behavior is unspecified.'}]}}]));
    if(url.endsWith('/test-specifications/test-b/edits')){body=JSON.parse(options!.body as string);return response({...blockedSpecification,id:'replacement',review_status:'READY_FOR_REVIEW'});}
    return undefined;
  });open('test-design');await screen.findByRole('heading',{name:blockedSpecification.title});
  const row=screen.getByRole('heading',{name:blockedSpecification.title}).closest('tr')!;
  fireEvent.click(within(row).getByText('Add information',{selector:'summary'}));
  fireEvent.click(within(row).getByRole('button',{name:'Edit / provide facts'}));
  const form=within(row).getByRole('form',{name:'Edit CURRENCY'});
  fireEvent.change(within(form).getByLabelText('Overall expected result'),{target:{value:'Unsupported currency is rejected.'}});
  fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa'}});
  fireEvent.change(within(form).getByLabelText('Facts / reason for this change'),{target:{value:'Product owner confirmed rejection.'}});
  fireEvent.click(within(form).getByRole('checkbox'));
  expect(writes()).toHaveLength(0);fireEvent.click(within(form).getByRole('button',{name:'Save new test version'}));
  await waitFor(()=>expect(body).toBeDefined());
  expect(body!.previous_hash).toBe(blocked.content_hash);expect((body!.design as Record<string,unknown>).information_markers).toEqual([]);
  expect(writes()).toHaveLength(1);expect(writes()[0][0]).toContain('/edits');
});

it('exports the explicit current-page selection through the scoped export contract',async()=>{
  const create=vi.fn(()=> 'blob:export'),revoke=vi.fn();Object.defineProperty(URL,'createObjectURL',{configurable:true,value:create});Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:revoke});
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  let body:unknown;
  routes((url,options)=>{if(url.endsWith('/test-exports')){body=JSON.parse(options!.body as string);return response({filename:'test-design.xlsx',media_type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',content_base64:btoa('inert fixture'),count:1});}return undefined;});
  open('test-design');fireEvent.click(await screen.findByRole('checkbox',{name:'Select PAY'}));fireEvent.click(screen.getByRole('button',{name:'Export XLSX'}));
  await screen.findByText('Exported 1 selected cases as XLSX.');expect(body).toEqual({test_specification_ids:['test-a'],format:'XLSX'});expect(click).toHaveBeenCalledOnce();expect(writes()).toHaveLength(1);click.mockRestore();
});


it('uses a disabled approval button until eligible page selection; mixed selection stays explicit',async()=>{
  routes();open('test-design');await screen.findByRole('heading',{name:specification.title});
  expect(screen.getByRole('button',{name:'Approve selected (0)'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Select all on current page (2)'}));
  expect(screen.getByRole('button',{name:'Approve selected (1)'})).toBeEnabled();
  expect(screen.getByText('Selected: 2 · 1 eligible for approval')).toBeInTheDocument();
  expect(writes()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button',{name:'Clear selection'}));
  expect(screen.getByRole('button',{name:'Approve selected (0)'})).toBeDisabled();
});

it('expands a whole row with click/keyboard without checkbox or child interaction toggles',async()=>{
  routes();open('test-design');const row=(await screen.findByRole('heading',{name:specification.title})).closest('tr')!;
  expect(row).toHaveAttribute('aria-expanded','false');
  fireEvent.click(within(row).getByRole('heading'));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByRole('checkbox'));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByRole('button',{name:'Edit / provide facts'}));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.change(within(row).getByLabelText('Title'),{target:{value:'Edited title'}});expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByLabelText('Priority'));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByLabelText('Overall expected result'));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.keyDown(row,{key:'Enter'});expect(row).toHaveAttribute('aria-expanded','false');
  fireEvent.keyDown(row,{key:' '});expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByText('Supporting source findings'));expect(row).toHaveAttribute('aria-expanded','true');
  fireEvent.click(within(row).getByRole('link'));expect(row).toHaveAttribute('aria-expanded','true');
});

it('requests bounded server pages, numbers and sizes while preserving search/filter',async()=>{
  routes(url=>{if(url.includes('/test-design?')){const q=new URL(url,'http://local').searchParams;return response({items:[{...good,approvable:true}],total:247,page:Number(q.get('page')),page_size:Number(q.get('page_size')),total_pages:Math.ceil(247/Number(q.get('page_size')))});}return undefined;});
  open('test-design');await screen.findByRole('heading',{name:specification.title});
  const nav=screen.getByRole('navigation',{name:'Test Design pages'});
  expect(within(nav).getByRole('button',{name:'1'})).toHaveAttribute('aria-current','page');
  expect(within(nav).getAllByRole('button').length).toBeLessThan(9);
  fireEvent.click(within(nav).getByRole('button',{name:'Next page'}));await screen.findByText(/Page 2 of 25/);
  fireEvent.change(screen.getByLabelText('Search tests'),{target:{value:'booking'}});await screen.findByText(/Page 1 of 25/);
  fireEvent.change(screen.getByLabelText('Design status'),{target:{value:'READY'}});
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'100'}});await screen.findByText(/Page 1 of 3/);
  const calls=vi.mocked(fetch).mock.calls.map(([url])=>String(url)).filter(url=>url.includes('/test-design?'));
  expect(calls.at(-1)).toContain('search=booking');expect(calls.at(-1)).toContain('status=READY');expect(calls.at(-1)).toContain('page_size=100');
  expect(writes()).toHaveLength(0);
});

it('selects all matching using a descriptor and pins approval to its backend fingerprint',async()=>{
  let selection:unknown,approval:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url.includes('/test-design?'))return response({items:[{...good,approvable:true}],total:247,page:1,page_size:10,total_pages:25});
    if(url.endsWith('/test-design/selection')){selection=JSON.parse(options!.body as string);return response({fingerprint:'f'.repeat(64),matched:247,eligible:240});}
    if(url.endsWith('/test-design/approval')){approval=JSON.parse(options!.body as string);return response({matched:247,approved:240,skipped:7});}return undefined;
  });open('test-design');await screen.findByRole('heading',{name:specification.title});
  fireEvent.click(screen.getByRole('button',{name:'Select all 247 matching tests for approval'}));
  expect(await screen.findByRole('button',{name:'Approve selected (240)'})).toBeEnabled();
  expect(selection).toEqual({criteria:{search:'',status:'ALL'}});
  fireEvent.change(screen.getByLabelText('Reviewer label'),{target:{value:'human'}});
  fireEvent.click(screen.getByRole('button',{name:'Approve selected (240)'}));
  await screen.findByText('Approved 240; skipped 7 ineligible tests.');
  expect(approval).toEqual({selection,fingerprint:'f'.repeat(64),reviewer_label:'human'});
  expect(writes()).toHaveLength(2);expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/test-specifications/'))).toBe(false);
});

it('discards delayed matching selection on navigation',async()=>{
  const pending=deferred<Response>();routes(url=>url.endsWith('/test-design/selection')?pending.promise:undefined);
  const view=open('test-design');await screen.findByRole('heading',{name:specification.title});
  fireEvent.click(screen.getByRole('button',{name:'Select all 2 matching tests for approval'}));view.unmount();
  await act(async()=>{pending.resolve(response({fingerprint:'f'.repeat(64),matched:2,eligible:2}));});
  expect(writes()).toHaveLength(1);
});

it('downloads persisted Run exports only on explicit action, with no mutable test reads',async()=>{
  const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn(()=> 'blob:run')});
  Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
  routes(url=>{
    if(url.includes('/runs/run-v2/results'))return response({run:{...run,execution_status:'COMPLETED',qa_outcome:'FAIL'},summary:{total:2,completed:2,passed:1,failed:1,skipped:0,not_evaluated:0,remaining:0},tests:page([])});
    if(url.includes('/runs/run-v2/requirements'))return response(page([]));
    if(url.includes('/runs/run-v2/export?'))return response({filename:'run-results.csv',media_type:'text/csv',content_base64:btoa('Run,FAIL'),count:2});return undefined;
  });open('runs/run-v2');await screen.findByText('RUN-001');
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/export?'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Export CSV'}));await waitFor(()=>expect(click).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button',{name:'Export XLSX'}));await waitFor(()=>expect(click).toHaveBeenCalledTimes(2));
  expect(writes()).toHaveLength(0);expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/test-specifications'))).toBe(false);
  click.mockRestore();
});


it('pins explicit page approval to displayed versions and never retries a stale conflict',async()=>{
  let chosen:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url.endsWith('/test-design/selection')){chosen=JSON.parse(options!.body as string);return response({fingerprint:'c'.repeat(64),matched:2,eligible:1});}
    if(url.endsWith('/test-design/approval'))return response({error:{code:'REVIEW_CONFLICT',message:'Selection changed; select again.'}},409);
    return undefined;
  });open('test-design');await screen.findByRole('heading',{name:specification.title});
  fireEvent.click(screen.getByRole('button',{name:'Select all on current page (2)'}));
  fireEvent.change(screen.getByLabelText('Reviewer label'),{target:{value:'human'}});
  fireEvent.click(screen.getByRole('button',{name:'Approve selected (1)'}));
  await screen.findByText(/Selection changed; select again/);
  expect(chosen).toEqual({criteria:{search:'',status:'ALL'},ids:[specification.id,blockedSpecification.id],expected_versions:{[specification.id]:`${good.content_hash}:${specification.review_status}`,[blockedSpecification.id]:`${blocked.content_hash}:${blockedSpecification.review_status}`}});
  expect(writes()).toHaveLength(2);
});

it('hides reserved browser facts from generic preconditions and edits ordinary text only',async()=>{
  const facts=JSON.stringify({contract_version:'browser-facts-v1',required_actions:[['NAVIGATE']],locators:[],paths:['/'],input_values:[]});
  const test={...specification,preconditions:['Ordinary setup',facts]};let submitted:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url.includes('/test-design?'))return response({items:[{...good,test,approvable:true}],total:1,page:1,page_size:10,total_pages:1});
    if(url.endsWith(`/test-specifications/${test.id}/edits`)){submitted=JSON.parse(options!.body as string);return response({...test,id:'successor',review_status:'READY_FOR_REVIEW'});}
    return undefined;
  });open('test-design');const row=(await screen.findByRole('heading',{name:test.title})).closest('tr')!;
  fireEvent.click(within(row).getByText('Review / edit',{selector:'summary'}));fireEvent.click(within(row).getByRole('button',{name:'Edit / provide facts'}));
  const form=within(row).getByRole('form',{name:'Edit PAY'}),preconditions=within(form).getByLabelText('Preconditions (one per line)');
  expect(preconditions).toHaveValue('Ordinary setup');expect(preconditions).not.toHaveValue(expect.stringContaining('browser-facts-v1'));
  expect(within(form).getByText(/Existing browser facts are preserved by the server/)).toBeInTheDocument();
  fireEvent.change(preconditions,{target:{value:'Changed ordinary setup'}});
  fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa'}});fireEvent.change(within(form).getByLabelText('Facts / reason for this change'),{target:{value:'Ordinary change'}});
  fireEvent.submit(form);await waitFor(()=>expect(submitted).toBeDefined());
  expect((submitted!.design as Record<string,unknown>).preconditions).toEqual(['Changed ordinary setup']);expect(writes()).toHaveLength(1);
});


it('Analyze success continues directly to the one top generation workflow without a model call on landing',async()=>{
  const source={id:'spec',name:'Spec',source_type:'MARKDOWN',purpose:'SPECIFICATION',status:'INGESTED',original_bytes:12,line_count:2,document:null,latest_extraction:{id:'analysis',status:'SUCCEEDED',output:{requirement_count:1},metadata:null}};
  routes(url=>url===api+'/sources?limit=50&purpose=SPECIFICATION'?response(page([source])):undefined);
  open('specification');await screen.findByText('Analysis saved. Review the supported findings in Test Design.');
  fireEvent.click(screen.getByRole('link',{name:'Continue to Test Design'}));
  const summary=await screen.findByText('Generate Test Cases from supported findings');
  const panel=summary.closest('details')!;expect(panel.open).toBe(true);
  expect(panel.compareDocumentPosition(screen.getByRole('region',{name:'Test Design table'})) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole('link',{name:'Import Test Cases'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('link',{name:'Generate from Specs'}));expect(summary).toHaveFocus();
  expect(screen.getAllByText('Generate Test Cases from supported findings')).toHaveLength(1);
  expect(screen.getByRole('button',{name:'Generate test cases'})).toBeDisabled();
  expect(writes()).toHaveLength(0);
});

it('normal local bulk approval has no reviewer/note fields and sends explicit provenance and displayed hashes',async()=>{
  let approved:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url===api+'/browser/capability')return response({planning:'AVAILABLE',execution:'AVAILABLE',automatic:'AVAILABLE',source_free_review:'AVAILABLE',local_operator_review:'AVAILABLE'});
    if(url.includes('/test-design?'))return response({items:[{...good,test:{...specification,review_status:'READY_FOR_REVIEW',requirement_ids:[]},approvable:false}],total:1,page:1,page_size:10,total_pages:1});
    if(url===api+'/browser/tests/approve-selection'){approved=JSON.parse(options!.body as string);return response({matched:1,approved:1,skipped:0});}
    return undefined;
  });open('test-design');await screen.findByRole('checkbox',{name:'Select PAY'});
  const form=screen.getByRole('form',{name:'Approve selected tests'});
  expect(within(form).queryByLabelText('Reviewer label')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Bulk reviewer label')).not.toBeInTheDocument();expect(screen.queryByLabelText('Bulk review note (optional)')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));
  fireEvent.click(within(form).getByRole('button',{name:'Approve selected (1)'}));
  await screen.findByText('Approved 1; skipped 0 ineligible tests.');
  expect(approved).toEqual({test_ids:[specification.id],expected_hashes:{[specification.id]:'a'.repeat(64)},approval_provenance:'LOCAL_OPERATOR'});
  expect(writes()).toHaveLength(1);
});

it('current-page header selection, page sizing and filters never select unloaded browser Tests',async()=>{
  const approved={...specification,requirement_ids:[]},second={...approved,id:'second',key:'SECOND',title:'Second Test'};
  let submitted:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url===api+'/browser/capability')return response({planning:'AVAILABLE',execution:'AVAILABLE',automatic:'AVAILABLE',source_free_review:'AVAILABLE',local_operator_review:'AVAILABLE'});
    if(url.includes('/test-design?')){const q=new URL(url,'http://local').searchParams;return response({items:[{test:q.get('page')==='2'?second:approved,content_hash:'a'.repeat(64),approvable:false}],total:100,page:Number(q.get('page')),page_size:Number(q.get('page_size')),total_pages:10});}
    if(url===api+'/browser/batches'){submitted=JSON.parse(options!.body as string);return response({error:{code:'BROWSER_BATCH_NOT_CONFIGURED',message:'Offline fixture'}},409);}
    return undefined;
  });open('test-design');await screen.findByRole('checkbox',{name:'Select PAY'});
  const header=screen.getByRole('checkbox',{name:'Select all on current page'});header.focus();expect(header).toHaveFocus();fireEvent.click(header);
  expect(screen.getByRole('checkbox',{name:'Select PAY'})).toBeChecked();
  fireEvent.click(screen.getByRole('button',{name:'Next page'}));await screen.findByRole('checkbox',{name:'Select SECOND'});
  expect(screen.getByRole('checkbox',{name:'Select all on current page'})).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select all on current page'}));
  fireEvent.click(screen.getByRole('checkbox',{name:'Select all on current page'}));
  expect(screen.getByText(/1 approved browser tests selected across pages/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Run selected'}));fireEvent.click(screen.getByRole('button',{name:'Run'}));
  await screen.findByText('BROWSER_BATCH_NOT_CONFIGURED');expect(submitted?.test_specification_ids).toEqual([approved.id]);
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
  fireEvent.change(screen.getByLabelText('Rows per page'),{target:{value:'20'}});await screen.findByRole('checkbox',{name:'Select PAY'});
  expect(screen.getByText(/0 approved browser tests selected across pages/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select all on current page'}));fireEvent.change(screen.getByLabelText('Design status'),{target:{value:'READY'}});
  await waitFor(()=>expect(screen.getByText(/0 approved browser tests selected across pages/)).toBeInTheDocument());
  expect(screen.getByRole('button',{name:'Select all 100 matching tests for approval'})).toBeDisabled();
  expect(writes()).toHaveLength(1);
});


it('the top generation panel calls the existing generation action exactly once after explicit approved selection',async()=>{
  const pending=deferred<Response>();
  routes((url,options)=>url===api+'/generate-tests' && options?.method==='POST'?pending.promise:undefined);
  open('test-design');await screen.findByText('Generate Test Cases from supported findings');
  const panel=document.getElementById('test-design-generation')!;
  const selected=await within(panel).findByRole('checkbox',{name:/Approved for generation/});expect(selected).not.toBeChecked();
  fireEvent.click(selected);const generate=within(panel).getByRole('button',{name:'Generate test cases'});
  fireEvent.click(generate);fireEvent.click(generate);
  await waitFor(()=>expect(writes()).toHaveLength(1));
  expect(writes()[0][0]).toBe(api+'/generate-tests');
  expect(JSON.parse(writes()[0][1]!.body as string)).toEqual({requirement_ids:[requirement.id]});
  await act(async()=>pending.resolve(response({id:'generated',status:'SUCCEEDED',output:{generated_count:1},metadata:null})));
  await screen.findByText('Generated 1 test cases. Review remains explicit.');expect(writes()).toHaveLength(1);
});


it('trusted local Spec-based bulk approval before Target selection needs no reviewer ceremony',async()=>{
  let approval:Record<string,unknown>|undefined;
  routes((url,options)=>{
    if(url===api+'/browser/capability')return response({planning:'UNAVAILABLE',execution:'UNAVAILABLE',automatic:'UNAVAILABLE',source_free_review:'UNAVAILABLE',local_operator_review:'AVAILABLE'});
    if(url.includes('/test-design?'))return response({items:[{...good,test:{...specification,review_status:'READY_FOR_REVIEW'},approvable:true}],total:1,page:1,page_size:10,total_pages:1});
    if(url.endsWith('/test-design/selection'))return response({fingerprint:'f'.repeat(64),matched:1,eligible:1});
    if(url.endsWith('/browser/test-design/approval')){approval=JSON.parse(options!.body as string);return response({matched:1,approved:1,skipped:0});}
    return undefined;
  });open('test-design');await screen.findByRole('checkbox',{name:'Select PAY'});
  expect(screen.queryByLabelText('Bulk reviewer label')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Bulk review note (optional)')).not.toBeInTheDocument();
  const form=screen.getByRole('form',{name:'Approve selected tests'});expect(within(form).queryByLabelText('Reviewer label')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));fireEvent.click(within(form).getByRole('button',{name:'Approve selected (1)'}));
  await screen.findByText('Approved 1; skipped 0 ineligible tests.');
  expect(approval).toEqual({selection:{criteria:{search:'',status:'ALL'},ids:[specification.id],expected_versions:{[specification.id]:'a'.repeat(64)+':READY_FOR_REVIEW'}},fingerprint:'f'.repeat(64),approval_provenance:'LOCAL_OPERATOR'});
  expect(writes()).toHaveLength(2);
});


it('does not flash or accept reviewer ceremony while local capability is loading',async()=>{
  const pending=deferred<Response>();
  routes(url=>url===api+'/browser/capability'?pending.promise:undefined);
  open('test-design');await screen.findByRole('checkbox',{name:'Select PAY'});
  expect(screen.queryByLabelText('Reviewer label')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Bulk reviewer label')).not.toBeInTheDocument();
  await act(async()=>pending.resolve(response({planning:'UNAVAILABLE',execution:'UNAVAILABLE',source_free_review:'UNAVAILABLE',local_operator_review:'AVAILABLE'})));
  expect(screen.queryByLabelText('Reviewer label')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Bulk reviewer label')).not.toBeInTheDocument();
  expect(writes()).toHaveLength(0);
});
