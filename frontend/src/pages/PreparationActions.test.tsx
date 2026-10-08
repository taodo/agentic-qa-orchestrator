import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { campaign, requirement, blockedRequirement, specification, blockedSpecification, readiness, traceability } from '../test/campaigns';
import { deferred, page, response } from '../test/fixtures';
import { CSV_COLUMNS, CSV_TEMPLATE, MARKDOWN_TEMPLATE } from '../components/PreparationTests';
import type { CampaignSource, CampaignRequirement, CampaignTestSpecification, CampaignView } from '../api/campaignTypes';
const base='/projects/'+campaign.project_id+'/campaigns/'+campaign.id, api='/api/v1'+base;
const readyReq: CampaignRequirement={...requirement,review_status:'READY_FOR_REVIEW'};
const readyTest: CampaignTestSpecification={...specification,review_status:'READY_FOR_REVIEW'};
const source: CampaignSource={id:'source-a',project_id:campaign.project_id,campaign_id:campaign.id,name:'Checkout PRD',source_type:'TEXT',status:'INGESTED',content_hash:'a'.repeat(64),raw_hash:'a'.repeat(64),normalization_version:'utf8-nfc-lf-v1',original_bytes:30,normalized_chars:30,line_count:2,error_code:null,created_at:campaign.created_at};
const attempt={id:'attempt-a',project_id:campaign.project_id,campaign_id:campaign.id,status:'SUCCEEDED',started_at:campaign.created_at,finished_at:campaign.updated_at,error_code:null};
const imported={id:'import-a',status:'IMPORTED',test_count:1,error_code:null};
const receipt=(kind:string,id:string)=>({project_id:campaign.project_id,campaign_id:campaign.id,object_id:id,object_kind:kind,review_status:'APPROVED',evidence:{object_id:id,object_kind:kind,status:'APPROVED',reviewer_label:'qa-human',approved_at:campaign.updated_at,note:'Reviewed against PRD.',content_hash:'c'.repeat(64)}});
type State={sources:CampaignSource[];requirements:CampaignRequirement[];tests:CampaignTestSpecification[];campaign:CampaignView};
function mock(write?: (path:string,body:Record<string,unknown>,state:State)=>Response|Promise<Response>, overrides:Partial<State>={}) {
  const state:State={sources:[],requirements:[readyReq,blockedRequirement],tests:[readyTest,blockedSpecification],campaign,...overrides};
  const calls=vi.mocked(fetch).mockImplementation((input,options)=>{
    const url=String(input);
    if(options?.method==='POST') return Promise.resolve(write?.(url.slice(api.length),JSON.parse(String(options.body)),state) ?? response({error:{code:'INVALID_INPUT',message:'Not configured in this test'}},422));
    if(url===api) return Promise.resolve(response(state.campaign));
    if(url===api+'/readiness') return Promise.resolve(response(readiness));
    if(url===api+'/sources?limit=50') return Promise.resolve(response(page(state.sources)));
    if(url===api+'/requirements?limit=50') return Promise.resolve(response(page(state.requirements)));
    if(url===api+'/test-specifications?limit=50') return Promise.resolve(response(page(state.tests)));
    if(url===api+'/traceability?limit=50') return Promise.resolve(response(traceability));
    if(url.endsWith('/review')) return Promise.resolve(response(receipt(url.includes('test-specifications')?'TEST_SPECIFICATION':'REQUIREMENT',url.split('/').at(-2)!)));
    return Promise.reject(new Error('Unexpected mocked GET '+url));
  });return {state,calls};
}
function open(section='requirements') {return render(<MemoryRouter initialEntries={[section?base+'/'+section:base]}><App /></MemoryRouter>);}
const posts=()=>vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method==='POST');
function fillSource(content='Accept a valid payment.') {fireEvent.change(screen.getByLabelText('Source name'),{target:{value:'Checkout PRD'}});fireEvent.change(screen.getByLabelText('Specification content'),{target:{value:content}});}
function fillImport(content=CSV_TEMPLATE) {fireEvent.change(screen.getByLabelText('Import name'),{target:{value:'Existing tests'}});fireEvent.change(screen.getByLabelText('Test case content'),{target:{value:content}});}
function submit(name:string){fireEvent.submit(screen.getByRole('form',{name}));}

 describe('source ingestion and explicit extraction',()=>{
  it.each(['TEXT','MARKDOWN'])('adds inert %s content without extracting, even when input is repeated',async type=>{
    const content='<script>bad()</script> [url](https://invalid.example)';const {state}=mock((_path,body,s)=>{s.sources=[{...source,source_type:body.source_type as 'TEXT'|'MARKDOWN'}];return response(s.sources[0],201);});open();
    await screen.findByLabelText('Source name');fillSource(content);fireEvent.change(screen.getByLabelText('Source type'),{target:{value:type}});
    submit('Add specification');await screen.findByText(/Source available/);
    expect(posts()).toHaveLength(1);expect(JSON.parse(String(posts()[0][1]?.body))).toEqual({name:'Checkout PRD',source_type:type,content});
    expect(state.sources).toHaveLength(1);expect(screen.getByText(/PDF is not supported yet/)).toBeInTheDocument();expect(document.querySelector('script')).toBeNull();
    expect(screen.getByRole('button',{name:'Extract Requirements'})).toBeInTheDocument();expect(posts().some(([url])=>String(url).includes('extract'))).toBe(false);
    submit('Add specification');await waitFor(()=>expect(posts()).toHaveLength(2));expect(screen.queryByText(/Created new/i)).not.toBeInTheDocument();
  });
  it('shows rejected/PDF source metadata without extraction and discloses bounds',async()=>{
    mock(undefined,{sources:[{...source,status:'REJECTED',source_type:'PDF',error_code:'PDF_UNSUPPORTED'}]});open();
    expect(await screen.findByText(/PDF_UNSUPPORTED/)).toBeInTheDocument();expect(screen.getByText(/30 original bytes/)).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Extract Requirements'})).not.toBeInTheDocument();
  });
  it('extracts only on explicit click, blocks duplicates and refreshes Requirements/readiness/coverage',async()=>{
    const pending=deferred<Response>();const {state}=mock(()=>pending.promise,{sources:[source],requirements:[]});open();
    const button=await screen.findByRole('button',{name:'Extract Requirements'});expect(posts()).toHaveLength(0);fireEvent.click(button);fireEvent.click(button);
    expect(screen.getByRole('button',{name:'Extracting…'})).toBeDisabled();expect(posts()).toHaveLength(1);
    state.requirements=[readyReq];await act(async()=>pending.resolve(response({...attempt,source_id:source.id})));
    expect(await screen.findByText(/Requirement extraction complete\./)).toBeInTheDocument();expect(await screen.findByText(readyReq.title)).toBeInTheDocument();
    for(const path of ['/requirements?limit=50','/readiness','/traceability?limit=50']) expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+path)).toHaveLength(2);
  });
  it.each([409,500])('does not retry extraction error %s and never shows raw provider data',async status=>{
    mock(()=>response({stack:'PRIVATE_PROVIDER_RESPONSE'},status),{sources:[source]});open();fireEvent.click(await screen.findByRole('button',{name:'Extract Requirements'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP_ERROR');expect(document.body).not.toHaveTextContent('PRIVATE_PROVIDER_RESPONSE');expect(posts()).toHaveLength(1);
  });
  it('shows terminal FAILED attempt honestly without a success refresh or replay',async()=>{
    mock(()=>response({...attempt,status:'FAILED',error_code:'MODEL_INVALID_OUTPUT'}),{sources:[source]});open();fireEvent.click(await screen.findByRole('button',{name:'Extract Requirements'}));
    const summary=await screen.findByRole('region',{name:'Requirement Extraction result'});expect(summary).toHaveTextContent('FAILED');expect(within(summary).getByText('MODEL_INVALID_OUTPUT')).toBeInTheDocument();expect(posts()).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/requirements?limit=50')).toHaveLength(1);
  });
  it('keeps source input after a safe error and rejects oversized UTF-8 before POST',async()=>{
    mock(()=>response({error:{code:'SOURCE_SIZE_LIMIT',message:'Source content is too large'}},413));open();await screen.findByLabelText('Source name');fillSource();submit('Add specification');
    expect(await screen.findByRole('alert')).toHaveTextContent('SOURCE_SIZE_LIMIT');expect(screen.getByLabelText('Source name')).toHaveValue('Checkout PRD');
    fillSource('あ'.repeat(22000));submit('Add specification');expect(await screen.findByText(/Enter a name of 1–200/)).toBeInTheDocument();expect(posts()).toHaveLength(1);
  });
 });

 describe('explicit deterministic import and selected generation',()=>{
  it.each(['CSV','MARKDOWN'])('imports accepted %s text and refreshes normalized tests without claiming new creation',async format=>{
    mock((_path,_body,s)=>{s.tests=[readyTest];return response(imported,201);},{tests:[]});open('test-specifications');await screen.findByLabelText('Import name');
    fillImport(format==='CSV'?CSV_TEMPLATE:MARKDOWN_TEMPLATE);fireEvent.change(screen.getByLabelText('Import format'),{target:{value:format}});submit('Import Test Cases');
    expect(await screen.findByText(/Test import complete/)).toHaveTextContent('IMPORTED. Cases: 1');expect(await screen.findByText(readyTest.title)).toBeInTheDocument();
    expect(JSON.parse(String(posts()[0][1]?.body))).toEqual({name:'Existing tests',format,content:format==='CSV'?CSV_TEMPLATE:MARKDOWN_TEMPLATE});
    expect(screen.getByText(/XLSX is not supported yet/)).toBeInTheDocument();expect(posts()).toHaveLength(1);
  });
  it('renders exact import template guidance as inert text',async()=>{
    mock();open('test-specifications');fireEvent.click(await screen.findByText('Import format help and templates'));
    const help=document.querySelector('.import-help')!;expect(help.textContent).toContain(CSV_COLUMNS);expect(help.textContent).toContain('# Test cases');expect(screen.getByText(/never fuzzy-matched links/)).toBeInTheDocument();
    expect(CSV_TEMPLATE.split('\n')[0]).toBe(CSV_COLUMNS);expect(MARKDOWN_TEMPLATE).toContain('"expected": "User is signed in"');expect(document.querySelector('script')).toBeNull();
  });
  it('discloses rejected import, preserves text and does not refresh or retry',async()=>{
    mock(()=>response({...imported,status:'REJECTED',test_count:0,error_code:'IMPORT_INVALID_SCHEMA'}));open('test-specifications');await screen.findByLabelText('Import name');fillImport('bad input');submit('Import Test Cases');
    expect(await screen.findByText(/IMPORT_INVALID_SCHEMA/)).toHaveTextContent('REJECTED. Cases: 0');expect(screen.getByLabelText('Test case content')).toHaveValue('bad input');expect(posts()).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/test-specifications?limit=50')).toHaveLength(1);
  });
  it('has no implicit selection and generates from only explicit unique IDs, preventing duplicates',async()=>{
    const pending=deferred<Response>();const {state}=mock(()=>pending.promise);open('test-specifications');
    const checkbox=await screen.findByRole('checkbox',{name:/REQ-PAY/});expect(checkbox).not.toBeChecked();expect(screen.getByRole('button',{name:'Generate Test Specifications'})).toBeDisabled();expect(posts()).toHaveLength(0);
    fireEvent.click(checkbox);expect(screen.getByText(/Selected: 1 of at most 20/)).toBeInTheDocument();submit('Generate Test Specifications');submit('Generate Test Specifications');
    expect(posts()).toHaveLength(1);expect(JSON.parse(String(posts()[0][1]?.body))).toEqual({requirement_ids:[requirement.id]});expect(screen.getByRole('button',{name:'Generating…'})).toBeDisabled();
    state.tests=[{...readyTest,provenance:{...readyTest.provenance,origin:'AI_GENERATED',contract_version:'test-specs-v1',start_line:null,end_line:null}}];await act(async()=>pending.resolve(response(attempt)));
    expect(await screen.findByText(/Test Specifications generated. Review is required/)).toBeInTheDocument();expect(await screen.findByText('AI-generated')).toBeInTheDocument();expect(posts()).toHaveLength(1);
  });
  it('enforces 20 selected Requirements and never includes an omitted record',async()=>{
    mock(()=>response(attempt),{requirements:Array.from({length:21},(_,i)=>({...readyReq,id:'r'+i,logical_key:'REQ-'+i,title:'Requirement '+i}))});open('test-specifications');
    const boxes=await screen.findAllByRole('checkbox');boxes.slice(0,20).forEach(box=>fireEvent.click(box));expect(boxes[20]).toBeDisabled();submit('Generate Test Specifications');
    await screen.findByText(/Test Specifications generated/);const ids=JSON.parse(String(posts()[0][1]?.body)).requirement_ids;expect(ids).toHaveLength(20);expect(new Set(ids).size).toBe(20);expect(ids).not.toContain('r20');
  });
  it('retains selection after provider failure without automatic retry',async()=>{
    mock(()=>response({error:{code:'MODEL_TIMEOUT',message:'Model request timed out'}},409));open('test-specifications');const box=await screen.findByRole('checkbox',{name:/REQ-PAY/});fireEvent.click(box);submit('Generate Test Specifications');
    expect(await screen.findByRole('alert')).toHaveTextContent('MODEL_TIMEOUT');expect(box).toBeChecked();expect(posts()).toHaveLength(1);
  });
 });

 describe('human review and contextual Campaign transitions',()=>{
  it.each(['Requirement','Test Specification'])('records %s approval explicitly with asserted label and refreshes scoped data',async kind=>{
    mock((path,body,s)=>{expect(body).toEqual({action:'APPROVE',reviewer_label:'qa-human',note:'Reviewed against PRD.'});if(kind==='Requirement')s.requirements=[requirement];else s.tests=[specification];return response(receipt(kind==='Requirement'?'REQUIREMENT':'TEST_SPECIFICATION',kind==='Requirement'?requirement.id:specification.id));});open(kind==='Requirement'?'requirements':'test-specifications');
    const form=await screen.findByRole('form',{name:'Approve '+kind});fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa-human'}});fireEvent.change(within(form).getByLabelText('Review note (optional)'),{target:{value:'Reviewed against PRD.'}});fireEvent.submit(form);
    expect(await screen.findByText('Approval recorded.')).toBeInTheDocument();expect(posts()).toHaveLength(1);
    await screen.findByText('Approved',{selector:'.badge'}); const evidenceButton=screen.queryByRole('button',{name:'View approval evidence'}); if(evidenceButton) fireEvent.click(evidenceButton); expect(await screen.findByText('qa-human')).toBeInTheDocument();expect(screen.getByText('Reviewed against PRD.')).toBeInTheDocument();expect(screen.getByText('Reviewer label (operator assertion)')).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/readiness')).toHaveLength(2);
  });
  it('blocks Draft/clarification and unresolved/missing links without fake resolution',async()=>{
    mock(undefined,{requirements:[blockedRequirement,{...readyReq,id:'draft',review_status:'DRAFT'}],tests:[blockedSpecification,{...readyTest,id:'unlinked',requirement_ids:[]}]});open();
    await screen.findByText(blockedRequirement.title);expect(screen.queryByRole('button',{name:'Approve Requirement'})).not.toBeInTheDocument();expect(screen.getAllByText(/No Resolve-to-Approved action is available/)).toHaveLength(2);
    fireEvent.click(screen.getByRole('link',{name:'Test Specifications'}));await screen.findByText(blockedSpecification.title);expect(screen.queryByRole('button',{name:'Approve Test Specification'})).not.toBeInTheDocument();expect(screen.getByText(/UNKNOWN-CURRENCY/)).toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it('requires a valid reviewer label and retains note after a safe approval conflict',async()=>{
    mock(()=>response({error:{code:'REVIEW_CONFLICT',message:'Review intent conflicts with existing evidence'}},409));open();const form=await screen.findByRole('form',{name:'Approve Requirement'});fireEvent.submit(form);expect(posts()).toHaveLength(0);
    fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa-human'}});fireEvent.change(within(form).getByLabelText('Review note (optional)'),{target:{value:'Keep this note'}});fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent('REVIEW_CONFLICT');expect(within(form).getByLabelText('Review note (optional)')).toHaveValue('Keep this note');expect(posts()).toHaveLength(1);
  });
  it('loads approved evidence only on request without redundant approval',async()=>{
    mock(undefined,{requirements:[requirement]});open();const button=await screen.findByRole('button',{name:'View approval evidence'});expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).endsWith('/review'))).toBe(false);fireEvent.click(button);expect(await screen.findByText('qa-human')).toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it('uses both explicit lifecycle actions without equating Approved and Ready',async()=>{
    mock((_path,body,s)=>{s.campaign={...s.campaign,status:body.status as CampaignView['status']};return response(s.campaign);},{campaign:{...campaign,status:'DRAFT'}});open('');
    fireEvent.click(await screen.findByRole('button',{name:'Submit Campaign for Review'}));fireEvent.click(await screen.findByRole('button',{name:'Approve Campaign Preparation'}));
    await screen.findByText('Campaign preparation updated. Readiness is assessed separately.');expect(posts().map(([,o])=>JSON.parse(String(o?.body)))).toEqual([{status:'READY_FOR_REVIEW'},{status:'APPROVED'}]);expect(await screen.findByText('Not ready',{selector:'.badge'})).toBeInTheDocument();expect(screen.queryByRole('button',{name:'Approve Campaign Preparation'})).not.toBeInTheDocument();
  });
 });

it.each(['extract','generate'])('discards stale %s completions after Campaign navigation',async kind=>{
  const pending=deferred<Response>();mock(()=>pending.promise,{sources:[source]});const oldMock=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input,options)=>String(input).includes('/campaigns/other') ? Promise.resolve(response(String(input).endsWith('/readiness')?{...readiness,campaign_id:'other'}:{...campaign,id:'other',name:'Other Campaign'})) : oldMock(input,options));
  render(<MemoryRouter initialEntries={[base+'/'+(kind==='extract'?'requirements':'test-specifications')]}><Link to={'/projects/'+campaign.project_id+'/campaigns/other'}>Switch Campaign</Link><App /></MemoryRouter>);
  if(kind==='extract')fireEvent.click(await screen.findByRole('button',{name:'Extract Requirements'}));else{fireEvent.click(await screen.findByRole('checkbox',{name:/REQ-PAY/}));submit('Generate Test Specifications');}
  fireEvent.click(screen.getByRole('link',{name:'Switch Campaign'}));await screen.findByRole('heading',{name:'Other Campaign'});const reads=vi.mocked(fetch).mock.calls.length;
  await act(async()=>pending.resolve(response(attempt)));expect(vi.mocked(fetch).mock.calls).toHaveLength(reads);expect(screen.queryByText(/extraction complete|Specifications generated/)).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Other Campaign'})).toBeInTheDocument();
});


