import { describe, expect, it, vi } from 'vitest';
import { execution, page, response } from '../test/fixtures';
import { getExecution, getExecutions, requestExecution } from './executions';
import type { ExecutionJobStatus } from './types';

describe('execution transport boundary', () => {
  it.each<ExecutionJobStatus>(['QUEUED', 'RUNNING', 'SUCCEEDED', 'STOPPED', 'FAILED'])('allows only public fields for %s', async status => {
    const job = execution(status);
    vi.mocked(fetch).mockResolvedValue(response({ ...job, sequence: 10, runtime: { secret: 'PRIVATE' }, raw_exception: 'PRIVATE' }));
    expect(await getExecution('task-a', job.id)).toEqual(job);
    expect(fetch).toHaveBeenCalledWith('/api/v1/executions/job-a', expect.anything());
  });
  it('posts once without a client-owned project or arbitrary body', async () => {
    vi.mocked(fetch).mockResolvedValue(response(execution(), 202));
    await requestExecution('task-a');
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith('/api/v1/tasks/task-a/executions', expect.objectContaining({ method: 'POST' }));
    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBeUndefined();
  });
  it('never retries a failed creation', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('PRIVATE'));
    await expect(requestExecution('task-a')).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    { task_id: 'task-b' }, { id: 'job-b' }, { project_id: null }, { status: 'DONE' },
    { created_at: 'bad-date' }, { started_at: '2026-10-02T05:00:01Z' }, { safe_error_code: 'PRIVATE' },
    { finished_at: '2026-10-02T05:00:02Z' }, { started_at: undefined },
  ])('rejects invalid/foreign job fields safely: %j', async changes => {
    vi.mocked(fetch).mockResolvedValue(response({ ...execution(), ...changes }));
    await expect(getExecution('task-a', 'job-a')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it.each([
    { items: [] }, page([execution(), execution()]), page(Array.from({ length: 11 }, (_, n) => execution('QUEUED', { id: `job-${n}` }))),
    { ...page([execution()]), total_returned: 20 }, { ...page([]), truncated: 'yes' }, page([execution('QUEUED', { task_id: 'task-b' })]),
  ])('rejects malformed or unbounded history: %j', async body => {
    vi.mocked(fetch).mockResolvedValue(response(body));
    await expect(getExecutions('task-a')).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('retains history order and honest truncation while dropping unknown page fields', async () => {
    const history = page([execution('STOPPED', { id: 'job-z' }), execution('SUCCEEDED', { id: 'job-a' })], true);
    vi.mocked(fetch).mockResolvedValue(response({ ...history, worker: 'PRIVATE' }));
    expect(await getExecutions('task-a')).toEqual(history);
    expect(fetch).toHaveBeenCalledWith('/api/v1/tasks/task-a/executions?limit=10', expect.anything());
  });
});
