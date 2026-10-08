import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import type { QARun, RunRequirement, RunTest } from '../api/runTypes';
import { campaign, requirement, specification, readiness } from '../test/campaigns';
import { deferred, page, project, response } from '../test/fixtures';
const base = `/projects/${project.id}/campaigns/${campaign.id}`, api = '/api/v1'+base;
const ready = { ...readiness, status: 'READY', blocker_codes: [] };
const run: QARun = {
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
function routes(override?: (url: string, options?: RequestInit) => Response | Promise<Response> | undefined) {
  return vi.mocked(fetch).mockImplementation((input,options) => {
    const url = String(input), result = override?.(url,options);
    if (result) return Promise.resolve(result);
    const fixtures: Record<string, unknown> = { [api]: campaign, [api+'/readiness']: ready, [api+'/runs?limit=50']: page([run]),
      [api+'/runs/run-a']: run, [api+'/runs/run-a/tests?limit=50&after_position=0']: page(tests), [api+'/runs/run-a/requirements?limit=50&after_position=0']: page([req]) };
    if (!(url in fixtures)) return Promise.reject(new Error('Unexpected request: '+url));
    return Promise.resolve(response(fixtures[url]));
  });
}
const posts = () => vi.mocked(fetch).mock.calls.filter(([,options]) => options?.method === 'POST');
describe('Campaign Runs', () => {
  it('adds Runs navigation, bounded listing and synthetic labeling', async () => {
    routes(url => url === api+'/runs?limit=50' ? response(page([run],true)) : undefined); open();
    expect(await screen.findByRole('link',{name:'RUN-001'})).toBeInTheDocument();
    expect(within(screen.getByRole('navigation',{name:'Campaign preparation'})).getByRole('link',{name:'Runs'})).toHaveAttribute('aria-current','page');
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
    expect(await screen.findByText('Frozen Requirement')).toBeInTheDocument(); expect(screen.getByText('Captured Campaign: Frozen Campaign')).toBeInTheDocument();
    fireEvent.click(start); fireEvent.click(start);
    expect(await screen.findByRole('button',{name:'Running synthetic execution…'})).toBeDisabled(); expect(posts()).toHaveLength(1);
    done = true; await act(async () => pending.resolve(response(completed)));
    await waitFor(() => expect(screen.getAllByText('COMPLETED')).toHaveLength(4));
    const rows = screen.getAllByRole('heading',{level:4}).filter(h => h.textContent?.includes('Frozen Test')).map(h => h.closest('article')!);
    expect(rows).toHaveLength(3); expect(rows[1]).toHaveTextContent('FAIL'); expect(rows[2]).toHaveTextContent('PASS');
    expect(rows[2]).toHaveTextContent('Overall expected behavior: Payment accepted'); expect(rows[2]).toHaveTextContent('Observed payment state');
    expect(screen.queryByRole('button',{name:'Start Synthetic Run'})).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument(); expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => String(url));
    expect(urls.some(url => /test-specifications|\/tasks|executions|model-usage/.test(url))).toBe(false);
    expect(urls.filter(url => url === api+'/runs/run-a/tests?limit=50&after_position=0')).toHaveLength(2);
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
    expect(screen.getByText(/Additional records/)).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(5);
    fireEvent.click(next); expect(await screen.findByText('No Test snapshots on this page.')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(6);
  });
  it('discards stale Start completion after navigation to another Run', async () => {
    const pending = deferred<Response>(); const other = {...run,id:'run-b',run_number:2};
    routes((url,options) => {
      if (url.endsWith('/start') && options?.method === 'POST') return pending.promise;
      if (url === api+'/runs/run-b') return response(other);
      if (url.startsWith(api+'/runs/run-b/')) return response(page([]));
    });
    render(<MemoryRouter initialEntries={[base+'/runs/run-a']}><Link to={base+'/runs/run-b'}>Other Run</Link><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button',{name:'Start Synthetic Run'})); fireEvent.click(screen.getByRole('link',{name:'Other Run'}));
    expect(await screen.findByRole('heading',{name:'RUN-002'})).toBeInTheDocument();
    const count = vi.mocked(fetch).mock.calls.length; await act(async () => pending.resolve(response(completed)));
    expect(screen.getByRole('heading',{name:'RUN-002'})).toBeInTheDocument(); expect(screen.queryByText('FAIL',{selector:'.metadata dd'})).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(count); expect(posts()).toHaveLength(1);
  });
});
