import { act, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { AIActionSummary } from './AIActionSummary';
import { SourceExtraction } from './PreparationSources';
import { PreparationRecovery } from './PreparationRecovery';
import { PreparationGeneration } from './PreparationTests';
import { App } from '../app/App';
import type { RequirementExtraction, TestGeneration, ActionOutput } from '../api/campaignTypes';
import { campaign, requirement, blockedRequirement, readiness, traceability } from '../test/campaigns';
import { response, page, deferred } from '../test/fixtures';

const p=campaign.project_id,c=campaign.id,base=`/projects/${p}/campaigns/${c}`,api='/api/v1'+base;
const output:ActionOutput={generated_count:4,ready_for_review_count:3,needs_clarification_count:1,inherited_clarification_count:null,revised_requirement:null};
const attempt:RequirementExtraction={id:'attempt-summary',project_id:p,campaign_id:c,source_id:'source-summary',source_hash:'a'.repeat(64),contract_version:'requirements-v1',
  status:'SUCCEEDED',started_at:campaign.created_at,finished_at:campaign.updated_at,error_code:null,configured_model:'configured-name',provider_model:'provider-name',provider:'fixture-provider',output,
  usage:{input_tokens:{total:1169},output_tokens:{total:1737},reasoning_tokens:{total:516},total_tokens:{total:2906}}};
const generation:TestGeneration={...attempt,id:'generation-summary',requirement_versions:[],output:{...output,inherited_clarification_count:1}};
const metric=(region:HTMLElement,label:string)=>within(region).getByText(label,{selector:'dt'}).closest('div')!;
const posts=()=>vi.mocked(fetch).mock.calls.filter(([,options])=>options?.method==='POST');
const changed=()=>vi.fn(async()=>{});

it('shows exact successful extraction counts/models and all provider categories immediately',async()=>{
  vi.mocked(fetch).mockResolvedValue(response(attempt));
  render(<SourceExtraction source={{id:attempt.source_id,name:'PRD'}} projectId={p} campaignId={c} changed={changed()}/>);
  expect(fetch).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Extract Requirements'}));
  const summary=await screen.findByRole('region',{name:'Requirement Extraction result'});
  expect(within(summary).getByRole('heading',{name:'Requirement Extraction completed'})).toBeInTheDocument();
  for(const [key,value] of [['Generated','4'],['Ready for review at creation','3'],['Needs clarification at creation','1'],['Input',(1169).toLocaleString()],['Output',(1737).toLocaleString()],['Reasoning','516'],['Total',(2906).toLocaleString()]])expect(metric(summary,key)).toHaveTextContent(value);
  expect(metric(summary,'Configured model')).toHaveTextContent('configured-name');
  expect(metric(summary,'Provider model')).toHaveTextContent('provider-name');expect(metric(summary,'Provider')).toHaveTextContent('fixture-provider');
  expect(within(summary).getByRole('link',{name:'Review requirements'})).toHaveAttribute('href',base+'/requirements#requirement-results');
  expect(posts()).toHaveLength(1);
});

it.each([
  ['total only',{total_tokens:{total:30}},['Unavailable','Unavailable','Unavailable','30']],
  ['missing',undefined,['Unavailable','Unavailable','Unavailable','Unavailable']],
  ['authoritative zero',{input_tokens:{total:0},output_tokens:{total:0},reasoning_tokens:{total:0},total_tokens:{total:0}},['0','0','0','0']],
  ['partial categories',{input_tokens:{total:10},output_tokens:{total:20},total_tokens:{total:null,known_sum:30}},['10','20','Unavailable','Unavailable']],
])('preserves %s usage without deriving categories or totals',(_label,usage,values)=>{
  render(<AIActionSummary attempt={{...attempt,usage:usage as RequirementExtraction['usage']}} kind="extraction" base={base}/>);
  const region=screen.getByRole('region');
  ['Input','Output','Reasoning','Total'].forEach((label,i)=>expect(metric(region,label).querySelector('dd')).toHaveTextContent(new RegExp('^'+values[i]+'$')));
  expect(fetch).not.toHaveBeenCalled();expect(document.body).not.toHaveTextContent(/estimated|\$/i);
});

it('does not fabricate models or output counts for older records',()=>{
  render(<AIActionSummary attempt={{...attempt,configured_model:undefined,provider_model:null,provider:null,output:null,usage:undefined}} kind="generation" base={base}/>);
  expect(screen.getByText(/Action output details are unavailable/)).toBeInTheDocument();
  expect(screen.getByText(/Usage unavailable/)).toBeInTheDocument();
  expect(screen.queryByText('Generated',{selector:'dt'})).not.toBeInTheDocument();
  ['Configured model','Provider model','Provider'].forEach(label=>expect(metric(screen.getByRole('region'),label)).toHaveTextContent('Unavailable'));
});

it('shows failed recorded usage and existing retry eligibility; viewing history is read-only',async()=>{
  const failed={...attempt,status:'FAILED' as const,error_code:'MODEL_TIMEOUT',retryable:true,attempt_number:1,output:{...output,generated_count:0,ready_for_review_count:0,needs_clarification_count:0}};
  vi.mocked(fetch).mockResolvedValue(response(page([failed])));
  render(<SourceExtraction source={{id:attempt.source_id,name:'PRD',latest_extraction:failed}} projectId={p} campaignId={c} changed={changed()}/>);
  const summary=screen.getByRole('region',{name:'Requirement Extraction result'});
  expect(within(summary).getByRole('heading',{name:'Requirement Extraction failed'})).toBeInTheDocument();
  expect(within(summary).getByText('MODEL_TIMEOUT')).toBeInTheDocument();expect(metric(summary,'Total')).toHaveTextContent((2906).toLocaleString());
  expect(screen.getByRole('button',{name:'Retry Extraction'})).toBeEnabled();expect(posts()).toHaveLength(0);
  fireEvent.click(screen.getByRole('button',{name:'View extraction history'}));await screen.findByRole('heading',{name:'Extraction attempt history'});
  fireEvent.click(screen.getByRole('button',{name:'Refresh extraction history'}));await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(vi.mocked(fetch).mock.calls.every(([url,options])=>String(url)===api+'/sources/source-summary/extractions?limit=50'&&!options?.method)).toBe(true);
});

it.each([false,true])('keeps clarification inert, then shows revised identity and remaining clarification=%s',async needs=>{
  const revised={...attempt,output:{...output,generated_count:1,ready_for_review_count:needs?0:1,needs_clarification_count:needs?1:0,revised_requirement:{id:'new-version',key:'LOGIN',logical_key:'REQ-V2-LOGIN',version:2,review_status:needs?'NEEDS_CLARIFICATION' as const:'READY_FOR_REVIEW' as const}}};
  vi.mocked(fetch).mockImplementation(async input=>response(String(input).endsWith('/clarifications')?{source_id:'addendum'}:revised));
  render(<PreparationRecovery requirement={blockedRequirement} projectId={p} campaignId={c} changed={changed()}/>);
  fireEvent.click(screen.getByRole('button',{name:'Add Clarification / Provide Missing Information'}));
  fireEvent.change(screen.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'Known facts'}});
  fireEvent.submit(screen.getByRole('form',{name:'Provide missing information'}));await screen.findByText(/Clarification saved/);
  expect(screen.queryByRole('region',{name:'Requirement Revision result'})).not.toBeInTheDocument();expect(screen.queryByText('Provider token usage')).not.toBeInTheDocument();expect(posts()).toHaveLength(1);
  fireEvent.click(screen.getByRole('button',{name:'Revise Requirement'}));
  const summary=await screen.findByRole('region',{name:'Requirement Revision result'});
  expect(summary).toHaveTextContent('Version 2');expect(summary).toHaveTextContent('new-version');expect(summary).toHaveTextContent(needs?'NEEDS_CLARIFICATION':'READY_FOR_REVIEW');
  expect(within(summary).getByRole('link',{name:'Review revised Requirement'})).toHaveAttribute('href',base+'/requirements?requirement_id=new-version');
  expect(!!within(summary).queryByText(/revised Requirement remains NEEDS_CLARIFICATION/)).toBe(needs);expect(posts()).toHaveLength(2);
});

