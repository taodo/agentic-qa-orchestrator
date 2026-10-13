import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import type { QARun, RunRequirement, RunTest, RunEvidence, RunResults } from '../api/runTypes';
import { campaign, requirement, specification, readiness } from '../test/campaigns';
import { deferred, page, project, response } from '../test/fixtures';
const base = `/projects/${project.id}/campaigns/${campaign.id}`, api = '/api/v1'+base;
const ready = { ...readiness, status: 'READY', blocker_codes: [] };
const run: QARun = {
  executor_kind: 'SYNTHETIC',
  id: 'run-a', project_id: project.id, campaign_id: campaign.id, run_number: 1, idempotency_key: 'intent-a', note: 'Showcase',
  snapshot_hash: 'f'.repeat(64), snapshot_version: 'qa-run-snapshot-v1', requirement_count: 1, test_count: 3,
  campaign_snapshot: { ...campaign, status: 'APPROVED', name: 'Frozen Campaign' }, readiness_at_creation: { ...readiness, status: 'READY', blocker_codes: [] },
  execution_status: 'CREATED', qa_outcome: 'NOT_EVALUATED', created_at: project.created_at, started_at: null, completed_at: null, execution_error_code: null,
};
const approval = { object_id: requirement.id, object_kind: 'REQUIREMENT' as const, project_id: project.id, campaign_id: campaign.id,
  status: 'APPROVED' as const, reviewer_label: 'QA Lead', note: null, content_hash: 'a'.repeat(64), approved_at: project.created_at };
const req: RunRequirement = { id: 'req-snapshot', run_id: run.id, original_requirement_id: requirement.id, position: 1, content: { ...requirement, title: 'Frozen Requirement' }, approval };
const tests: RunTest[] = [1,2,3].map(position => ({ id: 'snapshot-'+position, run_id: run.id, original_test_specification_id: 'test-'+position, position,
  content: { ...specification, title: 'Frozen Test '+position, logical_key: 'TEST-'+position }, approval: { ...approval, object_kind: 'TEST_SPECIFICATION' },
  linked_requirement_snapshot_ids: [req.id], execution_status: 'NOT_STARTED', qa_result: 'NOT_EVALUATED' }));