it.each(['source','import','approval','transition'])('prevents duplicate pending %s writes and ignores late completions after leaving Campaign',async kind=>{
  const pending=deferred<Response>();mock(()=>pending.promise,{campaign:{...campaign,status:kind==='transition'?'DRAFT':campaign.status}});
  render(<MemoryRouter initialEntries={[kind==='transition'?base:base+'/'+(kind==='import'?'test-specifications':'requirements')]}><Link to="/missing">Leave Campaign</Link><App /></MemoryRouter>);
  let form:HTMLElement|undefined;
  if(kind==='source'){await screen.findByLabelText('Source name');fillSource();form=screen.getByRole('form',{name:'Add specification'});}
  if(kind==='import'){await screen.findByLabelText('Import name');fillImport();form=screen.getByRole('form',{name:'Import Test Cases'});}
  if(kind==='approval'){form=await screen.findByRole('form',{name:'Approve Requirement'});fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa-human'}});}
  if(kind==='transition'){
    const button=await screen.findByRole('button',{name:'Submit Campaign for Review'});fireEvent.click(button);fireEvent.click(button);expect(posts()).toHaveLength(1);
    expect(screen.getByRole('button',{name:'Updating preparation…'})).toBeDisabled();
    fireEvent.click(screen.getByRole('link',{name:'Leave Campaign'}));await screen.findByRole('heading',{name:'Page not found'});const reads=vi.mocked(fetch).mock.calls.length;
    await act(async()=>pending.resolve(response({...campaign,status:'READY_FOR_REVIEW'})));expect(vi.mocked(fetch).mock.calls).toHaveLength(reads);return;
  }
  fireEvent.submit(form!);fireEvent.submit(form!);expect(posts()).toHaveLength(1);expect(form!.querySelector('fieldset')).toBeDisabled();
  fireEvent.click(screen.getByRole('link',{name:'Leave Campaign'}));await screen.findByRole('heading',{name:'Page not found'});const reads=vi.mocked(fetch).mock.calls.length;
  await act(async()=>pending.resolve(response(kind==='source'?source:kind==='import'?imported:receipt('REQUIREMENT',requirement.id))));
  expect(vi.mocked(fetch).mock.calls).toHaveLength(reads);expect(screen.queryByText(/Source available|Test import complete|Approval recorded/)).not.toBeInTheDocument();
});

it('keeps approval evidence errors safe and never re-approves automatically',async()=>{
  mock(undefined,{tests:[specification]});const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input,options)=>String(input).endsWith('/review')?Promise.resolve(response({stack:'PRIVATE_APPROVAL_EXCEPTION'},500)):current(input,options));
  open('test-specifications');fireEvent.click(await screen.findByRole('button',{name:'View approval evidence'}));expect(await screen.findByRole('alert')).toHaveTextContent('HTTP_ERROR');expect(document.body).not.toHaveTextContent('PRIVATE_APPROVAL_EXCEPTION');expect(posts()).toHaveLength(0);
});
it('distinguishes missing approval evidence from a fabricated reviewer',async()=>{
  mock(undefined,{requirements:[requirement]});const current=vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((input,options)=>String(input).endsWith('/review')?Promise.resolve(response({...receipt('REQUIREMENT',requirement.id),evidence:null})):current(input,options));
  open();fireEvent.click(await screen.findByRole('button',{name:'View approval evidence'}));expect(await screen.findByText('Approval evidence is unavailable in this response.')).toBeInTheDocument();expect(screen.queryByText('qa-human')).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
});
it('surfaces public-mode model unavailability without invented generated tests',async()=>{
  mock(()=>response({error:{code:'GENERATION_NOT_CONFIGURED',message:'Generation is not configured'}},409),{tests:[]});open('test-specifications');fireEvent.click(await screen.findByRole('checkbox',{name:/REQ-PAY/}));submit('Generate Test Specifications');
  expect(await screen.findByRole('alert')).toHaveTextContent('GENERATION_NOT_CONFIGURED');expect(screen.queryByText(/Specifications generated/)).not.toBeInTheDocument();expect(posts()).toHaveLength(1);
});