it('retains revision result when the old Requirement unmounts during page refresh',async()=>{
  let revised=false;
  const result={...attempt,output:{...output,generated_count:1,ready_for_review_count:1,needs_clarification_count:0,revised_requirement:{id:'new-page-version',key:'PAY',logical_key:'REQ-NEW-PAY',version:2,review_status:'READY_FOR_REVIEW'}}};
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const url=String(input);
    if(options?.method==='POST'){
      if(url.endsWith('/clarifications'))return response({source_id:'addendum'});
      revised=true;return response(result);
    }
    if(url===api)return response(campaign);
    if(url===api+'/readiness')return response(readiness);
    if(url.includes('/requirements?'))return response(page(revised?[{...requirement,id:'new-page-version',title:'Revised payment'}]:[blockedRequirement]));
    if(url.includes('/traceability?'))return response(traceability);
    if(url.includes('/sources?'))return response(page([]));
    throw new Error('Unexpected read '+url);
  });
  render(<MemoryRouter initialEntries={[base+'/requirements']}><App/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button',{name:'Add Clarification / Provide Missing Information'}));
  fireEvent.change(screen.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'Grounded facts'}});
  fireEvent.submit(screen.getByRole('form',{name:'Provide missing information'}));fireEvent.click(await screen.findByRole('button',{name:'Revise Requirement'}));
  await screen.findByRole('heading',{name:'Revised payment'});
  const summary=screen.getByRole('region',{name:'Requirement Revision result'});expect(summary).toHaveTextContent('new-page-version');
  const heading=screen.getByRole('heading',{name:'Requirements',level:2});expect(heading).toHaveFocus();expect(heading.compareDocumentPosition(summary)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(posts()).toHaveLength(2);
});

