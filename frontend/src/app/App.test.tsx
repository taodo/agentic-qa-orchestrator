import { fireEvent, render, screen, waitFor, within, act } from '@testing-library/react';
import { MemoryRouter, Link } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import { App } from './App';
import { StatusBadge } from '../components/StatusBadge';
import { DateTime, formatDate } from '../components/DateTime';
import type { TaskState } from '../api/types';
import { project, task, page, event, response, deferred } from '../test/fixtures';

function open(path = '/projects') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }
function mockRoutes(handler: (url: string, options: RequestInit) => Promise<Response> | Response) {
  return vi.mocked(fetch).mockImplementation((input, options = {}) => Promise.resolve(handler(String(input), options)));
}
function taskReads(value = task, events = [event('z', 'STATE_TRANSITIONED')]) {
  return mockRoutes(url => url.includes('/timeline?') ? response(page(events)) : response(value));
}

describe('routing and Projects', () => {
  it('redirects home and shows loading before the response', async () => {
    const pending = deferred<Response>(); vi.mocked(fetch).mockReturnValue(pending.promise);
    open('/'); expect(screen.getByText('Loading Projects…')).toBeInTheDocument();
    await act(async () => pending.resolve(response(page([project]))));
    expect(await screen.findByRole('link', { name: project.name })).toHaveAttribute('href', '/projects/project-a');
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('renders Projects, timestamp and honest truncation', async () => {
    vi.mocked(fetch).mockResolvedValue(response(page([project], true))); open();
    expect(await screen.findByText(project.key)).toBeInTheDocument();
    expect(screen.getByTitle(project.updated_at)).toBeInTheDocument();
    expect(screen.getByText(/Additional records are not included/)).toBeInTheDocument();
  });
  it('renders an empty registry', async () => {
    vi.mocked(fetch).mockResolvedValue(response(page([]))); open();
    expect(await screen.findByText(/No Projects yet/)).toBeInTheDocument();
  });
  it('shows a safe error and retries only after a click', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: { code: 'PERSISTENCE_ERROR', message: 'Persistence operation failed' } }, 500)).mockResolvedValue(response(page([project])));
    open(); expect(await screen.findByText('PERSISTENCE_ERROR')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('link', { name: project.name })).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('never renders raw sensitive unknown response bodies', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ stack: 'synthetic-sensitive-body' }, 500)); open();
    expect(await screen.findByText('HTTP_ERROR')).toBeInTheDocument(); expect(document.body).not.toHaveTextContent('synthetic');
  });
  it('creates a Project and refetches server IDs without ownership fields', async () => {
    let created = false;
    const calls = mockRoutes((url, options) => {
      if (options.method === 'POST') { created = true; return response(project, 201); }
      return response(page(created ? [project] : []));
    }); open(); await screen.findByText(/No Projects yet/);
    fireEvent.change(screen.getByLabelText(/Key/), { target: { value: project.key } });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: project.name } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: project.description } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    expect(await screen.findByRole('link', { name: project.name })).toHaveAttribute('href', '/projects/project-a');
    const body = JSON.parse(String(calls.mock.calls.find(([, options]) => options?.method === 'POST')?.[1]?.body));
    expect(body).toEqual({ key: project.key, name: project.name, description: project.description });
  });
  it('keeps Project form values on a server error', async () => {
    mockRoutes((url, options) => options.method === 'POST' ? response({ error: { code: 'PROJECT_KEY_EXISTS', message: 'Project key already exists' } }, 409) : response(page([])));
    open(); await screen.findByText(/No Projects yet/);
    fireEvent.change(screen.getByLabelText(/Key/), { target: { value: 'existing' } });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Existing' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }));
    expect(await screen.findByText('PROJECT_KEY_EXISTS')).toBeInTheDocument(); expect(screen.getByLabelText(/Key/)).toHaveValue('existing');
  });
  it('gives required-field feedback before posting whitespace', async () => {
    vi.mocked(fetch).mockResolvedValue(response(page([]))); open(); await screen.findByText(/No Projects yet/);
    fireEvent.change(screen.getByLabelText(/Key/), { target: { value: ' ' } });
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: ' ' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Create Project' }).closest('form')!);
    expect(await screen.findByText('Key and name are required.')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each(['/unknown', '/projects/a/unknown'])('renders Not Found for %s', path => {
    open(path); expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument(); expect(fetch).not.toHaveBeenCalled();
  });
});

describe('Project Detail and Task creation', () => {
  it('renders only the Project task list returned by its scoped endpoint', async () => {
    const calls = mockRoutes(url => url.includes('/tasks?') ? response(page([task])) : response(project)); open('/projects/project-a');
    expect(await screen.findByRole('heading', { name: project.name })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: task.title })).toHaveAttribute('href', '/tasks/task-a');
    expect(screen.getByText(project.description)).toBeInTheDocument(); expect(document.body).not.toHaveTextContent('Project B');
    expect(calls.mock.calls.map(([url]) => url)).toEqual(expect.arrayContaining(['/api/v1/projects/project-a', '/api/v1/projects/project-a/tasks?limit=50']));
  });
  it('creates a Task under the path owner and refreshes Tasks', async () => {
    let created = false;
    const calls = mockRoutes((url, options) => {
      if (options.method === 'POST') { created = true; return response(task, 201); }
      return url.includes('/tasks?') ? response(page(created ? [task] : [])) : response(project);
    }); open('/projects/project-a'); await screen.findByText('No Tasks in this Project yet.');
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: task.title } });
    fireEvent.change(screen.getByLabelText(/Requirement/), { target: { value: task.requirement } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Task' }));
    expect(await screen.findByRole('link', { name: task.title })).toBeInTheDocument();
    const call = calls.mock.calls.find(([, options]) => options?.method === 'POST')!;
    expect(call[0]).toBe('/api/v1/projects/project-a/tasks'); expect(JSON.parse(String(call[1]?.body))).toEqual({ title: task.title, requirement: task.requirement });
  });
  it('shows missing Project errors without a creation form', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'PROJECT_NOT_FOUND', message: 'Project not found' } }, 404)); open('/projects/missing');
    expect(await screen.findByText('PROJECT_NOT_FOUND')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Create Task' })).not.toBeInTheDocument();
  });
  it('discards stale Project reads after navigation and isolates both task lists', async () => {
    const oldProject = deferred<Response>(), oldTasks = deferred<Response>();
    const b = { ...project, id: 'project-b', name: 'Project B', key: 'b' };
    const tb = { ...task, id: 'task-b', project_id: b.id, title: 'Task B' };
    mockRoutes(url => {
      if (url === '/api/v1/projects/project-a') return oldProject.promise;
      if (url === '/api/v1/projects/project-a/tasks?limit=50') return oldTasks.promise;
      return url.includes('/tasks?') ? response(page([tb])) : response(b);
    });
    render(<MemoryRouter initialEntries={['/projects/project-a']}><Link to="/projects/project-b">Switch Project</Link><App /></MemoryRouter>);
    fireEvent.click(screen.getByRole('link', { name: 'Switch Project' }));
    expect(await screen.findByRole('heading', { name: 'Project B' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Task B' })).toBeInTheDocument();
    await act(async () => { oldProject.resolve(response(project)); oldTasks.resolve(response(page([task]))); });
    expect(screen.getByRole('heading', { name: 'Project B' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: task.title })).not.toBeInTheDocument();
  });
  it('keeps the Task form on server error without changing ownership', async () => {
    mockRoutes((url, options) => options.method === 'POST' ? response({ error: { code: 'INVALID_INPUT', message: 'Invalid application input' } }, 422) : url.includes('/tasks?') ? response(page([])) : response(project));
    open('/projects/project-a'); await screen.findByText('No Tasks in this Project yet.');
    fireEvent.change(screen.getByLabelText(/Title/), { target: { value: task.title } });
    fireEvent.change(screen.getByLabelText(/Requirement/), { target: { value: task.requirement } });
    fireEvent.click(screen.getByRole('button', { name: 'Create Task' }));
    expect(await screen.findByText('INVALID_INPUT')).toBeInTheDocument();
    expect(screen.getByLabelText(/Title/)).toHaveValue(task.title);
  });
});

describe('Task Detail and explicit controls', () => {
  it('renders persisted fields and timeline in API order, never UUID order', async () => {
    taskReads(task, [event('z', 'FIRST_EVENT'), event('a', 'SECOND_EVENT', 2)]); open('/tasks/task-a');
    expect(await screen.findByRole('heading', { name: task.title })).toBeInTheDocument();
    expect(screen.getByText(task.requirement)).toBeInTheDocument(); expect(screen.getByText('Implementation attempts')).toBeInTheDocument();
    expect(screen.getByText('Defect cycles')).toBeInTheDocument(); expect(screen.getByText('Review cycles')).toBeInTheDocument();
    const events = within(await screen.findByRole('list', { name: 'Task timeline' })).getAllByRole('listitem');
    expect(events[0]).toHaveTextContent('FIRST_EVENT'); expect(events[1]).toHaveTextContent('SECOND_EVENT');
    expect(events[0]).toHaveTextContent('ORCHESTRATOR'); expect(events[0]).toHaveTextContent('to_state');
  });
  it('posts Run exactly once, disables both controls while pending, and refreshes Task/timeline', async () => {
    const pending = deferred<Response>(); let done = false;
    const calls = mockRoutes((url, options) => {
      if (options.method === 'POST') return pending.promise;
      if (url.includes('/timeline?')) return response(page([event('z', done ? 'RUN_COMPLETE' : 'READY')]));
      return response({ ...task, state: done ? 'DONE' : 'BLOCKED', resume_state: done ? null : 'RESEARCHING' });
    }); open('/tasks/task-a'); await screen.findByRole('heading', { name: task.title });
    const run = screen.getByRole('button', { name: 'Run' }); fireEvent.click(run); fireEvent.click(run);
    expect(run).toBeDisabled(); expect(screen.getByRole('button', { name: 'Resume' })).toBeDisabled();
    expect(screen.getByText(/waiting for the synchronous API/)).toBeInTheDocument();
    expect(calls.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    expect(calls.mock.calls.find(([, options]) => options?.method === 'POST')?.[0]).toBe('/api/v1/tasks/task-a/run');
    done = true; await act(async () => pending.resolve(response({ ...task, state: 'DONE' })));
    expect(await screen.findByText('RUN_COMPLETE')).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Run (terminal check)' })).toBeEnabled();
    expect(calls.mock.calls.filter(([url]) => String(url).endsWith('/task-a'))).toHaveLength(2);
    expect(calls.mock.calls.filter(([url]) => String(url).includes('/timeline?'))).toHaveLength(2);
  });
  it('shows Run errors safely and still refreshes durable evidence', async () => {
    const calls = mockRoutes((url, options) => options.method === 'POST' ? response({ error: { code: 'RUNTIME_STOPPED', message: 'Task execution stopped; inspect persisted evidence' } }, 409) : url.includes('/timeline?') ? response(page([])) : response(task));
    open('/tasks/task-a'); await screen.findByRole('heading', { name: task.title }); fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByText('RUNTIME_STOPPED')).toBeInTheDocument(); await waitFor(() => expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled());
    expect(calls.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1);
    expect(calls.mock.calls.filter(([url]) => String(url).includes('/timeline?'))).toHaveLength(2);
  });
  it('resumes explicitly without automatically running or changing state optimistically', async () => {
    const pending = deferred<Response>(); let resumed = false;
    const calls = mockRoutes((url, options) => {
      if (options.method === 'POST') return pending.promise;
      return url.includes('/timeline?') ? response(page([])) : response({ ...task, state: resumed ? 'RESEARCHING' : 'BLOCKED', resume_state: resumed ? null : 'RESEARCHING' });
    }); open('/tasks/task-a'); await screen.findByRole('button', { name: 'Resume' }); fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    expect(screen.getByText('BLOCKED')).toBeInTheDocument();
    expect(calls.mock.calls.find(([, options]) => options?.method === 'POST')?.[0]).toBe('/api/v1/tasks/task-a/resume');
    resumed = true; await act(async () => pending.resolve(response({ ...task, state: 'RESEARCHING' })));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Run' })).toBeEnabled();
    expect(calls.mock.calls.filter(([url]) => String(url).endsWith('/run'))).toHaveLength(0);
  });
  it('hides Resume without a persisted target and shows an empty timeline', async () => {
    taskReads({ ...task, state: 'BLOCKED' }, []); open('/tasks/task-a');
    expect(await screen.findByText('No persisted events yet.')).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument();
  });
  it('renders a safe Task not-found state without execution controls', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'TASK_NOT_FOUND', message: 'Task not found' } }, 404));
    open('/tasks/missing'); expect((await screen.findAllByText('TASK_NOT_FOUND')).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Run' })).not.toBeInTheDocument();
  });
});

describe('presentation', () => {
  it.each<TaskState>(['CREATED', 'RESEARCHING', 'PLANNING', 'IMPLEMENTING', 'TESTING', 'ANALYZING', 'INVESTIGATING', 'REVIEWING', 'BLOCKED', 'FAILED', 'DONE'])('labels canonical state %s in text', state => {
    render(<StatusBadge state={state} />); expect(screen.getByText(state)).toBeInTheDocument();
  });
  it('does not crash on an invalid timestamp and retains the original value', () => {
    render(<DateTime value="not-a-timestamp" />); expect(screen.getByTitle('not-a-timestamp')).toHaveTextContent('Invalid timestamp'); expect(formatDate(null)).toBe('—');
  });
});
