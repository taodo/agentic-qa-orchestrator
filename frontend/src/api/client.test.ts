import { describe, it, expect, vi } from 'vitest';
import { ApiError, request } from './client';
import { response } from '../test/fixtures';
import { createTask } from './projects';
describe('typed API boundary', () => {
  it('parses a typed response without retry', async () => {
    const fetch = vi.mocked(globalThis.fetch).mockResolvedValue(response({ name: 'Project' }));
    expect(await request<{ name: string }>('/projects')).toEqual({ name: 'Project' });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/projects');
  });
  it('uses only the approved non-2xx error envelope', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'TASK_NOT_FOUND', message: 'Task not found' }, raw: 'synthetic-secret' }, 404));
    await expect(request('/tasks/missing')).rejects.toMatchObject({ code: 'TASK_NOT_FOUND', message: 'Task not found', status: 404 });
  });
  it.each([200, 500])('handles non-JSON responses safely at status %s', async status => {
    vi.mocked(fetch).mockResolvedValue(new Response('synthetic-sensitive-stack-trace', { status }));
    await expect(request('/projects')).rejects.toMatchObject({ code: 'INVALID_RESPONSE', message: 'QA Sentinel API returned an unreadable response.' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('does not expose an unknown server error body', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ traceback: 'synthetic-secret', detail: 'private-path' }, 500));
    await expect(request('/projects')).rejects.toMatchObject({ code: 'HTTP_ERROR', message: 'QA Sentinel API could not complete the request.' });
  });
  it('maps network errors to a generic message', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('synthetic-sensitive-credential'));
    await expect(request('/projects')).rejects.toEqual(new ApiError('NETWORK_ERROR', 'Unable to reach QA Sentinel API.'));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('does not duplicate Task ownership in the body and encodes IDs', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ id: 'task' }));
    await createTask('project/a', { title: 'Task', requirement: 'Requirement' });
    expect(fetch).toHaveBeenCalledWith('/api/v1/projects/project%2Fa/tasks', expect.objectContaining({ method: 'POST', body: '{"title":"Task","requirement":"Requirement"}' }));
  });
});
