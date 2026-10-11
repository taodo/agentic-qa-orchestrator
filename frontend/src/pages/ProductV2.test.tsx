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
  if(url.includes('/execution-candidates?'))return response(page([good,blocked]));
  if(url===api+'/requirements?limit=50')return response(page([requirement]));
  if(url===api+'/sources?limit=50&purpose=SPECIFICATION')return response(page([]));
  if(url===api+'/runs?limit=50')return response(page([]));
  return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
const open=(path:string)=>render(<MemoryRouter initialEntries={[base+'/'+path]}><App/></MemoryRouter>);
const writes=()=>vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST');

it('uses product navigation and passive authoritative overview without provider writes',async()=>{
  routes();open('');await screen.findByText('130 current tests');
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
  fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));expect(screen.getByRole('button',{name:'Export CSV'})).toBeEnabled();expect(screen.getByRole('button',{name:'Export XLSX'})).toBeEnabled();
  expect(writes()).toHaveLength(0);fireEvent.click(screen.getByRole('button',{name:'Clear selection'}));expect(screen.getByRole('button',{name:'Export CSV'})).toBeDisabled();
});

it('retains selection across bounded pages and creates exactly that synthetic Run despite NOT_READY',async()=>{
  const second={...good,test:{...specification,id:'test-second',key:'SECOND',title:'Second case'}};
  const pending=deferred<Response>();let submitted:Record<string,unknown>|undefined;
  routes((url,options)=>{
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
  await screen.findByRole('link',{name:'RUN-001'});expect(screen.getByText('2 selected tests · SYNTHETIC')).toBeInTheDocument();expect(writes()).toHaveLength(0);
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
