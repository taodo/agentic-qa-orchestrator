import { act,fireEvent,render,screen,waitFor,within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect,it,vi } from 'vitest';
import { App } from '../app/App';
import { TargetManager } from './Targets';
import { campaign,readiness } from '../test/campaigns';
import { page,response,project,deferred } from '../test/fixtures';
const base=`/projects/${project.id}/campaigns/${campaign.id}`,api='/api/v1'+base;
const target={id:'target-a',project_id:project.id,name:'Staging WEB',type:'WEB',environment:'STAGING',configuration:{base_url:'https://staging.example.com'},created_at:campaign.created_at,updated_at:campaign.updated_at};
const snapshot={schema_version:'web-target-snapshot-v1',target_id:target.id,project_id:project.id,name:target.name,type:'WEB',environment:'STAGING',base_url:'https://staging.example.com'};
function setup(extra:(url:string,options?:RequestInit)=>Response|Promise<Response>|undefined=()=>undefined,associated=false){vi.mocked(fetch).mockImplementation(async(input,options)=>{
  const url=String(input),custom=extra(url,options);if(custom)return custom;
  if(url===api)return response({...campaign,target_id:associated?target.id:null});
  if(url===api+'/readiness')return response(readiness);
  if(url===`/api/v1/projects/${project.id}/targets?limit=50`)return response(page([target]));
  if(url===api+'/target')return response(target);
  if(url===`/api/v1/projects/${project.id}`)return response(project);
  return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
const open=(path:string)=>render(<MemoryRouter initialEntries={[path]}><App/></MemoryRouter>);
const mutations=()=>vi.mocked(fetch).mock.calls.filter(([,o])=>o?.method && o.method!=='GET');

it('creates/edits a WEB Target with no workspace prerequisites, fetching or implicit mutation',async()=>{
  let body:unknown;setup((url,options)=>{if(url.endsWith('/targets') && options?.method==='POST'){body=JSON.parse(options.body as string);return response(target);}if(url.endsWith('/targets/target-a') && options?.method==='PATCH')return response({...target,name:'Production',configuration:{base_url:'https://example.com'}});return undefined;});
  render(<MemoryRouter><TargetManager projectId={project.id}/></MemoryRouter>);
  await screen.findByText('Staging WEB',{selector:'strong'});expect(mutations()).toHaveLength(0);
  expect(screen.getByText(/Source-code access, a repository and workspace setup are optional/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'New Target'}));
  fireEvent.change(screen.getByLabelText('Target name'),{target:{value:'Staging'}});
  fireEvent.change(screen.getByLabelText('Base URL'),{target:{value:'https://staging.example.com'}});
  fireEvent.submit(screen.getByRole('form',{name:'Create WEB Target'}));
  await waitFor(()=>expect(body).toEqual({name:'Staging',type:'WEB',environment:'STAGING',configuration:{base_url:'https://staging.example.com'}}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Edit Staging WEB'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Edit Staging WEB'}));
  fireEvent.change(screen.getByLabelText('Base URL'),{target:{value:'https://example.com'}});
  fireEvent.submit(screen.getByRole('form',{name:'Edit WEB Target'}));await waitFor(()=>expect(mutations()).toHaveLength(2));
  expect(vi.mocked(fetch).mock.calls.every(([url])=>String(url).startsWith(`/api/v1/projects/${project.id}/targets`))).toBe(true);
});

it('shows a legacy Campaign honestly and explicitly associates a Target without invoking a Run',async()=>{
  let selected=false;setup((url,options)=>{
    if(url===api+'/target' && options?.method==='PUT'){selected=true;return response({...campaign,target_id:target.id});}
    if(url===api+'/target')return response(selected?target:null);return undefined;
  });open(base);await screen.findByText('Target not configured');
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).endsWith('/target'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Choose Campaign Target'}));
  await screen.findByRole('option',{name:'Staging WEB · STAGING'});
  fireEvent.change(screen.getByRole('combobox',{name:'Target Under Test'}),{target:{value:target.id}});
  fireEvent.submit(screen.getByRole('form',{name:'Campaign Target selection'}));
  await within(await screen.findByRole('region',{name:'Target Under Test'})).findByText('https://staging.example.com');expect(mutations()).toHaveLength(1);
  expect(mutations()[0][1]?.method).toBe('PUT');expect(JSON.parse(mutations()[0][1]?.body as string)).toEqual({target_id:target.id});
  expect(screen.getByText(/Viewing or configuring it never visits the URL/)).toBeInTheDocument();
});

it('renders the Campaign-selected Target using its scoped configuration',async()=>{
  setup(undefined,true);open(base);const region=await screen.findByRole('region',{name:'Target Under Test'});await within(region).findByText('Staging WEB',{selector:'strong'});
  expect(within(region).getByText('STAGING')).toBeInTheDocument();expect(within(region).getByText('Web Application · WEB')).toBeInTheDocument();expect(mutations()).toHaveLength(0);
});

it('keeps historical Run Target display isolated from mutable Project Targets',async()=>{
  const run={executor_kind:'SYNTHETIC',id:'run-a',project_id:project.id,campaign_id:campaign.id,run_number:1,execution_status:'COMPLETED',qa_outcome:'FAIL',target_snapshot:snapshot,created_at:campaign.created_at,started_at:null,completed_at:null,campaign_snapshot:campaign,readiness_at_creation:readiness,requirement_count:1,test_count:2};
  setup(url=>{
    if(url.includes('/runs/run-a/results'))return response({run,summary:{total:2,completed:2,passed:1,failed:1,skipped:0,not_evaluated:0,remaining:0},tests:page([])});
    if(url.includes('/runs/run-a/requirements'))return response(page([]));
    if(url.includes('/targets'))return response(page([{...target,configuration:{base_url:'https://example.com'}}]));return undefined;
  });open(base+'/runs/run-a');await screen.findByText('https://staging.example.com');
  expect(screen.queryByText('https://example.com')).not.toBeInTheDocument();
  expect(screen.getByText('Synthetic execution')).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/targets')||String(url).endsWith('/target'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Refresh Run and results'}));await screen.findByText('https://staging.example.com');
  expect(mutations()).toHaveLength(0);
});

