import { act,fireEvent,render,screen,waitFor } from '@testing-library/react';
import { describe,it,expect,vi } from 'vitest';
import { PreparationSources, SourceExtraction } from './PreparationSources';
import { PreparationRecovery } from './PreparationRecovery';
import { blockedRequirement,campaign } from '../test/campaigns';
import { page,response,deferred } from '../test/fixtures';
import type { RequirementExtraction } from '../api/campaignTypes';
const p=campaign.project_id,c=campaign.id,root=`/api/v1/projects/${p}/campaigns/${c}`;
const first:RequirementExtraction={id:'a1',project_id:p,campaign_id:c,source_id:'s1',source_hash:'a'.repeat(64),contract_version:'requirements-v1',attempt_number:1,parent_attempt_id:null,is_latest:true,
  status:'FAILED',error_code:'EXTRACTION_INVALID_CITATION',retryable:true,started_at:campaign.created_at,finished_at:campaign.updated_at,configured_model:'configured',provider_model:'provider',usage:{total_tokens:{total:30,known_sum:30}}};
const second:RequirementExtraction={...first,id:'a2',attempt_number:2,parent_attempt_id:first.id,status:'SUCCEEDED',error_code:null,retryable:false};
const posts=()=>vi.mocked(fetch).mock.calls.filter(([,options])=>options?.method==='POST');
const changed=()=>vi.fn(async()=>{});

