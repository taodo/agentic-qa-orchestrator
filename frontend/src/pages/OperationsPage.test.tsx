import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation, Link } from 'react-router-dom';
import { App } from '../app/App';
import { OperationsPage } from './OperationsPage';
import { useOperations, OPERATIONS_REFRESH_MS } from '../app/useOperations';
import { getOperations } from '../api/operations';
import { initializeAccess } from '../api/access';
import { snapshot, projectId, taskId } from '../test/operations';
import { response, deferred } from '../test/fixtures';

function routes(data = snapshot) {
  return vi.mocked(fetch).mockImplementation(async input => {
    const url = String(input);
    if (url.startsWith('/host/runtime-status/')) return response({ mode: 'preview-demo', project_id: projectId, runtime_configured: true, model_ready: null, test_targets_configured: false });
    if (url.includes('/operations/summary')) return response(data.summary);
    if (url.includes('/operations/projects')) return response(data.projects);
    if (url.includes('/operations/tasks')) return response(data.tasks);
    if (url.includes('/operations/activity')) return response(data.activity);
    return response({ error: { code: 'TASK_NOT_FOUND', message: 'Task not found' } }, 404);
  });
}
function Location() { const value = useLocation(); return <span data-testid="location">{value.pathname}{value.search}</span>; }
function open(path = '/operations') { return render(<MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter>); }
async function flush() { await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); }); }
beforeEach(async () => {
  vi.mocked(fetch).mockResolvedValueOnce(response({ mode: 'demo' })); await initializeAccess(); vi.mocked(fetch).mockClear();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('Operations dashboard', () => {
  it('routes with primary navigation, summary text and accessible tables', async () => {
    routes(); open();
    expect(await screen.findByRole('table', { name: 'Task states and execution lifecycles' })).toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Operations' })).toHaveAttribute('aria-current', 'page');
    for (const name of ['Projects', 'Tasks', 'Running', 'Queued', 'Blocked', 'Reconciliation attention']) expect(screen.getByLabelText('System summary')).toHaveTextContent(name);
    expect(screen.getByRole('region', { name: 'Task summaries' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('columnheader', { name: 'Task state' })).toHaveAttribute('scope', 'col');
    expect(screen.getByText(/Last updated/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it('keeps Task REVIEWING alongside job SUCCEEDED and uses fixed activity labels', async () => {
    routes(); open(); await screen.findByRole('link', { name: 'Calculator' });
    const table = screen.getByRole('table', { name: 'Task states and execution lifecycles' });
    expect(table).toHaveTextContent('REVIEWING'); expect(table).toHaveTextContent('SUCCEEDED'); expect(table).not.toHaveTextContent('DONE');
    expect(screen.getByRole('link', { name: 'Execution succeeded' })).toHaveAttribute('href', `/tasks/${taskId}`);
    fireEvent.click(screen.getByRole('link', { name: 'Calculator' }));
    expect(await screen.findByRole('link', { name: 'Back to Operations' })).toHaveAttribute('href', '/operations');
    expect(screen.getByTestId('location')).toHaveTextContent(`/tasks/${taskId}`);
  });
  it('shows active attention, safe errors, and bounded collection notices', async () => {
    routes({ ...snapshot, tasks: { ...snapshot.tasks, truncated: true, items: [{ ...snapshot.tasks.items[0],
      active_execution_status: 'RUNNING', attention: 'ACTIVE', reconciliation_attention: true, latest_error_code: 'OUTPUT_SCHEMA_INVALID' }] } });
    open(); await screen.findByRole('link', { name: 'Calculator' });
    expect(screen.getByRole('table', { name: 'Task states and execution lifecycles' })).toHaveTextContent('RUNNING');
    expect(screen.getByText('Output schema invalid')).toBeInTheDocument();
    expect(screen.getByText(/Additional records/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Run|Resume|Retry|Cancel/ })).not.toBeInTheDocument();
  });
  it('handles empty synthetic state clearly', async () => {
    routes({ ...snapshot, projects: { items: [], total_returned: 0, truncated: false }, tasks: { items: [], total_returned: 0, truncated: false }, activity: { items: [], total_returned: 0, truncated: false } });
    open(); expect(await screen.findByText('No Tasks match these filters.')).toBeInTheDocument();
    expect(screen.getByText(/No activity recorded/)).toBeInTheDocument(); expect(screen.getByText('No Projects recorded.')).toBeInTheDocument();
  });
  it('round-trips filters in URL and reads only selected Project readiness', async () => {
    routes(); open(); await screen.findByRole('link', { name: 'Calculator' });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: projectId } });
    await screen.findByText('Runtime: Configured · Synthetic demo');
    fireEvent.change(screen.getByLabelText('Task state'), { target: { value: 'BLOCKED' } });
    fireEvent.click(screen.getByLabelText('Attention only')); fireEvent.click(screen.getByLabelText('Active only'));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('active_only=true'));
    expect(screen.getByTestId('location')).toHaveTextContent(`project_id=${projectId}&task_state=BLOCKED&attention_only=true`);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('active_only=true'), expect.anything()));
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith('/host/runtime-status/'))).toHaveLength(1);
  });
  it.each(['task_state=UNKNOWN', 'project_id=unsafe', 'active_only=1', 'attention_only=true&attention_only=false', 'sort=unsafe'])('rejects invalid filter %s without reads', async query => {
    routes(); open(`/operations?${query}`);
    expect(screen.getByRole('alert')).toHaveTextContent('Invalid Operations filters'); expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' })); await screen.findByRole('link', { name: 'Calculator' });
    expect(screen.getByTestId('location')).toHaveTextContent('/operations');
  });
  it('manual refresh preserves focused control and sends GETs only', async () => {
    routes(); open(); await screen.findByRole('link', { name: 'Calculator' });
    const button = screen.getByRole('button', { name: 'Refresh' }); button.focus(); fireEvent.click(button);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(8)); await flush();
    expect(button).toHaveFocus(); expect(document.querySelector('[aria-live]')).toBeNull();
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
  });
  it.each(['preview-demo', 'hosted-demo'])('%s retains accepted auth transport and synthetic readiness', async mode => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ mode, csrf: 'a'.repeat(64) })); await initializeAccess(); vi.mocked(fetch).mockClear();
    routes(); open(`/operations?project_id=${projectId}`); await screen.findByRole('link', { name: 'Calculator' });
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.credentials === 'same-origin' && !('X-QA-Sentinel-CSRF' in (options.headers ?? {})))).toBe(true);
    if (mode === 'hosted-demo') expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    else expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });
  it('auth expiry follows login recovery once, stops refresh, and never writes', async () => {
    vi.useFakeTimers(); const assign = vi.fn(); const testWindow = Object.create(window);
    Object.defineProperty(testWindow, 'location', { value: { assign } }); vi.stubGlobal('window', testWindow);
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'HOST_AUTH_REQUIRED', message: 'secret raw failure' } }, 401));
    open(); await flush(); expect(assign).toHaveBeenCalledExactlyOnceWith('/login');
    const count = vi.mocked(fetch).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS * 3));
    expect(fetch).toHaveBeenCalledTimes(count); expect(document.body).not.toHaveTextContent('secret raw failure');
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
});

