import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Link } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { campaign, requirement, blockedRequirement, readiness, traceability } from '../test/campaigns';
import { deferred, page, response } from '../test/fixtures';
import type { CampaignRequirement, RequirementTrace } from '../api/campaignTypes';
const base=`/projects/${campaign.project_id}/campaigns/${campaign.id}`, api='/api/v1'+base;
const ready={...requirement,id:'ready',title:'Review payment',key:'READY',logical_key:'REQ-long-internal-ready',review_status:'READY_FOR_REVIEW' as const};
const result={id:'generation',project_id:campaign.project_id,campaign_id:campaign.id,status:'SUCCEEDED',error_code:null,
  configured_model:'configured-model',provider_model:'provider-model',provider:'openai',usage:{input_tokens:{total:10},output_tokens:{total:20},reasoning_tokens:{total:7},total_tokens:{total:30}},
  output:{generated_count:8,ready_for_review_count:7,needs_clarification_count:1,inherited_clarification_count:0,revised_requirement:null}};
const posts=()=>vi.mocked(fetch).mock.calls.filter(([,options])=>options?.method==='POST');
function setup({requirements=[requirement,ready,blockedRequirement],rows=traceability.requirements.items,truncated=false,namesFail=false,write}:{
  requirements?:CampaignRequirement[]; rows?:RequirementTrace[]; truncated?:boolean; namesFail?:boolean;
  write?:(url:string,body:Record<string,unknown>)=>Response|Promise<Response>;
}={}) {
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const url=String(input);
    if(options?.method==='POST')return write?.(url,JSON.parse(String(options.body))) ?? response(result);
    if(url===api)return response(campaign);
    if(url===api+'/readiness')return response(readiness);
    if(url===api+'/requirements?limit=50')return namesFail?response({stack:'PRIVATE_NAMES'},500):response(page(requirements,truncated));
    if(url===api+'/traceability?limit=50')return response({...traceability,requirements:page(rows,truncated)});
    if(url===api+'/sources?limit=50' || url===api+'/test-specifications?limit=50')return response(page([]));
    if(url===api+'/requirements/historical')return response({...ready,id:'historical',key:'HISTORY',title:'Historical payment'});
    throw new Error('Unexpected read '+url);
  });
}
function open(section='traceability'){return render(<MemoryRouter initialEntries={[base+'/'+section]}><Link to="/missing">Leave</Link><App/></MemoryRouter>);}
function row(key:string){return screen.getByRole('heading',{name:key}).closest('tr')!;}
function selectAll(){fireEvent.click(screen.getByRole('button',{name:'Select all approved visible'}));}
function bulkSubmit(){fireEvent.change(screen.getByLabelText('Bulk reviewer label'),{target:{value:'qa-human'}});fireEvent.submit(screen.getByRole('form',{name:'Bulk approve Requirements'}));}

