import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { campaign, readiness } from '../test/campaigns';
import { page, response, project } from '../test/fixtures';
const base=`/projects/${project.id}/campaigns/${campaign.id}`,api='/api/v1'+base;
const target={id:'target-a',project_id:project.id,name:'Production WEB',type:'WEB',environment:'PRODUCTION',configuration:{base_url:'https://example.com'},created_at:campaign.created_at,updated_at:campaign.updated_at};
const run={id:'run-v3',project_id:project.id,campaign_id:campaign.id,run_number:12,test_count:4,execution_status:'COMPLETED',qa_outcome:'FAIL',created_at:campaign.created_at,target_snapshot:{schema_version:'web-target-snapshot-v1',target_id:target.id,project_id:project.id,type:'WEB',name:'Old staging',environment:'STAGING',base_url:'https://staging.example.com'}};
function setup(fail=false,empty=false){vi.mocked(fetch).mockImplementation(async(input)=>{
  const url=String(input);
  if(url===api)return response({...campaign,target_id:empty?null:target.id});
  if(url===api+'/target')return response(target);
  if(url===api+'/readiness')return fail?response({error:{code:'PERSISTENCE_ERROR',message:'Persistence operation failed'}},500):response(readiness);
  if(url===api+'/runs?limit=50')return response(page(empty?[]:[run]));
  return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
const open=()=>render(<MemoryRouter initialEntries={[base]}><App/></MemoryRouter>);
it('shows authoritative Target, counts and snapshot-only recent history with no detail fan-out',async()=>{
  setup();open();await screen.findByText('Old staging');expect(within(screen.getByRole('region',{name:'Target Under Test'})).getByText('Production WEB')).toBeInTheDocument();
  const summary=screen.getByLabelText('Workspace summary');expect(within(summary).getByText('100')).toBeInTheDocument();expect(within(summary).getByText('129')).toBeInTheDocument();
  const rows=screen.getByRole('region',{name:'Recent Runs'});expect(within(rows).getByText('COMPLETED')).toBeInTheDocument();expect(within(rows).getByText('FAIL')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Change Target'})).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).includes('/runs'))).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true);
});
it('does not fabricate readiness counts when unavailable or hide valid Run history',async()=>{
  setup(true);open();await screen.findByText('PERSISTENCE_ERROR');
  await screen.findByText('Old staging');expect(within(screen.getByLabelText('Workspace summary')).getAllByText('Unavailable')).toHaveLength(2);
  expect(screen.queryByText('100')).not.toBeInTheDocument();
});
it('shows honest no-target/no-run states and navigates with adaptive controls',async()=>{
  setup(false,true);open();await screen.findByText('No Runs yet. Nothing has been evaluated.');
  expect(screen.getByText('Target not configured')).toBeInTheDocument();expect(screen.getByText('Not evaluated')).toBeInTheDocument();
  const toggle=screen.getByRole('button',{name:'Navigation'});fireEvent.click(toggle);expect(toggle).toHaveAttribute('aria-expanded','false');
  expect(screen.getByLabelText('Workspace navigation')).toHaveAttribute('data-collapsed','true');
  fireEvent.click(toggle);const nav=screen.getByRole('navigation',{name:'Campaign preparation'});
  expect(within(nav).getByRole('link',{name:'Overview'})).toHaveAttribute('aria-current','page');
  fireEvent.click(within(nav).getByRole('link',{name:'Specification'}));
  await waitFor(()=>expect(within(nav).getByRole('link',{name:'Specification'})).toHaveAttribute('aria-current','page'));
  expect(screen.getByRole('group',{name:'Appearance'})).toBeInTheDocument();
});

it('represents Results as active on a historical Run route without live Target replacement',async()=>{
  setup();vi.mocked(fetch).mockImplementation(async(input)=>{
    const url=String(input);if(url===api)return response(campaign);if(url===api+'/readiness')return response(readiness);
    if(url.includes('/results?'))return response({run:{...run,note:null,requirement_count:1,started_at:null,completed_at:campaign.updated_at,readiness_at_creation:readiness,campaign_snapshot:campaign,snapshot_hash:'a'.repeat(64),snapshot_version:'qa-run-selection-v2'},summary:{total:4,completed:4,passed:3,failed:1,skipped:0,not_evaluated:0,remaining:0},tests:page([])});
    if(url.includes('/requirements?'))return response(page([]));return response({},404);
  });
  render(<MemoryRouter initialEntries={[base+'/runs/'+run.id]}><App/></MemoryRouter>);
  await screen.findByText('Old staging');const nav=screen.getByRole('navigation',{name:'Campaign preparation'});
  expect(within(nav).getByRole('link',{name:'Results'})).toHaveAttribute('aria-current','page');
  expect(screen.getByText('https://staging.example.com')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Export CSV'})).toBeInTheDocument();expect(screen.getByRole('button',{name:'Export XLSX'})).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).endsWith('/target'))).toBe(false);
});

it('keeps the compact Target hero authoritative, inert and explicit',async()=>{
  setup();open();const hero=await screen.findByRole('region',{name:'Target Under Test'});
  await within(hero).findByText('Production WEB');expect(within(hero).getByText('PRODUCTION')).toBeInTheDocument();
  expect(within(hero).getByText('100 requirements · 129 approved tests')).toBeInTheDocument();
  expect(within(hero).getByText('https://example.com')).toBeInTheDocument();
  expect(screen.queryByRole('link',{name:'https://example.com'})).not.toBeInTheDocument();
  expect(screen.getByText('Current executor is SYNTHETIC; no Target URL is visited.')).toBeInTheDocument();
  const sidebar=screen.getByLabelText('Workspace navigation');
  expect(within(sidebar).queryByText(project.id)).not.toBeInTheDocument();
  expect(within(sidebar).getByRole('link',{name:'Project workspaces'})).toHaveAttribute('title','Project ID: '+project.id);
  expect(within(sidebar).queryByText(/LIVE CONFIG/)).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/target'))).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true);
  fireEvent.click(screen.getByText('Target context'));expect(screen.getByText(/Association changes apply to future Runs only/)).toBeVisible();
});

it('uses already-loaded Target context in the right rail and only navigation quick actions',async()=>{
  setup();open();const rail=await screen.findByRole('complementary',{name:'Command center context'});
  await within(rail).findByText('Production WEB');expect(within(rail).getByText('https://example.com')).toBeInTheDocument();
  expect(within(rail).getByText('Configuration only; reachability is not checked.')).toBeInTheDocument();
  const actions=within(rail).getByRole('navigation',{name:'Quick actions'});
  expect(within(actions).getByRole('link',{name:'Execution selection'})).toHaveAttribute('href',base+'/execution');
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).endsWith('/target'))).toHaveLength(1);
  expect(vi.mocked(fetch).mock.calls.filter(([url])=>String(url).includes('/runs'))).toHaveLength(1);
  expect(screen.queryByRole('region',{name:'Persisted result distribution'})).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true);
});
