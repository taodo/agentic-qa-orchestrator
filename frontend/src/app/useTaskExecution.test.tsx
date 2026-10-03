import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { deferred, execution, page, response } from '../test/fixtures';
import { EXECUTION_POLL_MS, useTaskExecution } from './useTaskExecution';
import type { ExecutionJobView } from '../api/types';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
const flush = () => act(async () => {});
const tick = (duration = EXECUTION_POLL_MS) => act(async () => { await vi.advanceTimersByTimeAsync(duration); });
const posts = () => vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST');
const polls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith('/api/v1/executions/'));
function setup(history: ExecutionJobView[] = [], customize?: (url: string, options: RequestInit) => Response | Promise<Response> | undefined) {
  const finished = vi.fn(async () => {});
  vi.mocked(fetch).mockImplementation((input, options = {}) => {
    const url = String(input), custom = customize?.(url, options);
    if (custom) return Promise.resolve(custom);
    if (options.method === 'POST') return Promise.resolve(response(execution(), 202));
    if (url.includes('/executions?')) return Promise.resolve(response(page(history)));
    return Promise.resolve(response(history[0] ?? execution()));
  });
  const hook = renderHook(({ id }) => useTaskExecution(id, finished), { initialProps: { id: 'task-a' } });
  return { ...hook, finished };
}