describe('Requirements work table',()=>{
  it('uses local identity, bounded returned counts, filters and selects only visible rows',async()=>{
    setup({truncated:true});open('requirements');await screen.findByRole('table');
    expect(row(requirement.title)).toHaveTextContent('PAY');expect(row(ready.title)).toBeTruthy();
    expect(screen.getByText(/Counts describe returned current/)).toBeInTheDocument();
    expect(screen.getByRole('button',{name:'Ready for review (1)'})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Ready for review (1)'}));
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));
    expect(screen.getByRole('checkbox')).toBeChecked();expect(screen.getByText('Selected: 1 visible current Requirements.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Deselect all'}));expect(screen.getByRole('checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button',{name:'Needs clarification (1)'}));expect(screen.getByRole('checkbox',{name:'Select CURRENCY'})).not.toBeChecked();
    expect(screen.queryByRole('checkbox',{name:'Select READY'})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Approved (1)'}));expect(screen.getByRole('checkbox',{name:'Select PAY'})).toBeDisabled();
    expect(screen.getByText(/Additional records/)).toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it('bulk approval submits only selected eligible current rows, retaining individual failures',async()=>{
    const another={...ready,id:'ready2',key:'READY2',title:'Second ready'};const pending=deferred<Response>();
    setup({requirements:[requirement,ready,blockedRequirement,another],truncated:true,write:(url)=>{
      if(url.endsWith('/ready/review'))return pending.promise;
      if(url.endsWith('/ready2/review'))return response({error:{code:'REVIEW_CONFLICT',message:'Conflict'}},409);
      throw new Error('Unexpected bulk selection');
    }});open('requirements');await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));bulkSubmit();bulkSubmit();
    expect(posts()).toHaveLength(1);expect(await screen.findByText('Recording approval 1 of 2…')).toBeInTheDocument();
    await act(async()=>pending.resolve(response({review_status:'APPROVED'})));
    const results=await screen.findByRole('list',{name:'Bulk approval results'});
    expect(results).toHaveTextContent('READY: Approval recorded.');expect(results).toHaveTextContent('READY2: REVIEW_CONFLICT');
    expect(posts().map(([url])=>String(url))).toEqual([api+'/requirements/ready/review',api+'/requirements/ready2/review']);
    expect(posts().every(([,options])=>JSON.parse(String(options?.body)).reviewer_label==='qa-human')).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('extract') || String(url).includes('generate'))).toBe(false);
  });
  it('stops remaining approvals after authorization failure without automatic retry',async()=>{
    setup({requirements:[ready,{...ready,id:'r2',key:'R2'}],write:()=>response({error:{code:'HOST_CSRF_REQUIRED',message:'Sign in'}},403)});
    open('requirements');await screen.findByRole('table');fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));bulkSubmit();
    expect(await screen.findByRole('list',{name:'Bulk approval results'})).toHaveTextContent('1 remaining requests were not attempted');expect(posts()).toHaveLength(1);
  });
  it('does not continue a pending bulk batch after unmount',async()=>{
    const pending=deferred<Response>();setup({requirements:[ready,{...ready,id:'r2',key:'R2'}],write:()=>pending.promise});open('requirements');await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));bulkSubmit();fireEvent.click(screen.getByRole('link',{name:'Leave'}));
    await screen.findByRole('heading',{name:'Page not found'});await act(async()=>pending.resolve(response({})));expect(posts()).toHaveLength(1);
  });
  it('keeps clarification facts row-specific and never invokes revision on save',async()=>{
    const other={...blockedRequirement,id:'other',key:'OTHER',title:'Other unclear'};
    setup({requirements:[blockedRequirement,other],write:url=>{expect(url).toBe(api+'/requirements/'+other.id+'/clarifications');return response({id:'facts',source_id:'addendum',requirement_id:other.id});}});
    open('requirements');await screen.findByRole('heading',{name:other.title});const scope=within(row(other.title));
    fireEvent.click(scope.getByText('Add info / Clarify'));fireEvent.click(scope.getByRole('button',{name:'Add Clarification / Provide Missing Information'}));
    fireEvent.change(scope.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'Only this Requirement: USD'}});
    fireEvent.click(scope.getByRole('button',{name:'Save Clarification'}));
    expect(await scope.findByRole('button',{name:'Revise Requirement'})).toBeInTheDocument();expect(posts()).toHaveLength(1);
    expect(JSON.parse(String(posts()[0][1]?.body)).content).toBe('Only this Requirement: USD');
    expect(within(row(blockedRequirement.title)).queryByLabelText('Missing facts (no credentials or secrets)')).not.toBeInTheDocument();
  });
  it('never selects a detail outside the returned current list or fans out',async()=>{
    setup({requirements:[ready],truncated:true});open('requirements?requirement_id=historical');
    expect(await screen.findByRole('heading',{name:'Historical payment'})).toBeInTheDocument();
    expect(screen.getByRole('checkbox',{name:'Select HISTORY'})).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));bulkSubmit();
    await screen.findByRole('list',{name:'Bulk approval results'});expect(posts()).toHaveLength(1);expect(posts()[0][0]).toBe(api+'/requirements/ready/review');
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url)===api+'/requirements/historical')).toHaveLength(2); // one selected detail per explicit list refresh
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).startsWith(api+'/requirements/') && !String(url).endsWith('/review')).every(([url])=>String(url)===api+'/requirements/historical')).toBe(true);
  });
});

