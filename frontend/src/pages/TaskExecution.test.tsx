import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { EXECUTION_POLL_MS } from '../app/useTaskExecution';
import { artifact, evidence } from '../test/evidence';
import { deferred, event, execution, page, response, task, reconciliation } from '../test/fixtures';
import type { ExecutionJobView, TaskDetail } from '../api/types';

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); });
const flush = () => act(async () => {});
const tick = (time = EXECUTION_POLL_MS) => act(async () => { await vi.advanceTimersByTimeAsync(time); });
const count = (fragment: string) => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes(fragment)).length;
const posts = () => vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST');
function open(path = '/tasks/task-a') {
  return render(<MemoryRouter initialEntries={[path]}><Link to="/tasks/task-b">Other Task</Link><App /></MemoryRouter>);
}
function backend(initial?: ExecutionJobView, initialTask: TaskDetail = task,
  customize?: (url: string, options: RequestInit) => Response | Promise<Response> | undefined) {
  const server = { job: initial, detail: initialTask };
  vi.mocked(fetch).mockImplementation((input, options = {}) => {
    const url = String(input), custom = customize?.(url, options);
    if (custom) return Promise.resolve(custom);
    if (url.endsWith('/reconciliation')) return Promise.resolve(response(reconciliation(url.split('/').at(-2))));
    if (url.endsWith('/executions') && options.method === 'POST') { server.job = execution(); return Promise.resolve(response(server.job, 202)); }
    if (url.includes('/executions?')) return Promise.resolve(response(page(server.job ? [server.job] : [])));
    if (url.startsWith('/api/v1/executions/')) return Promise.resolve(response(server.job));
    if (url.endsWith('/resume')) { server.detail = { ...server.detail, state: 'RESEARCHING', resume_state: null }; return Promise.resolve(response(server.detail)); }
    if (url.endsWith('/run')) return Promise.resolve(response(server.detail));
    if (url.includes('/timeline?')) return Promise.resolve(response(page([event('event-a', server.job?.status === 'SUCCEEDED' ? 'FINISHED_TIMELINE' : 'INITIAL_TIMELINE')])));
    const key = url.split('/').pop()!.split('?')[0] as keyof typeof evidence;
    if (key in evidence) return Promise.resolve(response(page<unknown>(evidence[key])));
    return Promise.resolve(response(server.detail));
  });
  return server;
}
const jobRegion = () => screen.getByRole('region', { name: 'Execution requests' });
const taskHeading = () => document.querySelector('.task-heading') as HTMLElement;