it('keeps legacy Run target absence explicit',async()=>{
  setup(url=>url.includes('/runs/run-a/results')?response({run:{id:'run-a',run_number:1,created_at:campaign.created_at,execution_status:'CREATED',qa_outcome:'NOT_EVALUATED',campaign_snapshot:campaign,readiness_at_creation:readiness,target_snapshot:null,requirement_count:1,test_count:1},summary:{total:1,completed:0,passed:0,failed:0,skipped:0,not_evaluated:1,remaining:1},tests:page([])}):url.includes('/runs/run-a/requirements')?response(page([])):undefined);
  open(base+'/runs/run-a');await screen.findByText('Target information was not captured for this Run.');expect(mutations()).toHaveLength(0);
});

it('does not complete a Target save after unmount',async()=>{
  const pending=deferred<Response>();setup((url,options)=>url.endsWith('/targets')&&options?.method==='POST'?pending.promise:undefined);
  const view=render(<MemoryRouter><TargetManager projectId={project.id}/></MemoryRouter>);
  await screen.findByText('Staging WEB',{selector:'strong'});
  fireEvent.click(screen.getByRole('button',{name:'New Target'}));
  fireEvent.change(screen.getByLabelText('Target name'),{target:{value:'New'}});fireEvent.change(screen.getByLabelText('Base URL'),{target:{value:'http://localhost:3000'}});
  fireEvent.submit(screen.getByRole('form',{name:'Create WEB Target'}));view.unmount();
  await act(async()=>pending.resolve(response(target)));expect(mutations()).toHaveLength(1);
});


it('creates a Campaign with an explicit lazily selected Target and no workspace requirement',async()=>{
  let body:unknown;setup((url,options)=>{
    if(url===`/api/v1/projects/${project.id}/campaigns?limit=50`)return response(page([]));
    if(url===`/api/v1/projects/${project.id}/campaigns` && options?.method==='POST'){body=JSON.parse(options.body as string);return new Promise<Response>(()=>{});}return undefined;
  });open(`/projects/${project.id}`);await screen.findByRole('button',{name:'Choose Target for this workspace'});
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/targets?'))).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Choose Target for this workspace'}));await screen.findByRole('option',{name:'Staging WEB · STAGING'});
  fireEvent.change(screen.getByRole('combobox',{name:'Target Under Test'}),{target:{value:target.id}});
  fireEvent.change(screen.getByLabelText(/Workspace name/),{target:{value:'Black box'}});
  fireEvent.click(screen.getByRole('button',{name:'Create QA workspace'}));
  await waitFor(()=>expect(body).toEqual({name:'Black box',target_id:target.id}));
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/runtime-readiness'))).toBe(false);
});

it('shows safe auth failure and never automatically retries Target creation',async()=>{
  setup((url,options)=>url.endsWith('/targets')&&options?.method==='POST'?response({error:{code:'HOST_AUTH_REQUIRED',message:'Authentication required'}},401):undefined);
  render(<MemoryRouter><TargetManager projectId={project.id}/></MemoryRouter>);await screen.findByText('Staging WEB',{selector:'strong'});
  fireEvent.click(screen.getByRole('button',{name:'New Target'}));
  fireEvent.change(screen.getByLabelText('Target name'),{target:{value:'New'}});fireEvent.change(screen.getByLabelText('Base URL'),{target:{value:'http://localhost:3000'}});
  fireEvent.submit(screen.getByRole('form',{name:'Create WEB Target'}));await screen.findByText('HOST_AUTH_REQUIRED');
  expect(screen.getByRole('button',{name:'Create WEB Target'})).toBeDisabled();expect(mutations()).toHaveLength(1);
});
