import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Link } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { campaign, specification, blockedSpecification, requirement, blockedRequirement, readiness, traceability } from '../test/campaigns';
import { page, response, deferred } from '../test/fixtures';
import type { CampaignTestSpecification } from '../api/campaignTypes';
import { readCsv } from '../test/csv';
const base=`/projects/${campaign.project_id}/campaigns/${campaign.id}`,api='/api/v1'+base;
const ready={...specification,id:'ready',key:'READY',title:'Ready case',review_status:'READY_FOR_REVIEW' as const};
const historical={...ready,id:'historical',key:'OLD',title:'Retired case'};
const posts=()=>vi.mocked(fetch).mock.calls.filter(([,options])=>options?.method==='POST');
function setup({cases=[specification,ready,blockedSpecification],truncated=false,write}:{cases?:CampaignTestSpecification[];truncated?:boolean;write?:(url:string,body:Record<string,unknown>)=>Response|Promise<Response>}={}) {
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const url=String(input);if(options?.method==='POST')return write?.(url,JSON.parse(String(options.body)))??response({});
    if(url===api)return response(campaign);
    if(url===api+'/readiness')return response(readiness);
    if(url===api+'/test-specifications?limit=50')return response(page(cases,truncated));
    if(url===api+'/requirements?limit=50')return response(page([requirement,blockedRequirement]));
    if(url===api+'/requirements/'+requirement.id)return response(requirement);
    if(url===api+'/sources?limit=50')return response(page([]));
    if(url===api+'/traceability?limit=50')return response(traceability);
    if(url===api+'/test-specifications/historical')return response(historical);
    if(url.endsWith('/review'))return response({evidence:{reviewer_label:'qa',approved_at:campaign.updated_at,note:'Reviewed',content_hash:'hash'}});
    throw new Error('Unexpected request '+url);
  });
}
function open(suffix='/test-specifications'){return render(<MemoryRouter initialEntries={[base+suffix]}><Link to="/missing">Leave</Link><App/></MemoryRouter>);}
function caseRow(key:string){return screen.getByRole('heading',{name:key}).closest('tr')!;}
function submitBulk(){const panel=screen.getByText(/^Approve selected Test Cases \(/).closest('details')!;if(!panel.open)fireEvent.click(within(panel).getByText(/^Approve selected Test Cases \(/));fireEvent.change(screen.getByLabelText('Bulk reviewer label'),{target:{value:'qa-human'}});fireEvent.submit(screen.getByRole('form',{name:'Bulk approve Test Cases'}));}
async function blobText(blob:Blob):Promise<string>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=reject;reader.readAsText(blob);});}
function downloads(){const blobs:Blob[]=[];const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL{static createObjectURL=vi.fn((blob:Blob)=>{blobs.push(blob);return 'blob:offline';});static revokeObjectURL=vi.fn();});const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});return {blobs,click};}