describe('explicit extraction recovery',()=>{
  it('replaces misleading initial Extract with new-call Retry and retains failed history',async()=>{
    const pending=deferred<Response>();let done=false;const refresh=changed();
    vi.mocked(fetch).mockImplementation((input,options)=>{
      if(options?.method==='POST')return pending.promise;
      expect(String(input)).toBe(root+'/sources/s1/extractions?limit=50');
      return Promise.resolve(response(page(done?[second,{...first,is_latest:false}]:[first])));
    });
    render(<SourceExtraction source={{id:'s1',name:'PRD',latest_extraction:first}} projectId={p} campaignId={c} changed={refresh}/>);
    expect(screen.queryByRole('button',{name:'Extract Requirements'})).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
    expect(screen.getByText(/new provider call and may consume tokens/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'View extraction history'}));await screen.findByRole('heading',{name:'Extraction attempt history'});
    const retry=screen.getByRole('button',{name:'Retry Extraction'});fireEvent.click(retry);fireEvent.click(retry);
    expect(screen.getByRole('button',{name:'Extracting…'})).toBeDisabled();expect(posts()).toHaveLength(1);
    expect(posts()[0][0]).toBe(root+'/extractions/a1/retry');done=true;await act(async()=>pending.resolve(response(second)));
    expect(await screen.findByText(/Historical attempt/)).toHaveTextContent('FAILED');
    expect(screen.getByText(/Requirement extraction complete/)).toBeInTheDocument();expect(refresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button',{name:'Retry Extraction'})).not.toBeInTheDocument();expect(posts()).toHaveLength(1);
  });
  it('recovers a saved clarification source after reload without detail fan-out or automatic revision',async()=>{
    vi.mocked(fetch).mockResolvedValue(response(page([{id:'addendum',name:'Clarification: LOGIN',source_type:'TEXT',status:'INGESTED',created_at:campaign.created_at,clarification_requirement_id:blockedRequirement.id}])));
    render(<PreparationSources projectId={p} campaignId={c} changed={changed()}/>);
    expect(await screen.findByRole('button',{name:'Revise Requirement'})).toBeEnabled();
    expect(screen.getByText(new RegExp('Clarification addendum for Requirement '+blockedRequirement.id))).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);expect(posts()).toHaveLength(0);
  });
  it('shows honest unknown usage and nonretryable corrective guidance',()=>{
    render(<SourceExtraction source={{id:'s1',name:'PRD',latest_extraction:{...first,retryable:false,error_code:'MODEL_AUTHENTICATION',usage:undefined}}} projectId={p} campaignId={c} changed={changed()}/>);
    expect(screen.getByText(/Not eligible. Correct the source or provider configuration/)).toBeInTheDocument();
    expect(screen.getByText(/Usage unavailable/)).toBeInTheDocument();expect(screen.getByText('Total').closest('div')).toHaveTextContent('Unavailable');expect(screen.queryByRole('button',{name:'Retry Extraction'})).not.toBeInTheDocument();expect(fetch).not.toHaveBeenCalled();
  });
  it('never retries pending/uncertain extraction and GET history never writes',async()=>{
    vi.mocked(fetch).mockResolvedValue(response(page([{...first,status:'STARTED',error_code:null}])));
    render(<SourceExtraction source={{id:'s1',name:'PRD',latest_extraction:{...first,status:'STARTED',error_code:null,retryable:false}}} projectId={p} campaignId={c} changed={changed()}/>);
    expect(screen.getByText(/do not replay uncertain provider work/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'View extraction history'}));await screen.findByRole('heading',{name:'Extraction attempt history'});expect(posts()).toHaveLength(0);
  });
  it('shows safe errors without automatic mutation retries or provider response leakage',async()=>{
    vi.mocked(fetch).mockResolvedValue(response({stack:'PRIVATE_PROVIDER'},500));
    render(<SourceExtraction source={{id:'s1',name:'PRD',latest_extraction:first}} projectId={p} campaignId={c} changed={changed()}/>);
    fireEvent.click(screen.getByRole('button',{name:'Retry Extraction'}));expect(await screen.findByRole('alert')).toHaveTextContent('HTTP_ERROR');
    expect(document.body).not.toHaveTextContent('PRIVATE_PROVIDER');expect(posts()).toHaveLength(1);
  });
  it('ignores stale retry completion after unmount',async()=>{
    const pending=deferred<Response>();vi.mocked(fetch).mockReturnValue(pending.promise);const refresh=changed();
    const view=render(<SourceExtraction source={{id:'s1',name:'PRD',latest_extraction:first}} projectId={p} campaignId={c} changed={refresh}/>);
    fireEvent.click(screen.getByRole('button',{name:'Retry Extraction'}));view.unmount();await act(async()=>pending.resolve(response(second)));
    expect(refresh).not.toHaveBeenCalled();expect(posts()).toHaveLength(1);
  });
});
describe('grounded clarification and version history',()=>{
  const evidence={id:'clarification',source_id:'addendum',requirement_id:blockedRequirement.id,request_key:'intent',first_fact_line:4};
  it('saves inert evidence without a model, then explicitly revises and displays version history',async()=>{
    const pending=deferred<Response>();const refresh=changed();
    vi.mocked(fetch).mockImplementation((input,options)=>{
      const url=String(input);
      if(url.endsWith('/clarifications'))return pending.promise;
      if(url.endsWith('/extract-requirements'))return Promise.resolve(response({...second,source_id:'addendum'}));
      if(url.endsWith('/history'))return Promise.resolve(response(page([{requirement:blockedRequirement,version:1,is_current:false,supersedes_id:null},{requirement:{...blockedRequirement,id:'v2',review_status:'READY_FOR_REVIEW',information_markers:[]},version:2,is_current:true,supersedes_id:blockedRequirement.id}])));
      throw new Error('Unexpected '+url+options?.method);
    });
    render(<PreparationRecovery requirement={blockedRequirement} projectId={p} campaignId={c} changed={refresh}/>);
    expect(fetch).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Add Clarification / Provide Missing Information'}));
    expect(screen.getByText(/requires review again and retires tests/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'<script>inert</script> Missing facts'}});
    const form=screen.getByRole('form',{name:'Provide missing information'});fireEvent.submit(form);fireEvent.submit(form);expect(posts()).toHaveLength(1);
    expect(JSON.parse(String(posts()[0][1]?.body))).toMatchObject({content:'<script>inert</script> Missing facts'});
    await act(async()=>pending.resolve(response(evidence,201)));
    expect(await screen.findByText(/Clarification saved/)).toBeInTheDocument();expect(document.querySelector('script')).toBeNull();expect(posts()).toHaveLength(1);
    fireEvent.click(screen.getByRole('button',{name:'Revise Requirement'}));await screen.findByText(/Requirement revision complete/);expect(posts()).toHaveLength(2);expect(refresh).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button',{name:'View Requirement version history'}));
    expect(await screen.findByText('Version 2 — Current Requirement')).toBeInTheDocument();expect(screen.getByText('Version 1 — Superseded Requirement')).toBeInTheDocument();
    expect(screen.getByText(/Historical content cannot be revised or approved/)).toBeInTheDocument();
  });
  it('retains the same clarification request body on explicit error retry',async()=>{
    vi.mocked(fetch).mockImplementation(async()=>response({error:{code:'PERSISTENCE_ERROR',message:'Persistence operation failed'}},500));
    render(<PreparationRecovery requirement={blockedRequirement} projectId={p} campaignId={c} changed={changed()}/>);
    fireEvent.click(screen.getByRole('button',{name:'Add Clarification / Provide Missing Information'}));fireEvent.change(screen.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'Grounded facts'}});
    fireEvent.submit(screen.getByRole('form',{name:'Provide missing information'}));await screen.findByRole('alert');expect(posts()).toHaveLength(1);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Retry Save Clarification'})).toBeEnabled());fireEvent.click(screen.getByRole('button',{name:'Retry Save Clarification'}));
    await waitFor(()=>expect(posts()).toHaveLength(2));expect(posts()[0][1]?.body).toBe(posts()[1][1]?.body);
  });
  it('rejects oversized UTF-8 facts before any request',()=>{
    render(<PreparationRecovery requirement={blockedRequirement} projectId={p} campaignId={c} changed={changed()}/>);
    fireEvent.click(screen.getByRole('button',{name:'Add Clarification / Provide Missing Information'}));fireEvent.change(screen.getByLabelText('Missing facts (no credentials or secrets)'),{target:{value:'é'.repeat(2001)}});
    fireEvent.submit(screen.getByRole('form',{name:'Provide missing information'}));expect(screen.getByText(/up to 4,000 UTF-8 bytes/)).toBeInTheDocument();expect(fetch).not.toHaveBeenCalled();
  });
});