it('uses generation action counts, explains inherited blockers and opens durable history lazily',async()=>{
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    if(options?.method==='POST')return response(generation);
    return response(String(input).includes('/test-generations?')?{...page([generation]),truncated:true}:page([requirement,blockedRequirement]));
  });
  const view=render(<PreparationGeneration projectId={p} campaignId={c} changed={changed()}/>);
  fireEvent.click((await screen.findAllByRole('checkbox'))[0]);fireEvent.submit(screen.getByRole('form',{name:'Generate Test Specifications'}));
  const summary=await screen.findByRole('region',{name:'AI Test Generation result'});
  expect(metric(summary,'Generated')).toHaveTextContent('4');expect(summary).toHaveTextContent('1 generated Test Specification(s) require clarification because unresolved information was inherited');
  expect(within(summary).getByRole('link',{name:'View generated tests'})).toHaveAttribute('href',base+'/test-specifications#test-specification-results');
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/test-generations?'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'View generation history'}));
  const history=await screen.findByRole('region',{name:'Test generation history'});expect(within(history).getByText(/Additional records are not included/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Refresh generation history'}));await waitFor(()=>expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/test-generations?limit=50'))).toHaveLength(2));
  expect(posts()).toHaveLength(1);view.unmount();
  render(<PreparationGeneration projectId={p} campaignId={c} changed={changed()}/>);
  fireEvent.click(screen.getByRole('button',{name:'View generation history'}));
  expect(await screen.findByRole('region',{name:'Test generation history'})).toHaveTextContent('AI Test Generation completed');expect(posts()).toHaveLength(1);
});

it('discards a late generation history response after navigation/unmount',async()=>{
  const pending=deferred<Response>();vi.mocked(fetch).mockImplementation(input=>String(input).includes('/test-generations?')?pending.promise:Promise.resolve(response(page([requirement]))));
  const view=render(<PreparationGeneration projectId={p} campaignId={c} changed={changed()}/>);
  fireEvent.click(screen.getByRole('button',{name:'View generation history'}));view.unmount();await act(async()=>pending.resolve(response(page([generation]))));
  expect(screen.queryByRole('region',{name:'Test generation history'})).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
});


it('does not attribute non-inherited generation clarification to selected Requirements',()=>{
  render(<AIActionSummary attempt={{...generation,output:{...output,inherited_clarification_count:0}}} kind="generation" base={base}/>);
  expect(screen.getByRole('region')).toHaveTextContent('Needs clarification at creation1');
  expect(screen.queryByText(/generated Test Specification\(s\) require clarification because/)).not.toBeInTheDocument();
});

it('shows persisted generation failure and usage without a success action',async()=>{
  const failed={...generation,status:'FAILED' as const,error_code:'MODEL_SERVER_ERROR',output:{...output,generated_count:0,ready_for_review_count:0,needs_clarification_count:0,inherited_clarification_count:0}};
  vi.mocked(fetch).mockImplementation(async input=>response(String(input).includes('/test-generations?')?page([failed]):page([])));
  render(<PreparationGeneration projectId={p} campaignId={c} changed={changed()}/>);
  fireEvent.click(screen.getByRole('button',{name:'View generation history'}));
  const history=await screen.findByRole('region',{name:'Test generation history'});
  expect(within(history).getByRole('heading',{name:'AI Test Generation failed'})).toBeInTheDocument();
  expect(history).toHaveTextContent('MODEL_SERVER_ERROR');expect(metric(history,'Total')).toHaveTextContent((2906).toLocaleString());
  expect(within(history).queryByRole('link',{name:'View generated tests'})).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
});


it('retains extraction result beside the focused Requirement heading after scoped refresh',async()=>{
  let completed=false;
  const source={id:attempt.source_id,name:'Current PRD',source_type:'TEXT',status:'INGESTED',created_at:campaign.created_at};
  vi.mocked(fetch).mockImplementation(async(input,options)=>{
    const url=String(input);
    if(options?.method==='POST'){completed=true;return response(attempt);}
    if(url===api)return response(campaign);
    if(url===api+'/readiness')return response(readiness);
    if(url.includes('/requirements?'))return response(page(completed?[requirement]:[]));
    if(url.includes('/traceability?'))return response(traceability);
    if(url.includes('/sources?'))return response(page([source]));
    throw new Error('Unexpected read '+url);
  });
  render(<MemoryRouter initialEntries={[base+'/requirements']}><App/></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button',{name:'Extract Requirements'}));
  await screen.findByRole('heading',{name:requirement.title});
  const summary=screen.getByRole('region',{name:'Requirement Extraction result'});
  expect(metric(summary,'Generated')).toHaveTextContent('4');
  const heading=screen.getByRole('heading',{name:'Requirements',level:2});expect(heading).toHaveFocus();expect(heading.compareDocumentPosition(summary)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(posts()).toHaveLength(1);
});
