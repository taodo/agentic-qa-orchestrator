import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { initializeAccess, hostedAccess, logout } from './access';
import { request } from './client';
import { AppShell } from '../app/AppShell';
import { response } from '../test/fixtures';

const proof = 'a'.repeat(64);
let assign: ReturnType<typeof vi.fn>;
beforeEach(async () => {
  assign = vi.fn();
  const testWindow = Object.create(window);
  Object.defineProperty(testWindow, 'location', { value: { assign } });
  vi.stubGlobal('window', testWindow);
  vi.mocked(fetch).mockResolvedValueOnce(response({ mode: 'demo' }));
  await initializeAccess();
  vi.mocked(fetch).mockClear();
});

async function hosted() {
  vi.mocked(fetch).mockResolvedValueOnce(response({ mode: 'hosted-demo', csrf: proof,
    operator_username: 'DO_NOT_RENDER_OPERATOR', session_token: 'DO_NOT_RENDER_SESSION' }));
  await initializeAccess(); vi.mocked(fetch).mockClear();
}

describe('hosted access transport', () => {
  it('loads the existing shell with only safe synthetic mode and sign out', async () => {
    await hosted();
    render(<MemoryRouter><AppShell /></MemoryRouter>);
    expect(screen.getByText('HOSTED DEMO · Synthetic')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/DO_NOT_RENDER|a{64}/);
  });
  it.each(['POST', 'PATCH', 'PUT', 'DELETE'])('adds a session-bound proof to %s only in hosted mode', async method => {
    await hosted(); vi.mocked(fetch).mockResolvedValue(response({}));
    await request('/projects', { method });
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/projects', expect.objectContaining({ credentials: 'same-origin', headers: { 'X-QA-Sentinel-CSRF': proof } }));
  });
  it('GET does not carry CSRF proof', async () => {
    await hosted(); vi.mocked(fetch).mockResolvedValue(response({}));
    await request('/projects');
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/projects', expect.objectContaining({ headers: {} }));
  });
  it.each(['demo', 'local', 'preview-demo'])('%s preserves non-session requests and hides logout', async mode => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ mode })); await initializeAccess();
    vi.mocked(fetch).mockResolvedValue(response({})); await request('/projects', { method: 'POST' });
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/projects', expect.objectContaining({ headers: {} }));
    expect(hostedAccess()).toBe(false);
    render(<MemoryRouter><AppShell /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });
  it('supports standalone and Vite fallback', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({}, 404)); await initializeAccess();
    expect(hostedAccess()).toBe(false);
    vi.mocked(fetch).mockResolvedValueOnce(new Response('<html></html>', { headers: { 'Content-Type': 'text/html' } }));
    await initializeAccess(); expect(hostedAccess()).toBe(false);
  });
  it('expired execution POST redirects once and is never replayed', async () => {
    await hosted();
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'HOST_AUTH_REQUIRED', message: 'Hosted access required.' } }, 401));
    await expect(request('/tasks/task-a/executions', { method: 'POST' })).rejects.toMatchObject({ code: 'HOST_AUTH_REQUIRED', message: 'Sign in again to continue.' });
    await expect(request('/tasks/task-a/executions', { method: 'POST' })).rejects.toMatchObject({ code: 'HOST_AUTH_REQUIRED' });
    await expect(request('/projects')).rejects.toMatchObject({ code: 'HOST_AUTH_REQUIRED' });
    expect(fetch).toHaveBeenCalledTimes(1); expect(assign).toHaveBeenCalledExactlyOnceWith('/login');
  });
  it('initial expiry recovers login without loading an authenticated shell', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: { code: 'HOST_AUTH_REQUIRED' } }, 401));
    await expect(initializeAccess()).rejects.toThrow('Hosted access required.');
    expect(assign).toHaveBeenCalledExactlyOnceWith('/login'); expect(hostedAccess()).toBe(false);
  });
  it('rejects malformed hosted proof without granting session mode', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ mode: 'hosted-demo', csrf: 'wrong' }));
    await expect(initializeAccess()).rejects.toThrow('Host access unavailable.');
    expect(hostedAccess()).toBe(false);
  });
  it('logout sends one protected POST and navigates to login', async () => {
    await hosted(); render(<MemoryRouter><AppShell /></MemoryRouter>);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 303 }));
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(assign).toHaveBeenCalledExactlyOnceWith('/login'));
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/auth/logout', expect.objectContaining({ method: 'POST', redirect: 'manual', headers: { 'X-QA-Sentinel-CSRF': proof } }));
    expect(assign).toHaveBeenCalledExactlyOnceWith('/login');
  });
  it('logout failure keeps explicit retry with no automatic POST', async () => {
    await hosted(); vi.mocked(fetch).mockResolvedValueOnce(response({}, 403));
    await expect(logout()).rejects.toThrow('Unable to sign out.');
    expect(fetch).toHaveBeenCalledTimes(1); expect(assign).not.toHaveBeenCalled();
  });
});
