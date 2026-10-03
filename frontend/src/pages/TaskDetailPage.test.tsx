import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { artifact, errorRecord, evidence, invocation, malicious, testRun } from '../test/evidence';
import { deferred, event, page, response, task, reconciliation } from '../test/fixtures';

type EvidenceKey = keyof typeof evidence;
const names: Record<EvidenceKey, string> = { artifacts: 'Artifacts', invocations: 'Invocations', 'test-runs': 'Test Runs', errors: 'Errors', decisions: 'Decisions', gates: 'Gates' };
function RouterTools() {
  const location = useLocation(), navigate = useNavigate();
  return <><output aria-label="Current URL">{location.pathname}{location.search}</output><button onClick={() => void navigate(-1)}>Back</button><button onClick={() => void navigate(1)}>Forward</button><Link to="/tasks/task-b?view=artifacts">Other Task</Link></>;
}
function open(path = '/tasks/task-a') { return render(<MemoryRouter initialEntries={[path]}><RouterTools /><App /></MemoryRouter>); }
function mocks(override?: (url: string, options: RequestInit) => Response | Promise<Response> | undefined) {
  return vi.mocked(fetch).mockImplementation((input, options = {}) => {
    const url = String(input), custom = override?.(url, options);
    if (custom) return Promise.resolve(custom);
    if (url.endsWith('/reconciliation')) return Promise.resolve(response(reconciliation(url.split('/').at(-2))));
    if (url.includes('/executions?')) return Promise.resolve(response(page([])));
    if (url.includes('/timeline?')) return Promise.resolve(response(page([event('z', 'FIRST'), event('a', 'SECOND', 2)])));
    const key = url.split('/').pop()!.split('?')[0] as EvidenceKey;
    if (key in evidence) return Promise.resolve(response(page<unknown>(evidence[key])));
    return Promise.resolve(response(task));
  });
}
const count = (suffix: string) => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes(suffix)).length;
function select(name: string) { fireEvent.click(screen.getByRole('link', { name })); }