describe('per-Task durable execution lifecycle', () => {
  it('recovers active history, polls QUEUED -> RUNNING -> SUCCEEDED then stops', async () => {
    let next = execution('QUEUED');
    const hook = setup([next], url => url.startsWith('/api/v1/executions/') ? response(next) : url.includes('/executions?') ? response(page([next])) : undefined);
    await flush(); expect(hook.result.current.active).toBe(true); expect(posts()).toHaveLength(0);
    next = execution('RUNNING'); await tick(); expect(hook.result.current.job?.status).toBe('RUNNING');
    next = execution('SUCCEEDED'); await tick(); expect(hook.result.current.active).toBe(false);
    expect(hook.finished).toHaveBeenCalledTimes(1);
    const count = polls().length; await tick(10000); expect(polls()).toHaveLength(count);
    expect(posts()).toHaveLength(0);
  });
  it.each(['SUCCEEDED', 'STOPPED', 'FAILED'] as const)('does not poll a terminal %s history snapshot', async status => {
    const hook = setup([execution(status)]); await flush(); await tick(10000);
    expect(hook.result.current.job?.status).toBe(status); expect(polls()).toHaveLength(0); expect(hook.finished).not.toHaveBeenCalled();
  });
  it('serializes polls and manual history reads even when a response is slow', async () => {
    const slow = deferred<Response>();
    const hook = setup([execution()], url => url.startsWith('/api/v1/executions/') ? slow.promise : undefined);
    await flush(); await tick(); await tick(10000); await act(async () => { await hook.result.current.refresh(); });
    expect(polls()).toHaveLength(1); expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => slow.resolve(response(execution('RUNNING'))));
    await tick(EXECUTION_POLL_MS - 1); expect(polls()).toHaveLength(1);
    await tick(1); expect(polls()).toHaveLength(2);
  });
  it('guards history vs creation and repeated clicks before React updates', async () => {
    const history = deferred<Response>(), post = deferred<Response>();
    const hook = setup([], (url, options) => options.method === 'POST' ? post.promise : url.includes('/executions?') ? history.promise : undefined);
    await act(async () => { await hook.result.current.create(); }); expect(posts()).toHaveLength(0);
    await act(async () => history.resolve(response(page([]))));
    act(() => { void hook.result.current.create(); void hook.result.current.create(); void hook.result.current.refresh(); });
    expect(posts()).toHaveLength(1); expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () => post.resolve(response(execution(), 202)));
    expect(hook.result.current.job?.id).toBe('job-a'); expect(hook.result.current.active).toBe(true);
    await act(async () => { await hook.result.current.create(); }); expect(posts()).toHaveLength(1);
  });
  it('recovers backend active state on a duplicate POST instead of retrying creation', async () => {
    let history: ExecutionJobView[] = [];
    const hook = setup([], (url, options) => {
      if (options.method === 'POST') { history = [execution('RUNNING')]; return response({ error: { code: 'TASK_EXECUTION_ALREADY_ACTIVE', message: 'PRIVATE' } }, 409); }
      if (url.includes('/executions?')) return response(page(history));
    });
    await flush(); await act(async () => { await hook.result.current.create(); });
    expect(hook.result.current.job?.status).toBe('RUNNING'); expect(hook.result.current.warning).toBeUndefined(); expect(posts()).toHaveLength(1);
  });
  it('preserves identity and warns on a polling interruption, then conservatively retries GET', async () => {
    let fail = true;
    const hook = setup([execution()], url => url.startsWith('/api/v1/executions/') ? fail ? Promise.reject(new Error('PRIVATE')) : response(execution('RUNNING')) : undefined);
    await flush(); await tick();
    expect(hook.result.current.job?.id).toBe('job-a'); expect(hook.result.current.warning?.code).toBe('NETWORK_ERROR');
    expect(hook.result.current.warning?.message).not.toContain('PRIVATE'); expect(posts()).toHaveLength(0);
    fail = false; await tick(); expect(hook.result.current.job?.status).toBe('RUNNING'); expect(hook.result.current.warning).toBeUndefined();
  });
  it('recovers an uncertain POST from history without ever retrying POST', async () => {
    let accepted = false;
    const hook = setup([], (url, options) => {
      if (options.method === 'POST') { accepted = true; return Promise.reject(new Error('PRIVATE')); }
      if (url.includes('/executions?')) return response(page(accepted ? [execution()] : []));
    });
    await flush(); await act(async () => { await hook.result.current.create(); });
    expect(hook.result.current.job?.id).toBe('job-a'); expect(hook.result.current.warning?.code).toBe('NETWORK_ERROR');
    await tick(10000); expect(posts()).toHaveLength(1);
  });
  it('stops a missing job, reads history, and allows explicit recovery', async () => {
    let found = false;
    const hook = setup([execution()], url => url.startsWith('/api/v1/executions/') ? found ? response(execution('RUNNING')) : response({ error: { code: 'EXECUTION_JOB_NOT_FOUND', message: 'PRIVATE' } }, 404) : undefined);
    await flush(); await tick(); expect(hook.result.current.warning?.code).toBe('EXECUTION_JOB_NOT_FOUND');
    const count = polls().length; await tick(10000); expect(polls()).toHaveLength(count); expect(posts()).toHaveLength(0);
    found = true; await act(async () => { await hook.result.current.refresh(); }); await tick();
    expect(hook.result.current.job?.status).toBe('RUNNING'); expect(hook.result.current.warning).toBeUndefined();
  });
  it('ignores Task A polls after switching to Task B and aborts the old read', async () => {
    const old = deferred<Response>(); let signal: AbortSignal | undefined;
    const hook = setup([], (url, options) => {
      if (url.includes('/task-a/executions?')) return response(page([execution()]));
      if (url.includes('/task-b/executions?')) return response(page([execution('RUNNING', { id: 'job-b', task_id: 'task-b' })]));
      if (url.endsWith('/executions/job-a')) { signal = options.signal as AbortSignal; return old.promise; }
    });
    await flush(); await tick(); hook.rerender({ id: 'task-b' }); await flush();
    expect(signal?.aborted).toBe(true);
    await act(async () => old.resolve(response(execution('SUCCEEDED'))));
    expect(hook.result.current.job?.id).toBe('job-b'); expect(hook.finished).not.toHaveBeenCalled();
  });
  it.each(['history', 'POST', 'poll'] as const)('ignores late %s and stops timers after unmount', async kind => {
    const late = deferred<Response>();
    const hook = setup(kind === 'poll' ? [execution()] : [], (url, options) =>
      (kind === 'history' && url.includes('/executions?')) || (kind === 'POST' && options.method === 'POST') ||
      (kind === 'poll' && url.startsWith('/api/v1/executions/')) ? late.promise : undefined);
    await flush();
    if (kind === 'POST') act(() => { void hook.result.current.create(); });
    if (kind === 'poll') await tick();
    hook.unmount(); const count = vi.mocked(fetch).mock.calls.length;
    await act(async () => late.resolve(response(kind === 'history' ? page([execution()]) : execution('SUCCEEDED'))));
    await tick(10000); expect(fetch).toHaveBeenCalledTimes(count); expect(hook.finished).not.toHaveBeenCalled();
  });
  it('cannot let a foreign job response replace the tracked identity', async () => {
    const hook = setup([execution()], url => url.startsWith('/api/v1/executions/') ? response(execution('RUNNING', { id: 'job-b' })) : undefined);
    await flush(); await tick(); expect(hook.result.current.job?.id).toBe('job-a');
    expect(hook.result.current.warning?.code).toBe('INVALID_RESPONSE'); expect(hook.finished).not.toHaveBeenCalled();
  });
  it('requires explicit history recovery after an initial read failure', async () => {
    let fail = true;
    const hook = setup([], url => url.includes('/executions?') && fail ? Promise.reject(new Error('PRIVATE')) : undefined);
    await flush(); await tick(10000); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { await hook.result.current.create(); }); expect(posts()).toHaveLength(0);
    fail = false; await act(async () => { await hook.result.current.refresh(); }); expect(hook.result.current.verified).toBe(true);
  });
  it('holds the creation guard through error recovery and Task refresh', async () => {
    const refreshing = deferred<void>();
    const hook = setup([], (_url, options) => options.method === 'POST' ? response({ error: { code: 'TASK_EXECUTION_TERMINAL', message: 'PRIVATE' } }, 409) : undefined);
    hook.finished.mockImplementation(() => refreshing.promise);
    await flush(); act(() => { void hook.result.current.create(); }); await flush();
    await act(async () => { await hook.result.current.create(); await hook.result.current.refresh(); });
    expect(posts()).toHaveLength(1); expect(fetch).toHaveBeenCalledTimes(3);
    await act(async () => refreshing.resolve());
    expect(hook.result.current.creating).toBe(false);
  });
  it('refreshes Task if manual history recovers a newer terminal job after active work', async () => {
    let newest = execution();
    const hook = setup([], url => url.includes('/executions?') ? response(page([newest])) : undefined);
    await flush(); newest = execution('SUCCEEDED', { id: 'job-new' });
    await act(async () => { await hook.result.current.refresh(); });
    expect(hook.result.current.job?.id).toBe('job-new'); expect(hook.finished).toHaveBeenCalledTimes(1);
    await tick(10000); expect(polls()).toHaveLength(0);
  });
  it('replaces the scheduled old identity when history recovers a different active job', async () => {
    let newest = execution();
    const hook = setup([], url => url.includes('/executions?') ? response(page([newest])) : response(newest));
    await flush(); await tick(EXECUTION_POLL_MS - 1);
    newest = execution('RUNNING', { id: 'job-b' });
    await act(async () => { await hook.result.current.refresh(); }); await tick();
    expect(hook.result.current.job?.id).toBe('job-b'); expect(polls()).toHaveLength(1);
    expect(polls()[0][0]).toBe('/api/v1/executions/job-b'); expect(posts()).toHaveLength(0);
  });
  it('discards Task A history after navigation without overwriting recovered Task B', async () => {
    const old = deferred<Response>();
    const hook = setup([], url => url.includes('/task-a/executions?') ? old.promise :
      url.includes('/task-b/executions?') ? response(page([execution('STOPPED', { id: 'job-b', task_id: 'task-b' })])) : undefined);
    hook.rerender({ id: 'task-b' }); await flush();
    await act(async () => old.resolve(response(page([execution()]))));
    expect(hook.result.current.job?.id).toBe('job-b'); expect(hook.result.current.active).toBe(false);
    await tick(10000); expect(polls()).toHaveLength(0); expect(posts()).toHaveLength(0);
  });
});