describe('Test Cases current workspace',()=>{
  it('uses compact local identity, honest filters and exact visible selection',async()=>{
    setup({truncated:true});open();await screen.findByRole('table');
    expect(screen.getByRole('heading',{name:'Test Cases',level:2})).toBeInTheDocument();expect(screen.getByRole('link',{name:'Test Cases'})).toHaveAttribute('href',base+'/test-specifications');
    expect(within(caseRow(ready.title)).getByRole('rowheader')).toHaveTextContent('READYReady case');
    expect(screen.getByText(/Counts, selection and CSV exports cover returned current/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Ready for review (1)'}));expect(within(screen.getByRole('table')).getAllByRole('checkbox')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));expect(within(screen.getByRole('table')).getByRole('checkbox')).toBeChecked();
    fireEvent.click(within(screen.getByRole('heading',{name:'Test Cases',level:2}).closest('section')!).getByRole('button',{name:'Deselect all'}));expect(within(screen.getByRole('table')).getByRole('checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));fireEvent.click(screen.getByRole('button',{name:'Approved (1)'}));expect(within(screen.getByRole('table')).getByRole('checkbox')).not.toBeChecked();expect(screen.getByRole('button',{name:'Export selected CSV'})).toBeDisabled();
    expect(screen.getByText(/Additional Campaign cases are not included/)).toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it.each(['test-import','test-generation'])('keeps the existing #%s action fragment reachable',async fragment=>{
    setup();open('/test-specifications#'+fragment);await screen.findByRole('table');
    expect(document.getElementById(fragment)?.closest('details')).toHaveAttribute('open');expect(posts()).toHaveLength(0);
  });
  it('opens secondary import/generation explicitly without competing with Traceability',async()=>{
    setup();open();await screen.findByRole('table');
    const imports=document.getElementById('test-import-actions')!,generation=document.getElementById('test-generation-actions')!;
    expect(imports).not.toHaveAttribute('open');expect(generation).not.toHaveAttribute('open');
    fireEvent.click(screen.getByRole('link',{name:'Import Existing Tests'}));expect(imports).toHaveAttribute('open');
    fireEvent.click(screen.getByRole('link',{name:'Secondary generation selection'}));expect(generation).toHaveAttribute('open');
    expect(screen.getByRole('link',{name:'Design tests in Traceability'})).toHaveAttribute('href',base+'/traceability');expect(posts()).toHaveLength(0);
  });
  it('broad row click toggles, keyboard works, and controls never double-toggle',async()=>{
    setup();open();await screen.findByRole('table');const row=caseRow(ready.title),detail=row.querySelector('details')!;
    expect(detail.open).toBe(false);fireEvent.click(within(row).getByText('HIGH'));expect(detail.open).toBe(true);expect(row).toHaveAttribute('aria-expanded','true');
    fireEvent.click(within(row).getByRole('checkbox'));expect(detail.open).toBe(true);
    fireEvent.change(within(row).getByLabelText('Reviewer label'),{target:{value:'qa'}});expect(detail.open).toBe(true);
    fireEvent.click(within(row).getByRole('link',{name:requirement.id}));expect(detail.open).toBe(true);
  });
  it('keeps a row expanded while review buttons and nested provenance controls act',async()=>{
    setup({write:()=>response({error:{code:'REVIEW_CONFLICT',message:'Conflict'}},409)});open();await screen.findByRole('table');
    const row=caseRow(ready.title),detail=row.querySelector('details')!;fireEvent.click(within(row).getByRole('rowheader'));
    fireEvent.click(within(row).getByText('Provenance and audit identity'));expect(detail.open).toBe(true);
    const label=within(row).getByLabelText('Reviewer label');fireEvent.click(label);fireEvent.keyDown(label,{key:'Enter'});expect(detail.open).toBe(true);
    fireEvent.change(label,{target:{value:'qa-human'}});fireEvent.click(within(row).getByRole('button',{name:'Approve Test Case'}));
    expect(await within(row).findByRole('alert')).toHaveTextContent('REVIEW_CONFLICT');expect(detail.open).toBe(true);expect(posts()).toHaveLength(1);
  });
  it('shows a safe local export failure without sending a request',async()=>{
    setup();open();await screen.findByRole('table');const reads=vi.mocked(fetch).mock.calls.length;
    const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL{static createObjectURL=vi.fn(()=>{throw new Error('PRIVATE_EXPORT_ERROR');});});
    fireEvent.click(screen.getByRole('button',{name:'Export visible CSV'}));
    expect(screen.getByText('CSV export could not be created. No export request was sent.')).toBeInTheDocument();expect(document.body).not.toHaveTextContent('PRIVATE_EXPORT_ERROR');expect(fetch).toHaveBeenCalledTimes(reads);
  });
  it('toggles by focused row Enter/Space while summary remains a native disclosure',async()=>{
    setup();open();await screen.findByRole('table');const row=caseRow(ready.title),detail=row.querySelector('details')!;
    row.focus();fireEvent.keyDown(row,{key:'Enter'});expect(detail.open).toBe(true);fireEvent.keyDown(row,{key:' '});expect(detail.open).toBe(false);
    fireEvent.click(within(row).getByText('Review / details'));await waitFor(()=>expect(row).toHaveAttribute('aria-expanded','true'));
    fireEvent.click(within(row).getByText('HIGH'));expect(detail.open).toBe(false);
    expect(row).toHaveAttribute('tabindex','0');expect(posts()).toHaveLength(0);
  });
  it('renders structured details and reads review evidence only on explicit button',async()=>{
    setup();open();await screen.findByRole('table');const row=caseRow(specification.title);fireEvent.click(within(row).getByRole('rowheader'));
    expect(within(row).getByRole('heading',{name:'Steps and expected behavior'})).toBeInTheDocument();expect(within(row).getByText('Submit a payment')).toBeInTheDocument();expect(within(row).getByText('Expected: Payment accepted')).toBeInTheDocument();
    expect(within(row).getByText('Observed payment state')).toBeInTheDocument();expect(within(row).getByRole('link',{name:requirement.id})).toBeInTheDocument();
    const button=within(row).getByRole('button',{name:'View approval evidence'});expect(fetch).toHaveBeenCalledTimes(4);fireEvent.click(button);await within(row).findByText('Reviewer label (operator assertion)');expect(row.querySelector('details')!.open).toBe(true);expect(posts()).toHaveLength(0);
  });
  it('offers one compact bulk approval panel above the table with live eligible counts',async()=>{
    setup();open();const table=await screen.findByRole('table');
    const summary=screen.getByText('Approve selected Test Cases (0 eligible)'),panel=summary.closest('details')!;
    expect(panel).not.toHaveAttribute('open');expect(screen.getByRole('button',{name:'Export selected CSV'}).compareDocumentPosition(panel)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();expect(panel.compareDocumentPosition(table)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));expect(summary).toHaveTextContent('Approve selected Test Cases (1 eligible)');
    fireEvent.click(summary);expect(panel).toHaveAttribute('open');expect(within(panel).getByLabelText('Bulk reviewer label')).toBeVisible();expect(within(panel).getByRole('button',{name:'Confirm approval'})).toBeEnabled();
    expect(screen.getAllByRole('form',{name:'Bulk approve Test Cases'})).toHaveLength(1);expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole('button',{name:'Approved (1)'}));expect(summary).toHaveTextContent('(0 eligible)');expect(within(panel).getByRole('button',{name:'Confirm approval'})).toBeDisabled();
  });
  it('bulk approves eligible selected cases sequentially and discloses individual failures',async()=>{
    const second={...ready,id:'second',key:'SECOND',title:'Second case'},bad={...ready,id:'bad',key:'BAD',title:'Missing evidence',required_evidence:[]};const pending=deferred<Response>();
    setup({cases:[specification,ready,blockedSpecification,second,bad],write:url=>url.endsWith('/ready/review')?pending.promise:response({error:{code:'REVIEW_CONFLICT',message:'Conflict'}},409)});
    open();await screen.findByRole('table');fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));submitBulk();submitBulk();
    expect(posts()).toHaveLength(1);expect(await screen.findByText('Recording approval 1 of 2…')).toBeInTheDocument();await act(async()=>pending.resolve(response({review_status:'APPROVED'})));
    const results=await screen.findByRole('list',{name:'Bulk approval results'});expect(results).toHaveTextContent('READY: Approval recorded.');expect(results).toHaveTextContent('SECOND: REVIEW_CONFLICT');
    expect(posts().map(([url])=>String(url))).toEqual([api+'/test-specifications/ready/review',api+'/test-specifications/second/review']);
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/readiness')).toHaveLength(2);
  });
  it.each(['auth','leave'])('stops remaining bulk requests on %s',async mode=>{
    const pending=deferred<Response>();setup({cases:[ready,{...ready,id:'second'}],write:()=>pending.promise});open();await screen.findByRole('table');fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));submitBulk();
    if(mode==='leave'){fireEvent.click(screen.getByRole('link',{name:'Leave'}));await screen.findByRole('heading',{name:'Page not found'});}
    await act(async()=>pending.resolve(mode==='auth'?response({error:{code:'HOST_CSRF_REQUIRED',message:'Denied'}},403):response({})));
    if(mode==='auth')expect(await screen.findByRole('list',{name:'Bulk approval results'})).toHaveTextContent('1 remaining requests were not attempted');expect(posts()).toHaveLength(1);
  });
  it('excludes a selected historical/out-of-list detail from counts, selection, approval and CSV',async()=>{
    setup({cases:[ready],truncated:true});const {blobs,click}=downloads();open('/test-specifications?test_spec_id=historical');
    const audit=await screen.findByRole('region',{name:'Selected Test Case audit detail'});expect(audit).toHaveTextContent('read-only');expect(within(audit).queryByRole('form')).not.toBeInTheDocument();
    expect(within(screen.getByRole('table')).getAllByRole('checkbox')).toHaveLength(1);fireEvent.click(screen.getByRole('button',{name:'Select all visible'}));fireEvent.click(screen.getByRole('button',{name:'Export selected CSV'}));
    const rows=readCsv(await blobText(blobs[0]));expect(rows).toHaveLength(2);expect(rows[1][0]).toBe(ready.title);expect(rows.flat()).not.toContain(historical.title);
    expect(fetch).toHaveBeenCalledTimes(5);expect(posts()).toHaveLength(0);click.mockRestore();
  });
  it('exports exactly filtered visible/selected current cases, without extra reads or provider actions',async()=>{
    setup({truncated:true});const {blobs,click}=downloads();open();await screen.findByRole('table');const reads=vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole('button',{name:'Needs clarification (1)'}));fireEvent.click(screen.getByRole('button',{name:'Export visible CSV'}));
    expect(readCsv(await blobText(blobs[0]))[1][0]).toBe(blockedSpecification.title);
    fireEvent.click(screen.getByRole('button',{name:'All (3)'}));fireEvent.click(screen.getByRole('checkbox',{name:'Select PAY'}));fireEvent.click(screen.getByRole('button',{name:'Export selected CSV'}));
    const rows=readCsv(await blobText(blobs[1]));expect(rows).toHaveLength(2);expect(rows[1][0]).toBe(specification.title);expect(fetch).toHaveBeenCalledTimes(reads);expect(posts()).toHaveLength(0);click.mockRestore();
  });
});

