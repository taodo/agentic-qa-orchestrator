import { act, fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import { RuntimeReadiness } from './RuntimeReadiness';
import { App } from '../app/App';
import { getRuntimeStatus } from '../api/host';
import { deferred, page, project, response } from '../test/fixtures';

const configured = { mode: 'local', project_id: project.id, project_key: project.key,
  runtime_configured: true, model_ready: true, test_targets_configured: true };

it('shows configured local readiness, presence-only key and manual snapshot with no polling', async () => {
  vi.mocked(fetch).mockImplementation(() => Promise.resolve(response(configured)));
  render(<RuntimeReadiness projectId={project.id} />);
  expect(await screen.findByText('Runtime: Configured for this host')).toBeVisible();
  expect(screen.getByText('Present (not verified with provider)')).toBeVisible();
  expect(screen.getByText(/trusted local workspace configured outside Project persistence/)).toBeVisible();
  expect(screen.getByText(/not an execution guarantee/)).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith('/host/runtime-status/project-a', expect.any(Object));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh runtime' }));
  await screen.findByText('Runtime: Configured for this host');
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('explains missing local configuration without provisioning or execution', async () => {
  vi.mocked(fetch).mockResolvedValue(response({ ...configured, runtime_configured: false, model_ready: null, test_targets_configured: false }));
  render(<RuntimeReadiness projectId={project.id} />);
  expect(await screen.findByText('Runtime: Not configured for this host')).toBeVisible();
  expect(screen.getByText(/persisted identity but no runtime/)).toHaveTextContent('local init and local validate');
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('shows missing key without claiming provider validation', async () => {
  vi.mocked(fetch).mockResolvedValue(response({ ...configured, model_ready: false }));
  render(<RuntimeReadiness projectId={project.id} />);
  expect(await screen.findByText('Missing')).toBeVisible();
});

it.each(['demo', 'preview-demo'])('identifies configured %s as deterministic synthetic only', async mode => {
  vi.mocked(fetch).mockResolvedValue(response({ ...configured, mode, model_ready: null, test_targets_configured: false }));
  render(<RuntimeReadiness projectId={project.id} />);
  expect(await screen.findByText('Runtime: Configured · Synthetic demo')).toBeVisible();
  expect(screen.getByText(/No live AI, source mutation or real pytest/)).toBeVisible();
  expect(screen.queryByText('Model key')).not.toBeInTheDocument();
});

it('keeps arbitrary preview Projects unconfigured and never derives readiness from identity', async () => {
  vi.mocked(fetch).mockResolvedValue(response({ ...configured, mode: 'preview-demo', runtime_configured: false, model_ready: null, test_targets_configured: false }));
  render(<RuntimeReadiness projectId={project.id} />);
  expect(await screen.findByText('Runtime: Not configured for this host')).toBeVisible();
  expect(screen.getByText(/Only Demo Calculator/)).toBeVisible();
});

it('selects only safe host fields, with no workspace, DB, targets, key or environment dump', async () => {
  vi.mocked(fetch).mockImplementation(() => Promise.resolve(response({ ...configured, workspace_root: 'private-workspace-path',
    database: 'private-database-path', OPENAI_API_KEY: 'synthetic-secret-key', pytest_targets: ['private-tests'],
    project_key: 'private-host-key', environment: { SECRET: 'private-value' } })));
  const safe = await getRuntimeStatus(project.id);
  expect(Object.keys(safe).sort()).toEqual(['mode', 'model_ready', 'project_id', 'runtime_configured', 'test_targets_configured']);
  render(<RuntimeReadiness projectId={project.id} />);
  await screen.findByText('Runtime: Configured for this host');
  for (const hidden of ['private-workspace-path', 'private-database-path', 'synthetic-secret-key', 'private-tests', 'private-host-key', 'private-value']) {
    expect(document.body).not.toHaveTextContent(hidden);
  }
});

it.each([response({ detail: 'private-error-value' }, 500), response({ ...configured, project_id: 'different' }), response({ ...configured, model_ready: 'private-key' })])(
  'handles unavailable/malformed status with fixed guidance, no retries or unsafe bodies', async result => {
    vi.mocked(fetch).mockResolvedValue(result);
    render(<RuntimeReadiness projectId={project.id} />);
    expect(await screen.findByText(/Runtime status unavailable/)).toBeVisible();
    expect(document.body).not.toHaveTextContent('private-error-value');
    expect(document.body).not.toHaveTextContent('private-key');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

it('discards late readiness after Project navigation', async () => {
  const old = deferred<Response>();
  const b = { ...project, id: 'project-b', key: 'b', name: 'Project B' };
  vi.mocked(fetch).mockImplementation(input => {
    const url = String(input);
    if (url === '/host/runtime-status/project-a') return old.promise;
    if (url === '/host/runtime-status/project-b') return Promise.resolve(response({ ...configured, project_id: b.id, runtime_configured: false, model_ready: null, test_targets_configured: false }));
    return Promise.resolve(response((url.includes('/tasks?') || url.includes('/campaigns?')) ? page([]) : url.endsWith('project-a') ? project : b));
  });
  render(<MemoryRouter initialEntries={['/projects/project-a']}><Link to="/projects/project-b">Switch Project</Link><App /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: 'Legacy workflows' }));
  await screen.findByText('Checking this host…');
  fireEvent.click(screen.getByRole('link', { name: 'Switch Project' }));
  await screen.findByRole('heading', { name: 'Project B' });
  fireEvent.click(screen.getByRole('button', { name: 'Legacy workflows' }));
  expect(await screen.findByText('Runtime: Not configured for this host')).toBeVisible();
  await act(async () => old.resolve(response(configured)));
  expect(screen.queryByText('Runtime: Configured for this host')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Project B' })).toBeVisible();
});