describe('browser async Run and workflow truth', () => {
  it('creates once via /executions, polls and refreshes only opened evidence; SUCCEEDED cannot invent DONE', async () => {
    const delayedTask = deferred<Response>(); let refreshed = false;
    const server = backend(undefined, task, url => {
      if (url.endsWith('/task-a') && server.job?.status === 'SUCCEEDED') return delayedTask.promise;
      if (url.includes('/artifacts?')) return response(page([{ ...artifact, id: refreshed ? 'fresh-artifact' : 'old-artifact' }]));
    });
    open('/tasks/task-a?view=artifacts'); await flush();
    fireEvent.click(screen.getByRole('link', { name: 'Errors' })); await flush();
    const run = screen.getByRole('button', { name: 'Run' }); expect(run).toBeEnabled(); run.focus(); expect(run).toHaveFocus();
    fireEvent.click(run); fireEvent.click(run); await flush();
    expect(posts()).toHaveLength(1); expect(posts()[0][0]).toBe('/api/v1/tasks/task-a/executions'); expect(count('/run')).toBe(0);
    expect(within(jobRegion()).getByRole('status')).toHaveTextContent('Execution queued'); expect(run).toBeDisabled();
    server.job = execution('RUNNING'); await tick(); expect(within(jobRegion()).getByRole('status')).toHaveTextContent('Execution running');
    refreshed = true; server.job = execution('SUCCEEDED'); await tick();
    expect(jobRegion()).toHaveTextContent('Execution request completed'); expect(within(taskHeading()).getByText('CREATED')).toBeVisible();
    expect(within(taskHeading()).queryByText('DONE')).not.toBeInTheDocument(); expect(jobRegion()).not.toHaveTextContent('Task succeeded');
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled();
    await act(async () => delayedTask.resolve(response({ ...task, state: 'DONE' }))); await flush();
    expect(within(taskHeading()).getByText('DONE')).toBeVisible(); expect(screen.getByRole('button', { name: 'Run (terminal check)' })).toBeEnabled();
    expect(count('/timeline?')).toBe(2); expect(count('/artifacts?')).toBe(2); expect(count('/errors?')).toBe(2);
    for (const key of ['invocations', 'test-runs', 'decisions', 'gates']) expect(count(`/${key}?`)).toBe(0);
    fireEvent.click(screen.getByRole('link', { name: 'Artifacts' })); expect(screen.getByText('fresh-artifact')).toBeVisible();
    fireEvent.click(screen.getByRole('link', { name: 'Timeline' })); expect(screen.getByText('FINISHED_TIMELINE')).toBeVisible();
    const requests = vi.mocked(fetch).mock.calls.length; await tick(10000); expect(fetch).toHaveBeenCalledTimes(requests);
  });
  it('shows SUCCEEDED with a refreshed BLOCKED Task and keeps Resume separate', async () => {
    const blocked: TaskDetail = { ...task, state: 'BLOCKED', resume_state: 'RESEARCHING' };
    const server = backend(execution('RUNNING'), blocked); open(); await flush();
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Resume' })).toBeDisabled();
    server.job = execution('SUCCEEDED'); await tick();
    expect(within(taskHeading()).getByText('BLOCKED')).toBeVisible(); expect(jobRegion()).toHaveTextContent('SUCCEEDED');
    expect(within(taskHeading()).queryByText('DONE')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Resume' })); await flush();
    expect(posts()).toHaveLength(1); expect(posts()[0][0]).toBe('/api/v1/tasks/task-a/resume');
    expect(within(taskHeading()).getByText('RESEARCHING')).toBeVisible();
    expect(count('/api/v1/executions/')).toBe(1); expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled();
  });
  it.each(['STOPPED', 'FAILED'] as const)('%s presents the safe scope and refreshes Task without inferring outcome', async status => {
    const server = backend(execution('RUNNING')); open(); await flush(); server.job = execution(status); await tick();
    const region = jobRegion();
    expect(region).toHaveTextContent(status === 'STOPPED' ? 'Execution stopped safely' : 'Job infrastructure failed');
    expect(region).toHaveTextContent(status === 'STOPPED' ? 'RUNTIME_STOPPED' : 'EXECUTION_FAILED');
    expect(within(taskHeading()).getByText('CREATED')).toBeVisible(); expect(count('/timeline?')).toBe(2);
    const polls = count('/api/v1/executions/'); await tick(10000); expect(count('/api/v1/executions/')).toBe(polls);
  });
  it('recovers an active request on mount and disables repeated Run without POST', async () => {
    backend(execution('QUEUED')); open(); await flush();
    expect(jobRegion()).toHaveTextContent('Execution queued'); fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    await tick(); expect(posts()).toHaveLength(0); expect(count('/api/v1/executions/')).toBe(1);
  });
  it('recovers duplicate backend state and renders fixed guidance after network failure', async () => {
    let active = false;
    backend(undefined, task, (url, options) => {
      if (options.method === 'POST') { active = true; return response({ error: { code: 'TASK_EXECUTION_ALREADY_ACTIVE', message: 'PRIVATE' } }, 409); }
      if (url.includes('/executions?')) return response(page(active ? [execution('RUNNING')] : []));
      if (url.startsWith('/api/v1/executions/')) return Promise.reject(new Error('PRIVATE'));
    });
    open(); await flush(); fireEvent.click(screen.getByRole('button', { name: 'Run' })); await flush();
    expect(jobRegion()).toHaveTextContent('Execution running'); expect(jobRegion()).not.toHaveTextContent('PRIVATE');
    await tick(); expect(jobRegion()).toHaveTextContent('NETWORK_ERROR'); expect(jobRegion()).toHaveTextContent('job-a');
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Refresh execution history' })).toBeEnabled();
    await tick(10000); expect(posts()).toHaveLength(1);
  });
  it.each(['DONE', 'FAILED'] as const)('uses only legacy terminal check for a %s Task', async state => {
    backend(undefined, { ...task, state }); open(); await flush();
    fireEvent.click(screen.getByRole('button', { name: 'Run (terminal check)' })); await flush();
    expect(posts()).toHaveLength(1); expect(posts()[0][0]).toBe('/api/v1/tasks/task-a/run'); expect(count('/api/v1/executions/')).toBe(0);
  });
  it('refreshes stale Task state after backend terminal rejection without enqueueing again', async () => {
    const server = backend(undefined, task, (_url, options) => {
      if (options.method === 'POST') {
        server.detail = { ...task, state: 'DONE' };
        return response({ error: { code: 'TASK_EXECUTION_TERMINAL', message: 'PRIVATE' } }, 409);
      }
    });
    open(); await flush(); fireEvent.click(screen.getByRole('button', { name: 'Run' })); await flush();
    expect(within(taskHeading()).getByText('DONE')).toBeVisible(); expect(jobRegion()).toHaveTextContent('TASK_EXECUTION_TERMINAL');
    expect(jobRegion()).not.toHaveTextContent('PRIVATE'); expect(screen.getByRole('button', { name: 'Run (terminal check)' })).toBeEnabled();
    await tick(10000); expect(posts()).toHaveLength(1);
  });
  it('renders ten recent records in API order with safe fields, native disclosure and truncation', async () => {
    const jobs = Array.from({ length: 10 }, (_, n) => execution('SUCCEEDED', { id: n === 0 ? 'job-z' : `job-${n}` }));
    backend(undefined, task, url => url.includes('/executions?') ? response({ ...page(jobs, true), items: jobs.map(job => ({ ...job, sequence: 88, worker: 'PRIVATE', raw_exception: 'PRIVATE' })) }) : undefined);
    open(); await flush();
    const summary = screen.getByText('Recent executions (10)'); expect(summary.tagName).toBe('SUMMARY');
    expect(jobRegion()).not.toHaveTextContent('PRIVATE'); expect(jobRegion()).toHaveTextContent('Additional records');
    const list = screen.getByRole('list', { name: 'Recent execution requests', hidden: true });
    const rows = within(list).getAllByRole('listitem', { hidden: true }); expect(rows).toHaveLength(10); expect(rows[0]).toHaveTextContent('job-z');
    await tick(10000); expect(count('/api/v1/executions/')).toBe(0);
  });
  it('keeps the synthetic preview notice on the same async Run flow', async () => {
    vi.stubEnv('PUBLIC_QA_SENTINEL_MODE', 'preview-demo'); const server = backend(); open(); await flush();
    expect(screen.getByText('DEMO PREVIEW · Synthetic')).toBeVisible(); fireEvent.click(screen.getByRole('button', { name: 'Run' })); await flush();
    server.job = execution('SUCCEEDED'); server.detail = { ...task, state: 'DONE' }; await tick();
    expect(within(taskHeading()).getByText('DONE')).toBeVisible(); expect(screen.getByText('DEMO PREVIEW · Synthetic')).toBeVisible(); expect(posts()).toHaveLength(1);
  });
  it('does not let delayed Task/job completion update a newly navigated Task', async () => {
    const oldTask = deferred<Response>(), oldJob = deferred<Response>();
    backend(execution('RUNNING'), task, url => {
      if (url.endsWith('/executions/job-a')) return oldJob.promise;
      if (url.endsWith('/task-a')) return oldTask.promise;
      if (url.endsWith('/task-b')) return response({ ...task, id: 'task-b', title: 'Task B' });
      if (url.includes('/task-b/executions?')) return response(page([execution('STOPPED', { id: 'job-b', task_id: 'task-b' })]));
    });
    open(); await flush(); await tick(); fireEvent.click(screen.getByRole('link', { name: 'Other Task' })); await flush();
    await act(async () => { oldJob.resolve(response(execution('SUCCEEDED'))); oldTask.resolve(response({ ...task, state: 'DONE' })); });
    expect(screen.getByRole('heading', { name: 'Task B' })).toBeVisible(); expect(jobRegion()).toHaveTextContent('job-b'); expect(jobRegion()).not.toHaveTextContent('job-a');
    expect(within(taskHeading()).getByText('CREATED')).toBeVisible();
    const countBefore = count('/task-a'); await tick(10000); expect(count('/task-a')).toBe(countBefore);
  });
});