describe('serialized refresh lifecycle', () => {
  it('does not request an initial snapshot while hidden', async () => {
    routes(); vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    renderHook(() => useOperations('', '', true)); await flush(); expect(fetch).not.toHaveBeenCalled();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible'); fireEvent(document, new Event('visibilitychange'));
    await flush(); expect(fetch).toHaveBeenCalledTimes(4);
  });
  it('auto-refreshes every 7s and stops hidden and unmounted', async () => {
    vi.useFakeTimers(); routes(); const view = renderHook(() => useOperations('', '', true)); await flush();
    expect(fetch).toHaveBeenCalledTimes(4);
    await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS)); expect(fetch).toHaveBeenCalledTimes(8);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden'); fireEvent(document, new Event('visibilitychange'));
    await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS * 3)); expect(fetch).toHaveBeenCalledTimes(8);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible'); fireEvent(document, new Event('visibilitychange')); await flush(); expect(fetch).toHaveBeenCalledTimes(12);
    view.unmount(); await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS * 3)); expect(fetch).toHaveBeenCalledTimes(12);
  });
  it('does not overlap after one GET rejects while others are pending', async () => {
    vi.useFakeTimers(); const pending = deferred<Response>();
    vi.mocked(fetch).mockImplementation(input => String(input).includes('/summary') ? Promise.reject(new Error('secret')) : pending.promise);
    const view = renderHook(() => useOperations('', '', true)); await flush();
    act(() => { view.result.current.refresh(); view.result.current.refresh(); });
    await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS * 3)); expect(fetch).toHaveBeenCalledTimes(4);
    view.unmount(); pending.resolve(response({})); await flush(); expect(fetch).toHaveBeenCalledTimes(4);
  });
  it('ignores old-filter completion and serializes a single latest-filter cycle', async () => {
    const pending = deferred<Response>(); vi.mocked(fetch).mockReturnValue(pending.promise);
    const view = renderHook(({ query }) => useOperations(query, '', true), { initialProps: { query: '' } });
    view.rerender({ query: 'task_state=BLOCKED' }); view.rerender({ query: 'task_state=DONE' });
    expect(fetch).toHaveBeenCalledTimes(4); expect(view.result.current.data).toBeUndefined();
    routes(); pending.resolve(response({ secret: 'OLD_FILTER_DATA' })); await flush();
    expect(fetch).toHaveBeenCalledTimes(8);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('task_state=DONE'))).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('task_state=BLOCKED'))).toBe(false);
    expect(view.result.current.data?.tasks.items[0].task_id).toBe(taskId);
  });
  it('does not publish a valid old snapshot into the latest filter', async () => {
    const old = deferred<Response>(), next = deferred<Response>();
    routes(); vi.mocked(fetch).mockImplementationOnce(() => old.promise);
    const view = renderHook(({ query }) => useOperations(query, '', true), { initialProps: { query: '' } });
    await flush(); view.rerender({ query: 'task_state=BLOCKED' });
    vi.mocked(fetch).mockReturnValue(next.promise);
    old.resolve(response(snapshot.summary)); await flush();
    expect(view.result.current.data).toBeUndefined(); expect(view.result.current.error).toBeUndefined();
    view.unmount(); next.resolve(response({})); await flush();
  });
  it('navigation cleans up pending reads without further polling', async () => {
    vi.useFakeTimers(); const pending = deferred<Response>(); vi.mocked(fetch).mockReturnValue(pending.promise);
    render(<MemoryRouter initialEntries={['/operations']}><Link to="/away">Leave dashboard</Link><App /></MemoryRouter>);
    fireEvent.click(screen.getByRole('link', { name: 'Leave dashboard' }));
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
    pending.resolve(response({})); await flush();
    const count = vi.mocked(fetch).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(OPERATIONS_REFRESH_MS * 3)); expect(fetch).toHaveBeenCalledTimes(count);
  });
});

describe('response safety', () => {
  it('drops arbitrary payloads and error text rather than rendering them', async () => {
    routes(); const result = await getOperations('', '');
    expect(result).toEqual(snapshot);
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'UNSAFE', message: 'PRIVATE_EXCEPTION' } }, 500));
    open(); expect(await screen.findByRole('alert')).not.toHaveTextContent('PRIVATE_EXCEPTION');
  });
  it.each(['UNSAFE', '__proto__'])('rejects unknown activity label %s', async kind => {
    routes({ ...snapshot, activity: { ...snapshot.activity, items: [{ ...snapshot.activity.items[0], kind: kind as 'TEST_PASS' }] } });
    await expect(getOperations('', '')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('discards unexpected fields from successful responses', async () => {
    routes({ ...snapshot, activity: { ...snapshot.activity, items: [{ ...snapshot.activity.items[0],
      payload: { secret: 'PRIVATE_BODY' } } as typeof snapshot.activity.items[number]] } });
    expect(JSON.stringify(await getOperations('', ''))).not.toContain('PRIVATE_BODY');
  });
});
