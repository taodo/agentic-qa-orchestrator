import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { EnvironmentNotice } from './EnvironmentNotice';
it('identifies the preview with public static text and no environment dump', () => {
  render(<EnvironmentNotice mode="preview-demo" />);
  expect(screen.getByRole('status')).toHaveTextContent('DEMO PREVIEW · Synthetic');
  expect(screen.getByTitle(/No live AI/)).toBeInTheDocument();
});
it.each(['local', 'demo', 'synthetic-unapproved-value'])('keeps the local label for %s without rendering raw configuration', mode => {
  render(<EnvironmentNotice mode={mode} />);
  expect(screen.getByText('Local operator workspace')).toBeInTheDocument();
  expect(document.body).not.toHaveTextContent(mode === 'local' ? 'synthetic-unapproved-value' : mode);
});