it.each(['FAILED','STARTED'])('discloses generation %s without success copy, polling or test refresh',async status=>{
  mock(()=>response({...attempt,status,error_code:status==='FAILED'?'MODEL_INVALID_OUTPUT':null}));open('test-specifications');fireEvent.click(await screen.findByRole('checkbox',{name:/REQ-PAY/}));submit('Generate Test Specifications');
  expect(await screen.findByText(/Test generation did not complete successfully/)).toHaveTextContent('Status: '+status);expect(screen.queryByText(/Specifications generated. Review is required/)).not.toBeInTheDocument();
  expect(posts()).toHaveLength(1);expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/test-specifications?limit=50')).toHaveLength(1);
});
it('rejects oversized import bytes and reviewer note before network work',async()=>{
  mock();open('test-specifications');await screen.findByLabelText('Import name');fillImport('あ'.repeat(22000));submit('Import Test Cases');expect(posts()).toHaveLength(0);
  const form=await screen.findByRole('form',{name:'Approve Test Specification'});fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa-human'}});fireEvent.change(within(form).getByLabelText('Review note (optional)'),{target:{value:'x'.repeat(1001)}});fireEvent.submit(form);expect(posts()).toHaveLength(0);expect(within(form).getByRole('status')).toHaveTextContent('note up to 1,000');
});
it('moves focus to refreshed tests and loads fresh Traceability when visited after approval',async()=>{
  mock((_path,_body,s)=>{s.tests=[specification];return response(receipt('TEST_SPECIFICATION',specification.id));});open('test-specifications');
  const form=await screen.findByRole('form',{name:'Approve Test Specification'});fireEvent.change(within(form).getByLabelText('Reviewer label'),{target:{value:'qa-human'}});fireEvent.submit(form);await screen.findByText('Approval recorded.');
  await waitFor(()=>expect(screen.getByRole('heading',{name:'Test Specifications'})).toHaveFocus());
  fireEvent.click(screen.getByRole('link',{name:'Traceability'}));await screen.findByText('Covered',{selector:'.badge'});expect(vi.mocked(fetch).mock.calls.filter(([url])=>url===api+'/traceability?limit=50')).toHaveLength(1);expect(posts()).toHaveLength(1);
});
