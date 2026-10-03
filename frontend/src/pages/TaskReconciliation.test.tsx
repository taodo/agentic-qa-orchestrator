import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { getReconciliation, type ReconciliationStatus } from '../api/reconciliation';
import { deferred, page, reconciliation, response, task } from '../test/fixtures';

const evidenceId = '00000000-0000-4000-8000-000000000001';
function assessment(status: ReconciliationStatus = 'CLEAR', taskId = task.id) {
  const unsafe = status === 'MANUAL_ACTION_REQUIRED' || status === 'INCONSISTENT';
  return { ...reconciliation(taskId), status, safe_to_run: !unsafe, safe_to_resume: !unsafe,
    issues: unsafe ? [{ kind: status === 'INCONSISTENT' ? 'EVIDENCE_INCONSISTENT' : 'TEST_EXECUTION_PENDING', severity: 'BLOCKING',
      summary: 'PRIVATE_PATH', operator_action: 'PRIVATE_KEY', raw_exception: 'PRIVATE_EXCEPTION', evidence_refs: [evidenceId] }] : [] };
}
function mock(read: (id: string) => Response | Promise<Response>) {
  vi.mocked(fetch).mockImplementation((input, options = {}) => {
    const url = String(input), id = url.split('/')[4];
    if (url.endsWith('/reconciliation')) return Promise.resolve(read(id));
    if (url.includes('?')) return Promise.resolve(response(page([])));
    if (options.method === 'POST') return Promise.resolve(response(task));
    return Promise.resolve(response({ ...task, id, title: id === 'task-b' ? 'Task B' : task.title, state: 'BLOCKED', resume_state: 'RESEARCHING' }));
  });
}
function open() { return render(<MemoryRouter initialEntries={['/tasks/task-a']}><Link to="/tasks/task-b">Other Task</Link><App /></MemoryRouter>); }
const region = () => screen.getByRole('region', { name: 'Recovery / Reconciliation' });
const posts = () => vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST');

describe('derived recovery guidance', () => {
  it.each(['CLEAR', 'RECOVERABLE', 'MANUAL_ACTION_REQUIRED', 'INCONSISTENT'] as const)('shows %s without changing Task state', async status => {
    mock(id => response(assessment(status, id))); open();
    const label = { CLEAR: 'Clear', RECOVERABLE: 'Recoverable', MANUAL_ACTION_REQUIRED: 'Manual action required', INCONSISTENT: 'Inconsistent' }[status];
    expect(await within(await screen.findByRole('region', { name: 'Recovery / Reconciliation' })).findByText(label)).toBeVisible();
    expect(document.querySelector('.task-heading')).toHaveTextContent('BLOCKED');
    const unsafe = status === 'MANUAL_ACTION_REQUIRED' || status === 'INCONSISTENT';
    await waitFor(() => unsafe ? expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled() : expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Resume' }).hasAttribute('disabled')).toBe(unsafe);
    expect(region()).not.toHaveTextContent('PRIVATE');
    if (unsafe) {
      expect(region()).toHaveTextContent(evidenceId);
      fireEvent.click(screen.getByRole('button', { name: 'Run' })); fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
      expect(posts()).toHaveLength(0);
    }
    expect(screen.queryByRole('button', { name: /Retry anyway|fix/i })).not.toBeInTheDocument();
  });
  it('explicit refresh rereads assessment only, without POST or lazy evidence requests', async () => {
    let current: ReconciliationStatus = 'MANUAL_ACTION_REQUIRED';
    mock(id => response(assessment(current, id))); open(); await screen.findByText('Manual action required');
    const before = vi.mocked(fetch).mock.calls.length;
    current = 'CLEAR'; fireEvent.click(screen.getByRole('button', { name: 'Refresh reconciliation' }));
    await screen.findByText('Clear'); await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    expect(fetch).toHaveBeenCalledTimes(before + 1); expect(posts()).toHaveLength(0);
    for (const key of ['artifacts', 'invocations', 'test-runs', 'errors', 'decisions', 'gates']) expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes(`/${key}?`))).toBe(false);
  });
  it('discards a late Task A assessment after navigation to Task B', async () => {
    const old = deferred<Response>(); mock(id => id === 'task-a' ? old.promise : response(assessment('CLEAR', id)));
    open(); fireEvent.click(screen.getByRole('link', { name: 'Other Task' })); await screen.findByRole('heading', { name: 'Task B' });
    await screen.findByText('Clear'); await act(async () => old.resolve(response(assessment('INCONSISTENT'))));
    expect(region()).toHaveTextContent('Clear'); expect(region()).not.toHaveTextContent('Inconsistent'); expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled();
  });
  it('fails closed on unknown read and shows fixed text without raw backend errors', async () => {
    mock(() => response({ error: { code: 'PRIVATE_ERROR', message: 'PRIVATE_KEY' } }, 500)); open();
    expect(await within(await screen.findByRole('region', { name: 'Recovery / Reconciliation' })).findByRole('alert')).toHaveTextContent('could not be verified');
    expect(region()).not.toHaveTextContent('PRIVATE'); expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled();
  });
  it.each([
    { task_id: 'task-b' }, { status: 'UNKNOWN' }, { safe_to_run: 'true' }, { issues: [{ kind: 'UNKNOWN', severity: 'BLOCKING', evidence_refs: [] }] },
    { status: 'MANUAL_ACTION_REQUIRED', safe_to_run: true }, { issues: [{ kind: 'WORKSPACE_DRIFT', severity: 'BLOCKING', evidence_refs: ['PRIVATE_PATH'] }] },
  ])('rejects malformed or mismatched assessments', async changes => {
    vi.mocked(fetch).mockResolvedValue(response({ ...assessment(), ...changes }));
    await expect(getReconciliation(task.id)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' });
  });
  it('allowlists DTO fields and uses no-store GET without retaining raw summary', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ ...assessment('MANUAL_ACTION_REQUIRED'), workspace_path: 'PRIVATE' }));
    const result = await getReconciliation(task.id);
    expect(JSON.stringify(result)).not.toContain('PRIVATE'); expect(fetch).toHaveBeenCalledWith('/api/v1/tasks/task-a/reconciliation', expect.objectContaining({ cache: 'no-store' }));
  });
  it('refreshes stale clear guidance after the backend rejects continuation, without retrying POST', async () => {
    let unsafe = false;
    vi.mocked(fetch).mockImplementation((input, options = {}) => {
      const url = String(input);
      if (options.method === 'POST') { unsafe = true; return Promise.resolve(response({ error: { code: 'TASK_RECONCILIATION_REQUIRED', message: 'PRIVATE_EXCEPTION' } }, 409)); }
      if (url.endsWith('/reconciliation')) return Promise.resolve(response(assessment(unsafe ? 'MANUAL_ACTION_REQUIRED' : 'CLEAR')));
      if (url.includes('?')) return Promise.resolve(response(page([])));
      return Promise.resolve(response(task));
    });
    open(); await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Run' })); await screen.findByText('Manual action required');
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled(); expect(posts()).toHaveLength(1);
    expect(document.body).not.toHaveTextContent('PRIVATE_EXCEPTION');
    expect(screen.getByText(/Task requires reconciliation/)).toBeVisible();
  });
});