describe('Requirements broad row disclosure',()=>{
  it('toggles broad area and keyboard, but not checkbox, clarification form or nested controls',async()=>{
    setup();open('/requirements');await screen.findByRole('table');const row=screen.getByRole('heading',{name:blockedRequirement.title}).closest('tr')!,detail=row.querySelector('details')!;
    fireEvent.click(within(row).getByRole('rowheader'));
    expect(detail.open).toBe(true);
    fireEvent.click(within(row).getByRole('checkbox'));
    expect(detail.open).toBe(true);
    fireEvent.click(within(row).getByText(/Source evidence/));expect(detail.open).toBe(true);
    fireEvent.click(within(row).getByRole('button',{name:'Add Clarification / Provide Missing Information'}));expect(detail.open).toBe(true);
    fireEvent.change(within(row).getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'USD only'}});fireEvent.keyDown(within(row).getByLabelText('Missing facts (no credentials or secrets)'),{key:' '});expect(detail.open).toBe(true);
    row.focus();fireEvent.keyDown(row,{key:'Enter'});expect(detail.open).toBe(false);fireEvent.keyDown(row,{key:' '});expect(detail.open).toBe(true);
    fireEvent.click(within(row).getByText('Add info / Clarify'));await waitFor(()=>expect(row).toHaveAttribute('aria-expanded','false'));expect(posts()).toHaveLength(0);
  });
});
