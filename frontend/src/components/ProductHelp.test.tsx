import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { ProductHelp } from './ProductHelp';
import { App } from '../app/App';
import { page, project, response } from '../test/fixtures';

afterEach(() => vi.unstubAllEnvs());

it('provides a focusable inline help control and explains Project, Campaign, review and readiness without network', () => {
  render(<ProductHelp />);
  const control = screen.getByRole('button', { name: 'How campaigns work' });
  expect(control).toHaveAttribute('aria-expanded', 'false');
  expect(screen.getByText(/One QA initiative/)).not.toBeVisible();
  control.focus();
  expect(control).toHaveFocus();
  expect(control.tagName).toBe('BUTTON'); // Native Enter/Space behavior; no modal/focus trap.
  fireEvent.click(control);
  expect(control).toHaveAttribute('aria-expanded', 'true');
  expect(document.getElementById(control.getAttribute('aria-controls')!)).toBeVisible();
  expect(screen.getByText(/software identity that owns/)).toBeVisible();
  expect(screen.getByText(/One QA initiative/)).toBeVisible();
  expect(screen.getByText(/neither is automatically approved/)).toBeVisible();
  expect(screen.getByText(/Campaign Approved and readiness Ready remain separate/)).toBeVisible();
  expect(screen.getByText(/does not upload a document/)).toBeVisible();
  expect(screen.getByText(/deterministic and synthetic/)).toBeVisible();
  fireEvent.click(control);
  expect(screen.getByText(/One QA initiative/)).not.toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
});

it('keeps the preview notice and Project routing, with no additional request when help opens', async () => {
  vi.stubEnv('PUBLIC_QA_SENTINEL_MODE', 'preview-demo');
  vi.mocked(fetch).mockImplementation(input => Promise.resolve(response(
    String(input).includes('/campaigns?') || String(input).includes('/tasks?') ? page([]) : String(input).includes('/projects?') ? page([project]) : project)));
  render(<MemoryRouter initialEntries={['/projects']}><App /></MemoryRouter>);
  const projectLink = await screen.findByRole('link', { name: project.name });
  expect(screen.getByText('DEMO PREVIEW · Synthetic')).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'How campaigns work' }));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(projectLink).toHaveAttribute('href', '/projects/project-a');
  fireEvent.click(projectLink);
  expect(await screen.findByRole('heading', { name: project.name })).toBeVisible();
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  expect(screen.getByRole('button', { name: 'Create Campaign' })).toBeVisible();
  expect(screen.queryByRole('button', { name: 'Create Task' })).not.toBeInTheDocument();
});
