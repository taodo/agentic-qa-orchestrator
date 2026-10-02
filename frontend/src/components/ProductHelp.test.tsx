import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { ProductHelp } from './ProductHelp';
import { App } from '../app/App';
import { page, project, response } from '../test/fixtures';

afterEach(() => vi.unstubAllEnvs());

it('provides a focusable inline help control and explains Project, Task, Run and evidence without network', () => {
  render(<ProductHelp />);
  const control = screen.getByRole('button', { name: 'How QA Sentinel works' });
  expect(control).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByText(/One QA requirement/)).not.toBeVisible();
  control.focus();
  expect(control).toHaveFocus();
  expect(control.tagName).toBe('BUTTON'); // Native Enter/Space behavior; no modal/focus trap.
  fireEvent.click(control);
  expect(control).toHaveAttribute('aria-expanded', 'true');
  expect(document.getElementById(control.getAttribute('aria-controls')!)).toBeVisible();
  expect(screen.getByText(/software identity that owns/)).toBeVisible();
  expect(screen.getByText(/One QA requirement/)).toBeVisible();
  expect(screen.getByText(/Executes the configured workflow/)).toBeVisible();
  expect(screen.getByText(/After Run, inspect Overview/)).toBeVisible();
  expect(screen.getByText('Add division support and reject division by zero.')).toBeVisible();
  expect(screen.getByText(/deterministic and synthetic/)).toBeVisible();
  fireEvent.click(control);
  expect(screen.getByText(/One QA requirement/)).not.toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
});

it('keeps the preview notice and Project routing, with no additional request when help opens', async () => {
  vi.stubEnv('PUBLIC_QA_SENTINEL_MODE', 'preview-demo');
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(response(
    String(input).includes('/tasks?') ? page([]) : String(input).includes('/projects?') ? page([project]) : project)));
  render(<MemoryRouter initialEntries={['/projects']}><App /></MemoryRouter>);
  const projectLink = await screen.findByRole('link', { name: project.name });
  expect(screen.getByText('DEMO PREVIEW · Synthetic')).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'How QA Sentinel works' }));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(projectLink).toHaveAttribute('href', '/projects/project-a');
  fireEvent.click(projectLink);
  expect(await screen.findByRole('heading', { name: project.name })).toBeVisible();
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
  expect(screen.getByRole('button', { name: 'Create Task' })).toBeVisible();
});