describe('Task operator console sections and evidence', () => {
  it('defaults to Overview and reads Task, Timeline and execution history only', async () => {
    mocks(); open(); await screen.findByRole('region', { name: 'Overview' });
    expect(screen.getByRole('link', { name: 'Overview', current: 'page' })).toBeInTheDocument();
    expect(screen.getByText(task.requirement)).toBeVisible(); expect(screen.getByText('Current invocation ID')).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(4); expect(screen.queryByRole('region', { name: 'Artifacts' })).not.toBeInTheDocument();
  });
  it('preserves selected section in URL, browser history and direct loads', async () => {
    mocks(); open('/tasks/task-a?view=artifacts'); await screen.findByText('artifact-z');
    expect(screen.getByRole('link', { name: 'Artifacts', current: 'page' })).toBeInTheDocument();
    select('Invocations'); await screen.findByRole('region', { name: 'Invocations' });
    expect(screen.getByLabelText('Current URL')).toHaveTextContent('?view=invocations');
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    await waitFor(() => expect(screen.getByRole('link', { name: 'Artifacts', current: 'page' })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Forward' }));
    await waitFor(() => expect(screen.getByRole('link', { name: 'Invocations', current: 'page' })).toBeInTheDocument());
    expect(count('/artifacts?')).toBe(1); expect(count('/invocations?')).toBe(1);
  });
  it('falls back to Overview for an invalid view without evidence calls', async () => {
    mocks(); open('/tasks/task-a?view=invalid'); await screen.findByRole('region', { name: 'Overview' });
    expect(screen.getByRole('link', { name: 'Overview', current: 'page' })).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(4);
  });
  it('keeps Timeline API order and approved correlation IDs', async () => {
    mocks(url => url.includes('/timeline?') ? response(page([{ ...event('z', 'FIRST'), correlation: { invocation_id: 'inv-a', artifact_id: 'art-a', test_run_id: 'run-a', decision_id: 'dec-a' } }, event('a', 'SECOND', 2)], true)) : undefined);
    open('/tasks/task-a?view=timeline');
    const rows = within(await screen.findByRole('list', { name: 'Task timeline' })).getAllByRole('listitem');
    expect(rows[0]).toHaveTextContent('FIRST'); expect(rows[1]).toHaveTextContent('SECOND');
    expect(rows[0]).toHaveTextContent('inv-a'); expect(rows[0]).toHaveTextContent('art-a');
    expect(screen.getByText(/Additional records/)).toBeVisible();
  });
  it('shows artifact loading, metadata, bounded preview and explicit JSON expansion', async () => {
    const pending = deferred<Response>(); mocks(url => url.includes('/artifacts?') ? pending.promise : undefined);
    open('/tasks/task-a?view=artifacts'); expect(screen.getByText('Loading Artifacts…')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Refresh Artifacts' })).toBeDisabled();
    await act(async () => pending.resolve(response(page([artifact], true))));
    const region = screen.getByRole('region', { name: 'Artifacts' });
    for (const text of ['PLAN', 'artifact-z', 'PLANNER', 'mock-model', 'invocation-a', '1.0', 'artifact-old']) expect(within(region).getByText(text)).toBeVisible();
    const expand = within(region).getByRole('button', { name: 'Expand JSON' }); expect(expand).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(expand); expect(screen.getByRole('button', { name: 'Collapse JSON' })).toHaveAttribute('aria-expanded', 'true');
    expect(region.querySelector('pre')!.textContent).toBe(JSON.stringify(artifact.content, null, 2));
    expect(region.querySelector('script')).toBeNull(); expect(screen.getByText(/Additional records/)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse JSON' })); expect(region.querySelector('pre')!.textContent!.length).toBeLessThan(350);
  });
  it.each(Object.keys(names) as EvidenceKey[])('%s has its own empty state and explicit isolated refresh', async key => {
    mocks(url => url.includes(`/${key}?`) ? response(page([])) : undefined); open(`/tasks/task-a?view=${key}`);
    expect(await screen.findByText(`No persisted ${names[key].toLowerCase()} yet.`)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: `Refresh ${names[key]}` }));
    await waitFor(() => expect(count(`/${key}?`)).toBe(2)); expect(fetch).toHaveBeenCalledTimes(6);
  });
  it.each(Object.keys(names) as EvidenceKey[])('%s uses public error feedback and operator-only retry', async key => {
    mocks(url => url.includes(`/${key}?`) ? response({ error: { code: 'PERSISTENCE_ERROR', message: 'Persistence operation failed' }, stack: 'secret-body' }, 500) : undefined);
    open(`/tasks/task-a?view=${key}`); expect(await screen.findByText('PERSISTENCE_ERROR')).toBeVisible();
    expect(document.body).not.toHaveTextContent('secret-body'); expect(count(`/${key}?`)).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' })); await waitFor(() => expect(count(`/${key}?`)).toBe(2));
  });
  it('does not expose an unknown error body or log evidence', async () => {
    const log = vi.spyOn(console, 'log');
    mocks(url => url.includes('/artifacts?') ? response({ raw_provider_response: 'synthetic-secret', stack: malicious }, 500) : undefined);
    open('/tasks/task-a?view=artifacts'); expect(await screen.findByText('HTTP_ERROR')).toBeVisible();
    expect(document.body).not.toHaveTextContent('synthetic-secret'); expect(document.body).not.toHaveTextContent(malicious); expect(log).not.toHaveBeenCalled();
  });
  it('renders Invocations model, reasoning, status, times and IDs without private fields', async () => {
    mocks(url => url.includes('/invocations?') ? response(page([{ ...invocation, prompt: 'PRIVATE_PROMPT', input_context_refs: ['PRIVATE_INPUT'], raw_provider_response: 'PRIVATE_PROVIDER', chain_of_thought: 'PRIVATE_REASONING' }])) : undefined);
    open('/tasks/task-a?view=invocations'); const region = await screen.findByRole('region', { name: 'Invocations' }); await within(region).findByText('mock-model');
    for (const text of ['PLANNER', 'COMPLETED', 'high', '2', 'error-a']) expect(within(region).getByText(text)).toBeVisible();
    expect(region).not.toHaveTextContent('PRIVATE_'); expect(within(region).getByTitle(invocation.started_at)).toBeVisible();
  });
  it.each(['PASS', 'FAIL', 'UNKNOWN'] as const)('renders Test Run outcome %s distinctly from execution status', async outcome => {
    mocks(url => url.includes('/test-runs?') ? response(page([{ ...testRun, outcome, execution_status: 'INCOMPLETE', stdout: 'PRIVATE_STDOUT', stderr: 'PRIVATE_STDERR' }])) : undefined);
    open('/tasks/task-a?view=test-runs'); const region = await screen.findByRole('region', { name: 'Test Runs' }); await within(region).findByText(outcome);
    for (const text of [outcome, 'INCOMPLETE', 'unit-test', '5', '0', '1', 'implementation-a', 'report-a']) expect(within(region).getByText(text)).toBeVisible();
    expect(region).not.toHaveTextContent('PRIVATE_');
  });
  it('renders Errors persisted classification, severity, flags, references and safe source', async () => {
    mocks(); open('/tasks/task-a?view=errors'); const region = await screen.findByRole('region', { name: 'Errors' }); await within(region).findByText(malicious);
    for (const text of ['ERROR', 'TEST_TARGET', 'No', 'Yes', 'test-a', 'report-a', 'invocation-a', 'TOOL · pytest']) expect(within(region).getByText(text)).toBeVisible();
    expect(within(region).getAllByText('TEST_FAILURE')).toHaveLength(2); expect(region.querySelector('script')).toBeNull();
  });
  it('renders Decision reasons and Gate checks only as persisted text', async () => {
    mocks(); open('/tasks/task-a?view=decisions'); const decisions = await screen.findByRole('region', { name: 'Decisions' }); await within(decisions).findByText(malicious);
    for (const text of ['BLOCK', 'ORCHESTRATOR', 'PERSISTED_REASON', 'error-a']) expect(within(decisions).getByText(text)).toBeVisible();
    select('Gates'); const gates = await screen.findByRole('region', { name: 'Gates' }); await within(gates).findByText('ReviewGate');
    for (const text of ['BLOCKED', 'PASS', 'FAIL', 'Accepted review', 'Artifact persisted', 'Persisted review required', malicious]) expect(within(gates).getByText(text)).toBeVisible();
    expect(document.querySelector('script')).toBeNull();
  });
  it('refreshes only one previously opened panel and does not re-fetch on section navigation', async () => {
    mocks(); open('/tasks/task-a?view=artifacts'); await screen.findByText('artifact-z'); select('Invocations'); await screen.findByText('mock-model', { selector: 'dd' });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh Invocations' })); await waitFor(() => expect(count('/invocations?')).toBe(2));
    expect(count('/artifacts?')).toBe(1); expect(count('/timeline?')).toBe(1); select('Artifacts'); expect(count('/artifacts?')).toBe(1);
  });
  it('discards old evidence after navigating to another Task', async () => {
    const old = deferred<Response>(); mocks(url => {
      if (url.includes('/task-a/artifacts?')) return old.promise;
      if (url.includes('/task-b/artifacts?')) return response(page([{ ...artifact, id: 'new-artifact', task_id: 'task-b' }]));
      if (url.endsWith('/task-b')) return response({ ...task, id: 'task-b', title: 'Task B' });
    }); open('/tasks/task-a?view=artifacts'); fireEvent.click(screen.getByRole('link', { name: 'Other Task' }));
    await screen.findByText('new-artifact'); await act(async () => old.resolve(response(page([artifact]))));
    expect(screen.getByRole('heading', { name: 'Task B' })).toBeVisible(); expect(screen.queryByText('artifact-z')).not.toBeInTheDocument();
  });
});

describe('Run and Resume evidence refresh', () => {
  it.each(['success', 'safe-stop', 'resume'] as const)('%s refreshes Task/Timeline and all opened evidence only', async mode => {
    const pending = deferred<Response>(); let completed = false;
    mocks((url, options) => {
      if (options.method === 'POST') return pending.promise;
      if (url.endsWith('/task-a')) return response({ ...task, state: mode === 'resume' ? completed ? 'RESEARCHING' : 'BLOCKED' : 'DONE', resume_state: mode === 'resume' && !completed ? 'RESEARCHING' : null });
      if (url.includes('/artifacts?')) return response(page([{ ...artifact, id: completed ? 'refreshed-artifact' : artifact.id }]));
      if (url.includes('/timeline?')) return response(page([event('z', completed ? 'REFRESHED_TIMELINE' : 'INITIAL_TIMELINE')]));
    }); open('/tasks/task-a?view=artifacts'); await screen.findByText('artifact-z'); select('Errors'); await screen.findByText(errorRecord.message);
    const control = screen.getByRole('button', { name: mode === 'resume' ? 'Resume' : 'Run (terminal check)' });
    await waitFor(() => expect(control).toBeEnabled()); fireEvent.click(control); fireEvent.click(control);
    expect(control).toBeDisabled(); expect(screen.getByRole('button', { name: 'Refresh Errors' })).toBeDisabled();
    expect(count(mode === 'resume' ? '/resume' : '/run')).toBe(1);
    completed = true; await act(async () => pending.resolve(mode === 'safe-stop' ? response({ error: { code: 'RUNTIME_STOPPED', message: 'Task execution stopped' } }, 409) : response(task)));
    await waitFor(() => expect(screen.getByRole('button', { name: mode === 'resume' ? 'Run' : 'Run (terminal check)' })).toBeEnabled());
    expect(count('/timeline?')).toBe(2); expect(count('/artifacts?')).toBe(2); expect(count('/errors?')).toBe(2);
    for (const key of ['invocations', 'test-runs', 'decisions', 'gates']) expect(count(`/${key}?`)).toBe(0);
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/task-a'))).toHaveLength(2);
    if (mode === 'resume') expect(count('/run')).toBe(0);
    if (mode === 'safe-stop') expect(screen.getByText('RUNTIME_STOPPED')).toBeVisible();
    select('Artifacts'); expect(screen.getByText('refreshed-artifact')).toBeVisible(); select('Timeline'); expect(screen.getByText('REFRESHED_TIMELINE')).toBeVisible();
  });
  it('does not perform old-route refreshes when a Run resolves after navigation', async () => {
    const pending = deferred<Response>(); mocks((url, options) => options.method === 'POST' ? pending.promise : undefined);
    open('/tasks/task-a'); await screen.findByRole('button', { name: 'Run' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    fireEvent.click(screen.getByRole('link', { name: 'Other Task' })); await screen.findByText('artifact-z');
    const before = vi.mocked(fetch).mock.calls.length; await act(async () => pending.resolve(response(task)));
    expect(fetch).toHaveBeenCalledTimes(before); expect(screen.getByLabelText('Current URL')).toHaveTextContent('/tasks/task-b');
  });
});