const completed: QARun = { ...run, execution_status: 'COMPLETED', qa_outcome: 'FAIL', started_at: project.created_at, completed_at: project.updated_at };
const results: RunTest[] = tests.map((t,i) => ({ ...t, execution_status: 'COMPLETED', qa_result: i === 1 ? 'FAIL' : 'PASS' }));
function open(suffix='/runs') { return render(<MemoryRouter initialEntries={[base+suffix]}><App /></MemoryRouter>); }
function evidence(test:RunTest,sequence=1):RunEvidence {return {
  id:`evidence-${test.id}-${sequence}`,project_id:project.id,campaign_id:campaign.id,run_id:test.run_id,run_test_id:test.id,
  presentation:{variant:'synthetic-observation-v1',display_label:'SYNTHETIC',details:[
    {label:'Strategy',value:'synthetic-position-v1'},{label:'Snapshot position',value:String(test.position)},
    {label:'Observed synthetic outcome',value:test.qa_result==='FAIL'?'FAIL':'PASS'}]},
  sequence,recorded_at:project.updated_at,schema_version:'qa-run-evidence-v1',kind:'EXECUTION_OBSERVATION',source:'synthetic',
  summary:`Synthetic fixture position ${test.position}: ${test.qa_result}. No external target was tested.`,
  payload:{variant:'synthetic-observation-v1',strategy:'synthetic-position-v1',position:test.position,outcome:test.qa_result as 'PASS'|'FAIL'|'SKIP'},
};}
function resultPage(saved:QARun,items:RunTest[],truncated=false):RunResults {
  return {run:saved,summary:{total:saved.test_count,completed:items.filter(t=>t.execution_status==='COMPLETED').length,
    passed:items.filter(t=>t.qa_result==='PASS').length,failed:items.filter(t=>t.qa_result==='FAIL').length,
    skipped:items.filter(t=>t.qa_result==='SKIP').length,not_evaluated:items.filter(t=>t.qa_result==='NOT_EVALUATED').length,
    remaining:items.filter(t=>t.execution_status!=='COMPLETED').length},
    tests:page(items.map(t=>({...t,evidence_count:t.execution_status==='COMPLETED'?1:0,
      evidence:page(t.execution_status==='COMPLETED'?[evidence(t)]:[])})),truncated)};
}
function routes(override?: (url: string, options?: RequestInit) => Response | Promise<Response> | undefined) {
  return vi.mocked(fetch).mockImplementation(async (input,options) => {
    const url = String(input), result = override?.(url,options);
    if (result) return Promise.resolve(result);
    if(url.includes('/results?')) {
      const root=url.split('/results?')[0],after=url.split('after_position=')[1];
      const saved=await (override?.(root)??response(run));
      const listed=await (override?.(`${root}/tests?limit=50&after_position=${after}`)??response(page(tests)));
      const body=await listed.json();return response(resultPage(await saved.json(),body.items,body.truncated));
    }
    const fixtures: Record<string, unknown> = { [api]: campaign, [api+'/readiness']: ready, [api+'/runs?limit=50']: page([run]),
      [api+'/runs/run-a']: run, [api+'/runs/run-a/tests?limit=50&after_position=0']: page(tests), [api+'/runs/run-a/requirements?limit=50&after_position=0']: page([req]) };
    if (!(url in fixtures)) return Promise.reject(new Error('Unexpected request: '+url));
    return Promise.resolve(response(fixtures[url]));
  });
}
const posts = () => vi.mocked(fetch).mock.calls.filter(([,options]) => options?.method === 'POST');
describe('Campaign Runs', () => {
  it('preserves legacy Runs listing behind Results navigation, bounded listing and synthetic labeling', async () => {
    routes(url => url === api+'/runs?limit=50' ? response(page([run],true)) : undefined); open();
    expect(await screen.findByRole('link',{name:'RUN-001'})).toBeInTheDocument();
    expect(within(screen.getByRole('navigation',{name:'Campaign preparation'})).getByRole('link',{name:'Results'})).toHaveAttribute('href',base+'/results');
    expect(screen.getByText('No external target is tested in this mode.')).toBeInTheDocument();
    expect(screen.getByText(/Additional records/)).toBeInTheDocument(); expect(screen.getByText('NOT_EVALUATED')).toBeInTheDocument();
    expect(posts()).toHaveLength(0); expect(fetch).toHaveBeenCalledTimes(3);
  });
  it('blocks Create when NOT_READY and links readiness guidance', async () => {
    routes(url => url === api+'/readiness' ? response(readiness) : undefined); open();
    expect(await screen.findByText(/Campaign is NOT_READY/)).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Create QA Run'})).not.toBeInTheDocument();
    expect(screen.getByRole('link',{name:'Inspect Readiness'})).toHaveAttribute('href',base+'/readiness'); expect(posts()).toHaveLength(0);
  });
  it('creates explicitly, prevents pending duplicates and navigates to the snapshot', async () => {
    const pending = deferred<Response>(); routes((url,options) => url === api+'/runs' && options?.method === 'POST' ? pending.promise : undefined); open();
    const create = await screen.findByRole('button',{name:'Create QA Run'});
    fireEvent.change(screen.getByLabelText('Run note (optional)'),{target:{value:'Intent note'}}); fireEvent.click(create); fireEvent.click(create);
    expect(await screen.findByRole('button',{name:'Creating QA Run…'})).toBeDisabled(); expect(posts()).toHaveLength(1);
    const body = JSON.parse(posts()[0][1]!.body as string); expect(body).toMatchObject({note:'Intent note'});
    expect(body.idempotency_key).toMatch(/^[a-z0-9-]{36}$/); expect(body.idempotency_key).not.toBe(run.snapshot_hash);
    await act(async () => pending.resolve(response(run,201)));
    expect(await screen.findByRole('heading',{name:'QA Run detail'})).toBeInTheDocument(); expect(await screen.findByText('3. Frozen Test 3')).toBeInTheDocument();
  });
  it('retains key/note on explicit retry and allocates a fresh key for a new intent', async () => {
    routes((url,options) => url === api+'/runs' && options?.method === 'POST' ? response({error:{code:'PERSISTENCE_ERROR',message:'Persistence operation failed'}},500) : undefined); open();
    const create = await screen.findByRole('button',{name:'Create QA Run'});
    fireEvent.change(screen.getByLabelText('Run note (optional)'),{target:{value:'Keep this note'}}); fireEvent.click(create);
    const retry = await screen.findByRole('button',{name:'Retry Create QA Run'});
    expect(await screen.findByRole('alert')).toHaveTextContent('PERSISTENCE_ERROR'); expect(posts()).toHaveLength(1);
    fireEvent.click(retry); await waitFor(() => expect(posts()).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole('button',{name:'Retry Create QA Run'})).toBeEnabled()); expect(posts()[1][1]!.body).toBe(posts()[0][1]!.body);
    fireEvent.click(screen.getByRole('button',{name:'New create request'})); fireEvent.click(screen.getByRole('button',{name:'Create QA Run'}));
    await waitFor(() => expect(posts()).toHaveLength(3));
    expect(JSON.parse(posts()[2][1]!.body as string).idempotency_key).not.toBe(JSON.parse(posts()[0][1]!.body as string).idempotency_key);
  });
});
describe('immutable Run detail and synthetic Start', () => {
  it('uses snapshot APIs only, starts once and displays later tests after assertion FAIL', async () => {
    const pending = deferred<Response>(); let done = false;
    routes((url,options) => {
      if (url === api+'/runs/run-a/start' && options?.method === 'POST') return pending.promise;
      if (done && url === api+'/runs/run-a') return response(completed);
      if (done && url === api+'/runs/run-a/tests?limit=50&after_position=0') return response(page(results));
    }); open('/runs/run-a'); const start = await screen.findByRole('button',{name:'Start Synthetic Run'});
    expect(screen.getByText(/This Run uses the immutable preparation snapshot/)).toBeInTheDocument();
    expect(await screen.findByText('Frozen Requirement')).toBeInTheDocument(); expect(screen.getByText('Captured workspace: Frozen Campaign')).toBeInTheDocument();
    fireEvent.click(start); fireEvent.click(start);
    expect(await screen.findByRole('button',{name:'Running synthetic execution…'})).toBeDisabled(); expect(posts()).toHaveLength(1);
    done = true; await act(async () => pending.resolve(response(completed)));
    await waitFor(() => expect(screen.getAllByText('COMPLETED')).toHaveLength(4));
    const rows = screen.getAllByRole('heading',{level:4}).filter(h => h.textContent?.includes('Frozen Test')).map(h => h.closest('tr')!);
    expect(rows).toHaveLength(3); expect(rows[1]).toHaveTextContent('FAIL'); expect(rows[2]).toHaveTextContent('PASS');
    expect(rows[2]).toHaveTextContent('Overall expected behavior: Payment accepted'); expect(rows[2]).toHaveTextContent('Observed payment state');
    expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument(); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(urls.some(url => /test-specifications|\/tasks|executions|model-usage/.test(url))).toBe(false);
    expect(urls.filter(url => url === api+'/runs/run-a/results?limit=50&after_position=0')).toHaveLength(2);
  });
  it('shows a safe conflict, refreshes persisted state and never retries Start automatically', async () => {
    let done = false;
    routes((url,options) => {
      if (url.endsWith('/start') && options?.method === 'POST') { done = true; return response({error:{code:'RUN_INVALID_STATE',message:'Invalid Run state'}},409); }
      if (done && url === api+'/runs/run-a') return response(completed);
    }); open('/runs/run-a'); fireEvent.click(await screen.findByRole('button',{name:'Start Synthetic Run'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('RUN_INVALID_STATE');
    expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument(); expect(posts()).toHaveLength(1);
  });
  it('discloses safe infrastructure failure without restart controls', async () => {
    routes(url => url === api+'/runs/run-a' ? response({...completed,execution_status:'FAILED',qa_outcome:'PARTIAL',execution_error_code:'RUN_EXECUTION_FAILED'}) : undefined); open('/runs/run-a');
    expect(await screen.findByRole('alert')).toHaveTextContent('RUN_EXECUTION_FAILED'); expect(screen.getByText('PARTIAL')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument();
  });
  it('keeps snapshot pages bounded with explicit next-page requests', async () => {
    routes(url => url === api+'/runs/run-a/tests?limit=50&after_position=0' ? response(page(tests,true)) : url === api+'/runs/run-a/tests?limit=50&after_position=3' ? response(page([])) : undefined); open('/runs/run-a');
    const next = await screen.findByRole('button',{name:'Next Test snapshot page'});
    expect(screen.getByText(/Additional records/)).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(4);
    fireEvent.click(next); expect(await screen.findByText('No Test snapshots on this page.')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(5);
  });
  it('discards stale Start completion after navigation to another Run', async () => {
    const pending = deferred<Response>(); const other = {...run,id:'run-b',run_number:2};
    routes((url,options) => {
      if (url.endsWith('/start') && options?.method === 'POST') return pending.promise;
      if (url === api+'/runs/run-b') return response(other);
      if (url.startsWith(api+'/runs/run-b/') && !url.includes('/results?')) return response(page([]));
    });
    render(<MemoryRouter initialEntries={[base+'/runs/run-a']}><Link to={base+'/runs/run-b'}>Other Run</Link><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button',{name:'Start Synthetic Run'})); fireEvent.click(screen.getByRole('link',{name:'Other Run'}));
    expect(await screen.findByRole('heading',{name:'RUN-002'})).toBeInTheDocument();
    const count = vi.mocked(fetch).mock.calls.length; await act(async () => pending.resolve(response(completed)));
    expect(screen.getByRole('heading',{name:'RUN-002'})).toBeInTheDocument(); expect(screen.queryByText('FAIL',{selector:'.metadata dd'})).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(count); expect(posts()).toHaveLength(1);
  });
});


describe('Run Results and execution evidence',()=>{
  it('uses global persisted aggregates despite truncated rows, with readable SYNTHETIC evidence',async()=>{
    const data=resultPage({...completed,test_count:8},results.slice(0,1),true);
    data.summary={total:8,completed:8,passed:4,failed:4,skipped:0,not_evaluated:0,remaining:0};
    routes(url=>url.includes('/results?')?response(data):undefined);open('/runs/run-a');
    await screen.findByRole('table');
    const summary=screen.getByRole('heading',{name:'RUN-001'}).closest('section')!;
    expect(summary).toHaveTextContent('Execution statusCOMPLETED');expect(summary).toHaveTextContent('QA outcomeFAIL');
    const metrics=screen.getByLabelText('Run result totals');expect(metrics).toHaveTextContent('Total8');expect(metrics).toHaveTextContent('Passed4');expect(metrics).toHaveTextContent('Failed4');expect(metrics).toHaveTextContent('Remaining0');
    const table=screen.getByRole('table');expect(within(table).getAllByRole('row')).toHaveLength(2);
    const row=within(table).getByRole('heading',{name:'1. Frozen Test 1'}).closest('tr')!,detail=row.querySelector('details')!;
    const reads=vi.mocked(fetch).mock.calls.length;fireEvent.click(within(row).getByRole('rowheader'));expect(detail.open).toBe(true);
    expect(within(row).getByText('SYNTHETIC')).toBeVisible();expect(within(row).getByText('synthetic-position-v1')).toBeVisible();
    expect(within(row).getByText('Synthetic fixture position 1: PASS. No external target was tested.')).toBeVisible();
    fireEvent.click(within(row).getByText('Evidence audit identity'));expect(detail.open).toBe(true);
    row.focus();fireEvent.keyDown(row,{key:' '});expect(detail.open).toBe(false);fireEvent.keyDown(row,{key:'Enter'});expect(detail.open).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(reads);expect(posts()).toHaveLength(0);
    expect(screen.queryByText(/screenshot|HTTP response|DOM observation/)).not.toBeInTheDocument();
  });
  it('distinguishes system failure, earlier QA results and never evaluated tests',async()=>{
    const partial=[results[0],{...tests[1],execution_status:'RUNNING' as const},tests[2]];
    const failed={...completed,execution_status:'FAILED' as const,qa_outcome:'PARTIAL' as const,execution_error_code:'RUN_EXECUTION_FAILED' as const};
    routes(url=>url.includes('/results?')?response(resultPage(failed,partial)):undefined);open('/runs/run-a');
    expect(await screen.findByRole('alert')).toHaveTextContent('execution-system failure');
    const metrics=screen.getByLabelText('Run result totals');expect(metrics).toHaveTextContent('Completed1');expect(metrics).toHaveTextContent('Passed1');expect(metrics).toHaveTextContent('Failed0');expect(metrics).toHaveTextContent('Remaining2');
    const table=screen.getByRole('table');expect(within(table).getAllByText('NOT_EVALUATED')).toHaveLength(2);
    expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it('preserves historical snapshot identity and honestly shows absent evidence',async()=>{
    const data=resultPage(completed,results);data.tests.items=data.tests.items.map(t=>({...t,evidence_count:0,evidence:page([])}));
    routes(url=>url.includes('/results?')?response(data):undefined);open('/runs/run-a');await screen.findByRole('table');
    const row=screen.getByRole('heading',{name:'1. Frozen Test 1'}).closest('tr')!;fireEvent.click(within(row).getByRole('rowheader'));
    expect(within(row).getByText(/Historical completed tests may predate/)).toBeVisible();expect(within(row).getByText('PASS')).toBeVisible();
    expect(vi.mocked(fetch).mock.calls.some(([url])=>(String(url).startsWith(api+'/test-specifications') || String(url).startsWith(api+'/requirements')))).toBe(false);
    expect(posts()).toHaveLength(0);
  });
  it('loads additional bounded evidence only by explicit action and isolates button clicks',async()=>{
    const data=resultPage(completed,results.slice(0,1));const first=data.tests.items[0];first.evidence_count=7;first.evidence=page([evidence(first)],true);
    routes(url=>url.includes('/results?')?response(data):url.endsWith('/tests/snapshot-1/evidence?limit=7')?response(page(Array.from({length:7},(_,i)=>evidence(first,i+1)))):undefined);
    open('/runs/run-a');await screen.findByRole('table');
    // Settle mount effects before the operator interaction, including initial disclosure state.
    await act(async()=>{});
    const row=screen.getByRole('heading',{name:'1. Frozen Test 1'}).closest('tr')!;fireEvent.click(within(row).getByRole('rowheader'));
    await waitFor(()=>expect(within(row).getByText(/Only the bounded evidence preview/)).toBeVisible());const before=vi.mocked(fetch).mock.calls.length;
    fireEvent.click(within(row).getByRole('button',{name:'View bounded test evidence'}));await waitFor(()=>expect(within(row).getAllByText('SYNTHETIC')).toHaveLength(7));
    expect(row.querySelector('details')!.open).toBe(true);expect(fetch).toHaveBeenCalledTimes(before+1);expect(posts()).toHaveLength(0);
  });
});


it('labels sealed browser history truthfully and exposes no synthetic or browser start control',async()=>{
  routes(url=>url===api+'/runs/run-a'?response({...run,executor_kind:'WEB_BROWSER'}):undefined);
  render(<MemoryRouter initialEntries={[base+'/runs/run-a']}><App/></MemoryRouter>);
  expect(await screen.findByText('WEB_BROWSER execution')).toBeInTheDocument();
  expect(screen.queryByText('Synthetic execution')).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true);
});


const runtimeIdentity = {adapter_version:'playwright-chromium-v1',engine:'CHROMIUM' as const,
  playwright_version:'1.63.0',chromium_revision:'1243',browser_version:'153.0.8010.12'};
const capturedTarget = {schema_version:'web-target-snapshot-v1' as const,target_id:'captured-target',project_id:project.id,
  name:'Captured WEB system',type:'WEB' as const,environment:'STAGING' as const,base_url:'https://configured.invalid/'+ 'segment'.repeat(150)};
const browserRun:QARun = {...completed,executor_kind:'WEB_BROWSER',runtime_identity:runtimeIdentity,target_snapshot:capturedTarget,test_count:1,qa_outcome:'PASS'};
const browserTest = {...results[0],browser_plan:{origin:'AI' as const,plan_hash:'b'.repeat(64),plan:{version:'browser-execution-plan-v1'}}};
function browserEvidence(sequence:number,matched=true):RunEvidence {
  return {...evidence(browserTest,sequence),executor_kind:'WEB_BROWSER',source:'web-browser',summary:`Browser step ${sequence}: ${sequence===1?'NAVIGATE':'ASSERT_TEXT'} ${matched?'matched':'mismatched'}.`,
    payload:{variant:'browser-observation-v1',category:sequence===1?'NAVIGATION':'ASSERTION',run_test_id:browserTest.id,plan_hash:'b'.repeat(64),
      step_number:sequence,action:sequence===1?'NAVIGATE':'ASSERT_TEXT',matched,outcome:matched?'PASS':'FAIL',browser_version:runtimeIdentity.browser_version},
    presentation:{variant:'browser-observation-v1',display_label:'WEB_BROWSER',details:[
      {label:'Observed action',value:sequence===1?'NAVIGATE':'ASSERT_TEXT'},{label:'Snapshot step',value:String(sequence)},
      {label:'Matched',value:matched?'True':'False'},{label:'Chromium',value:runtimeIdentity.browser_version}]}};
}
function browserResults(saved:QARun=browserRun,records:RunEvidence[]=[browserEvidence(1),browserEvidence(2)]):RunResults {
  const value=resultPage(saved,[{...browserTest,qa_result:saved.qa_outcome==='FAIL'?'FAIL':saved.qa_outcome==='PASS'?'PASS':'NOT_EVALUATED'}]);
  value.tests.items[0].evidence=page(records);value.tests.items[0].evidence_count=records.length;
  return value;
}
function browserRoutes(value:RunResults) {
  routes(url=>url===api+'/runs/run-a/results?limit=50&after_position=0'?response(value):undefined);
}

describe('stored browser Results presentation',()=>{
  it('renders stored runtime, immutable Target and sealed plan identity without live lookups or execution',async()=>{
    browserRoutes(browserResults());open('/runs/run-a');
    expect(await screen.findByText('Playwright · Chromium')).toBeInTheDocument();
    expect(screen.getByLabelText('Stored executor identity')).toHaveTextContent(runtimeIdentity.adapter_version);
    expect(screen.getByLabelText('Stored executor identity')).toHaveTextContent(runtimeIdentity.playwright_version);
    expect(screen.getByLabelText('Stored executor identity')).toHaveTextContent(runtimeIdentity.chromium_revision);
    expect(screen.getByLabelText('Run Target snapshot')).toHaveTextContent(capturedTarget.name);
    expect(screen.getByText(capturedTarget.base_url)).not.toHaveAttribute('href');
    const row=screen.getByRole('row',{name:/Frozen Test 1/});fireEvent.click(row);
    const plan=within(row).getByLabelText('Sealed browser plan identity');
    expect(plan).toHaveTextContent('AI');expect(plan).toHaveTextContent('browser-execution-plan-v1');
    fireEvent.click(within(plan).getByText('Full plan hash'));expect(within(plan).getByText('b'.repeat(64))).toBeVisible();
    expect(within(row).getByText('Navigation (NAVIGATE)')).toBeVisible();
    expect(within(row).getByText('Text assertion (ASSERT_TEXT)')).toBeVisible();
    expect(within(row).getAllByText('Matched')).not.toHaveLength(0);
    expect(screen.queryByText(/Current executor is SYNTHETIC/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:/Start|Generate|Accept/})).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([url,options])=>String(url).startsWith('/api/v1/projects/')&&(!options?.method||options.method==='GET'))).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([url])=>/targets|browser-plan|sources/.test(String(url)))).toBe(false);
  });
  it('shows mismatch as evidence with authoritative COMPLETED and QA FAIL',async()=>{
    browserRoutes(browserResults({...browserRun,qa_outcome:'FAIL'},[browserEvidence(1),browserEvidence(2,false)]));open('/runs/run-a');
    const identity=await screen.findByLabelText('Stored executor identity');expect(identity).toHaveTextContent('WEB_BROWSER');
    const summary=screen.getByRole('heading',{name:'RUN-001'}).closest('section')!;
    expect(summary).toHaveTextContent('Execution statusCOMPLETED');expect(summary).toHaveTextContent('QA outcomeFAIL');
    fireEvent.click(screen.getByRole('row',{name:/Frozen Test 1/}));expect(screen.getByText('Mismatch')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();expect(posts()).toHaveLength(0);
  });
  it('shows system failure with no invented assertions or completion',async()=>{
    const value=browserResults({...browserRun,execution_status:'FAILED',qa_outcome:'NOT_EVALUATED',execution_error_code:'RUN_EXECUTION_FAILED',browser_error_code:'BROWSER_TARGET_UNREACHABLE'},[]);
    value.tests.items[0].execution_status='RUNNING';value.summary={total:1,completed:0,passed:0,failed:0,skipped:0,not_evaluated:1,remaining:1};
    browserRoutes(value);open('/runs/run-a');
    expect(await screen.findByRole('alert')).toHaveTextContent('BROWSER_TARGET_UNREACHABLE');
    expect(screen.getByRole('alert')).toHaveTextContent('execution-system failure, not a product assertion failure');
    fireEvent.click(screen.getByRole('row',{name:/Frozen Test 1/}));expect(screen.getByText(/No recorded execution evidence/)).toBeVisible();
    expect(screen.queryByText('Mismatch')).not.toBeInTheDocument();expect(screen.queryByText('Text assertion (ASSERT_TEXT)')).not.toBeInTheDocument();
  });
  it('does not infer executor/runtime/plan from a WEB Target or absent fields',async()=>{
    const value=browserResults({...browserRun,executor_kind:undefined,runtime_identity:null});
    value.tests.items[0].browser_plan=null;browserRoutes(value);open('/runs/run-a');
    expect(await screen.findByText('Executor identity unavailable. No executor is inferred from the Target.')).toBeInTheDocument();
    expect(screen.getByLabelText('Stored executor identity')).toHaveTextContent('Unavailable');
    expect(screen.queryByText('Playwright · Chromium')).not.toBeInTheDocument();
    expect(screen.queryByText('Synthetic execution')).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:/Start/})).not.toBeInTheDocument();
  });
  it('shows missing browser runtime and plan honestly without removing stored browser identity',async()=>{
    const value=browserResults({...browserRun,runtime_identity:null});value.tests.items[0].browser_plan=null;
    browserRoutes(value);open('/runs/run-a');expect(await screen.findByLabelText('Stored executor identity')).toHaveTextContent('RuntimeUnavailable');
    fireEvent.click(screen.getByRole('row',{name:/Frozen Test 1/}));expect(screen.getByText(/Browser plan identity unavailable/)).toBeVisible();
  });
  it('retains bounded preview and explicit evidence read, never automatic fan-out',async()=>{
    const value=browserResults();value.tests.items[0].evidence=page([browserEvidence(1)],true);value.tests.items[0].evidence_count=2;
    routes(url=>url===api+'/runs/run-a/results?limit=50&after_position=0'?response(value):url===api+'/runs/run-a/tests/snapshot-1/evidence?limit=2'?response(page([browserEvidence(1),browserEvidence(2)])):undefined);
    open('/runs/run-a');const row=await screen.findByRole('row',{name:/Frozen Test 1/});const before=vi.mocked(fetch).mock.calls.length;
    fireEvent.click(row);expect(fetch).toHaveBeenCalledTimes(before);
    fireEvent.click(within(row).getByRole('button',{name:'View bounded test evidence'}));
    expect(await within(row).findByText('Text assertion (ASSERT_TEXT)')).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(before+1);expect(posts()).toHaveLength(0);
  });
});