describe('Traceability Test Design Workbench',()=>{
  it('uses authoritative rows for eligibility despite optional-name failure; performs bounded reads only',async()=>{
    const rows=[...traceability.requirements.items,{...traceability.requirements.items[0],requirement_id:'pending',review_status:'READY_FOR_REVIEW' as const}];
    setup({rows,namesFail:true,truncated:true});open();await screen.findByText(/Requirement names are unavailable/);
    const table=screen.getByRole('table');expect(within(table).getAllByRole('checkbox')).toHaveLength(4);
    expect(screen.getByRole('checkbox',{name:'Select requirement-a for generation'})).toBeEnabled();
    expect(screen.getByRole('checkbox',{name:'Select requirement-b for generation'})).toBeDisabled();
    const buttons=within(table).getAllByRole('button',{name:'Generate Tests'});expect(buttons.map(button=>(button as HTMLButtonElement).disabled)).toEqual([false,true,false,true]);
    expect(screen.getAllByText('Approve this Requirement before generating tests.')).toHaveLength(2);
    selectAll();expect(screen.getAllByRole('checkbox').filter(box=>(box as HTMLInputElement).checked)).toHaveLength(2);
    fireEvent.click(screen.getByRole('button',{name:'Deselect all'}));expect(screen.getAllByRole('checkbox').every(box=>!(box as HTMLInputElement).checked)).toBe(true);
    fireEvent.click(screen.getByRole('button',{name:'Refresh Traceability'}));await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(6));
    expect(posts()).toHaveLength(0);expect(document.body).not.toHaveTextContent('PRIVATE_NAMES');
    expect(vi.mocked(fetch).mock.calls.every(([url])=>!String(url).includes('/requirements/'))).toBe(true);
  });
  it('caps select-all explicitly at 20 displayed approved rows',async()=>{
    const rows=Array.from({length:23},(_,i)=>({...traceability.requirements.items[0],requirement_id:'r'+i}));
    setup({rows,truncated:true});open();await screen.findByRole('table');selectAll();
    expect(screen.getByText(/Select all takes only the first 20/)).toBeInTheDocument();
    expect(screen.getAllByRole('checkbox').filter(box=>(box as HTMLInputElement).checked)).toHaveLength(20);
    expect(screen.getAllByRole('checkbox')[20]).toBeDisabled();fireEvent.click(screen.getByRole('button',{name:'Generate tests for selected'}));
    await screen.findByRole('region',{name:'Generation completion'});expect(JSON.parse(String(posts()[0][1]?.body)).requirement_ids).toEqual(rows.slice(0,20).map(row=>row.requirement_id));expect(posts()).toHaveLength(1);
  });
  it.each(['stay','go'])('shows exact action-local metadata and offers an explicit %s choice without redirect',async choice=>{
    const pending=deferred<Response>();setup({write:()=>pending.promise});open();await screen.findByRole('table');
    const button=within(screen.getByRole('table')).getAllByRole('button',{name:'Generate Tests'})[0];fireEvent.click(button);fireEvent.click(button);expect(posts()).toHaveLength(1);
    await act(async()=>pending.resolve(response(result)));const completion=await screen.findByRole('region',{name:'Generation completion'});
    expect(completion).toHaveTextContent('Generated8');expect(completion).toHaveTextContent('Ready for review at creation7');expect(completion).toHaveTextContent('Needs clarification at creation1');
    expect(completion).toHaveTextContent('Configured modelconfigured-model');expect(completion).toHaveTextContent('Provider modelprovider-model');
    expect(completion).toHaveTextContent('Input10');expect(completion).toHaveTextContent('Output20');expect(completion).toHaveTextContent('Reasoning7');expect(completion).toHaveTextContent('Total30');
    expect(screen.getByRole('heading',{name:'Traceability',level:2})).toBeInTheDocument();
    if(choice==='stay'){fireEvent.click(within(completion).getByRole('button',{name:'Stay on Traceability'}));expect(screen.queryByRole('region',{name:'Generation completion'})).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Traceability'})).toBeInTheDocument();}
    else {fireEvent.click(within(completion).getByRole('link',{name:'Go to Test Cases'}));await screen.findByRole('heading',{name:'Test Specifications',level:2});}
    expect(posts()).toHaveLength(1);
  });
  it('renders persisted FAILED with unknown usage and no success navigation, retry or refresh',async()=>{
    setup({write:()=>response({...result,status:'FAILED',error_code:'MODEL_MALFORMED_RESPONSE',provider_model:null,provider:null,usage:undefined,output:null})});open();await screen.findByRole('table');selectAll();fireEvent.click(screen.getByRole('button',{name:'Generate tests for selected'}));
    const completion=await screen.findByRole('region',{name:'Generation completion'});expect(completion).toHaveTextContent('FAILED');expect(completion).toHaveTextContent('MODEL_MALFORMED_RESPONSE');expect(completion).toHaveTextContent('Usage unavailable');
    expect(within(completion).queryByRole('link')).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Traceability'})).toBeInTheDocument();
    expect(posts()).toHaveLength(1);expect(fetch).toHaveBeenCalledTimes(5);
  });
  it('discards a late generation response after navigation without subsequent reads',async()=>{
    const pending=deferred<Response>();setup({write:()=>pending.promise});open();await screen.findByRole('table');selectAll();fireEvent.click(screen.getByRole('button',{name:'Generate tests for selected'}));
    fireEvent.click(screen.getByRole('link',{name:'Leave'}));await screen.findByRole('heading',{name:'Page not found'});const count=vi.mocked(fetch).mock.calls.length;
    await act(async()=>pending.resolve(response(result)));expect(fetch).toHaveBeenCalledTimes(count);expect(screen.queryByRole('region',{name:'Generation completion'})).not.toBeInTheDocument();
  });
});


it('keeps secondary generation selection approved-only with bounded select/deselect controls',async()=>{
  setup({truncated:true});open('test-specifications');
  const form=await screen.findByRole('form',{name:'Generate Test Specifications'});
  const boxes=within(form).getAllByRole('checkbox');expect(boxes).toHaveLength(3);
  expect(boxes[0]).toBeEnabled();expect(boxes[1]).toBeDisabled();expect(boxes[2]).toBeDisabled();
  expect(within(form).getAllByText(/Approve this Requirement before generating tests/)).toHaveLength(2);
  fireEvent.click(within(form).getByRole('button',{name:'Select all approved visible'}));expect(boxes[0]).toBeChecked();
  fireEvent.click(within(form).getByRole('button',{name:'Deselect all'}));expect(boxes[0]).not.toBeChecked();
  expect(posts()).toHaveLength(0);fireEvent.click(within(form).getByRole('button',{name:'Select all approved visible'}));fireEvent.submit(form);
  await screen.findByRole('region',{name:'AI Test Generation result'});expect(posts()).toHaveLength(1);
  expect(JSON.parse(String(posts()[0][1]?.body)).requirement_ids).toEqual([requirement.id]);
});