it('renders hostile Target strings as text with wrapping classes and no external requests',async()=>{
  const hostile='<img src="https://untrusted.invalid" onerror="alert(1)">';
  browserRoutes(browserResults({...browserRun,target_snapshot:{...capturedTarget,name:hostile}}));
  const view=open('/runs/run-a');expect(await screen.findByText(hostile)).toBeInTheDocument();
  const target=screen.getByLabelText('Run Target snapshot');expect(target.querySelector('.mono')).toHaveTextContent(capturedTarget.base_url);
  expect(view.container.querySelector('img,script,iframe')).toBeNull();
  expect(Array.from(view.container.querySelectorAll('a')).every(a=>!a.href.startsWith('https://configured.invalid'))).toBe(true);
  expect(vi.mocked(fetch).mock.calls.every(([url])=>String(url).startsWith('/api/v1/'))).toBe(true);
});
it('keeps a stored synthetic Run synthetic even when a WEB Target snapshot exists',async()=>{
  routes(url=>url===api+'/runs/run-a/results?limit=50&after_position=0'?response(resultPage({...completed,executor_kind:'SYNTHETIC',target_snapshot:capturedTarget},results)):undefined);
  open('/runs/run-a');expect(await screen.findByText('Synthetic execution')).toBeInTheDocument();
  expect(screen.getByLabelText('Stored executor identity')).toHaveTextContent('SYNTHETIC');
  expect(screen.queryByText('Playwright · Chromium')).not.toBeInTheDocument();
  expect(screen.queryByText('WEB_BROWSER execution')).not.toBeInTheDocument();
});
