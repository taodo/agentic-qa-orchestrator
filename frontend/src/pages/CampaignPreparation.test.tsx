import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { CampaignStatusBadge } from '../components/CampaignStatusBadge';
import type { ReviewStatus, CoverageStatus, ReadinessStatus } from '../api/campaignTypes';
import { campaign, requirement, blockedRequirement, specification, blockedSpecification, traceability, readiness } from '../test/campaigns';
import { deferred, page, project, response } from '../test/fixtures';
const base = `/projects/${project.id}/campaigns/${campaign.id}`;
const api = '/api/v1'+base;
function open(suffix = '') { return render(<MemoryRouter initialEntries={[base+suffix]}><App /></MemoryRouter>); }
function routes(overrides: Record<string, Response | Promise<Response>> = {}) {
  return vi.mocked(fetch).mockImplementation(input => {
    const url = String(input);
    if (overrides[url]) return Promise.resolve(overrides[url]);
    const fixtures: Record<string, unknown> = { [api]: campaign, [api+'/readiness']: readiness,
      [api+'/sources?limit=50']: page([]), [api+'/requirements?limit=50']: page([requirement, blockedRequirement]), [api+'/traceability?limit=50']: traceability,
      [api+'/test-specifications?limit=50']: page([specification, blockedSpecification]),
      ['/api/v1/projects/'+project.id]: project, ['/api/v1/projects/'+project.id+'/campaigns?limit=50']: page([campaign]) };
    if (!(url in fixtures)) return Promise.reject(new Error('Unexpected mocked request: '+url));
    return Promise.resolve(response(fixtures[url]));
  });
}

describe('Campaign routes and readiness', () => {
  it.each([['', 'Overview'], ['/requirements', 'Requirements'], ['/test-specifications', 'Test Specifications'], ['/traceability', 'Traceability'], ['/readiness', 'Readiness assessment']])('loads deep link %s with preparation navigation', async (suffix, heading) => {
    routes(); open(suffix);
    expect(await screen.findByRole('heading', { name: heading, level: 2 })).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Campaign preparation' });
    expect(within(nav).getAllByRole('link')).toHaveLength(6);
    expect(within(nav).getByRole('link', { name: suffix === '/readiness' ? 'Readiness' : heading })).toHaveAttribute('aria-current', 'page');
    expect(screen.queryByRole('button', { name: /Run|Mark Ready|Resolve|Execute/i })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true);
  });
  it('separates preparation Approved from Not ready and uses full aggregates', async () => {
    routes(); open(); await screen.findByText('Not ready');
    expect(screen.getByText('Approved', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText('One or more Requirements need clarification.')).toBeInTheDocument();
    const counts = screen.getByRole('heading', { name: 'Preparation summary' }).closest('section')!;
    expect(counts).toHaveTextContent('Requirements100'); expect(counts).toHaveTextContent('Test Specifications130');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('shows Ready as preparation without claiming execution results', async () => {
    routes({ [api+'/readiness']: response({ ...readiness, status: 'READY', blocker_codes: [] }) }); open('/readiness');
    expect(await screen.findByText('Ready', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText(/Ready describes preparation, not a test result/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Mark Ready|Run/i })).not.toBeInTheDocument();
  });
  it.each(['CAMPAIGN_NOT_APPROVED', 'NO_REQUIREMENTS', 'REQUIREMENTS_NOT_APPROVED', 'REQUIREMENTS_NEED_CLARIFICATION', 'NO_TEST_SPECIFICATIONS', 'REQUIREMENT_COVERAGE_GAP', 'INVALID_REQUIREMENT_APPROVAL', 'INVALID_TEST_APPROVAL'])('maps blocker %s to human copy and retained diagnostics', async code => {
    routes({ [api+'/readiness']: response({ ...readiness, blocker_codes: [code] }) }); open('/readiness');
    const section = (await screen.findByRole('heading', { name: 'Readiness blockers' })).closest('section')!;
    expect(within(section).getByRole('link', { name: /Inspect/ })).toHaveAttribute('href');
    expect(within(section).getByText(code)).toBeInTheDocument();
    expect(section.querySelector('li p')?.textContent).not.toBe(code);
  });
  it('handles empty readiness through meaningful blockers', async () => {
    routes({ [api+'/readiness']: response({ ...readiness, total_requirements: 0, total_test_specifications: 0, approved_requirements: 0, approved_test_specifications: 0, blocker_codes: ['NO_REQUIREMENTS', 'NO_TEST_SPECIFICATIONS'] }) }); open('/readiness');
    expect(await screen.findByText('No Requirements have been prepared. Add a specification and extract Requirements.')).toBeInTheDocument();
    expect(screen.getByText('No Test Specifications have been prepared. Import existing tests or generate tests.')).toBeInTheDocument();
  });
  it('handles Campaign not found without child calls or action controls', async () => {
    routes({ [api]: response({ error: { code: 'CAMPAIGN_NOT_FOUND', message: 'Campaign not found' } }, 404) }); open('/requirements');
    expect(await screen.findByRole('heading', { name: 'Campaign not found' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('CAMPAIGN_NOT_FOUND');
    expect(fetch).toHaveBeenCalledTimes(1); expect(screen.queryByRole('navigation', { name: 'Campaign preparation' })).not.toBeInTheDocument();
  });
  it('shows initial Campaign loading before preparing a child', async () => {
    const pending = deferred<Response>(); routes({ [api]: pending.promise }); open('/readiness');
    expect(screen.getByText('Loading Campaign…')).toBeInTheDocument(); expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => pending.resolve(response(campaign)));
    expect(await screen.findByText('Not ready')).toBeInTheDocument();
  });
});

describe('Requirements and executor-neutral Test Specifications', () => {
  it('renders requirement markers, criteria, citations and coverage', async () => {
    routes(); open('/requirements'); await screen.findByText(requirement.title);
    expect(screen.getByText('REQ-PAY')).toBeInTheDocument(); expect(screen.getByText('Clarify the supported currency.')).toBeInTheDocument();
    expect(screen.getByText('Needs clarification', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getAllByText('1 acceptance criteria · 1 source references')).toHaveLength(2);
    fireEvent.click(screen.getAllByText('Source evidence (1)')[0]);
    expect(screen.getAllByText(/lines 2–4/)).toHaveLength(2); expect(screen.getByText('Covered', { selector: '.badge' })).toBeInTheDocument();
  });
  it('does not turn missing bounded coverage rows into Not covered', async () => {
    routes({ [api+'/traceability?limit=50']: response({ ...traceability, requirements: page([], true) }) }); open('/requirements');
    expect(await screen.findAllByText(/Not included in the current traceability response/)).toHaveLength(2);
    expect(screen.queryByText('Not covered')).not.toBeInTheDocument(); expect(screen.getByText(/missing rows are unknown/)).toBeInTheDocument();
  });
  it('keeps requirement evidence visible when optional coverage fails safely', async () => {
    routes({ [api+'/traceability?limit=50']: response({ error: { code: 'PERSISTENCE_ERROR', message: 'Persistence operation failed' } }, 500) }); open('/requirements');
    expect(await screen.findByText(requirement.title)).toBeInTheDocument(); expect(await screen.findByText(/Coverage is unavailable/)).toBeInTheDocument();
  });
  it('shows both origins under the same review semantics and explains unresolved tests', async () => {
    const ai = { ...specification, id: 'test-ai', logical_key: 'TEST-AI', provenance: { ...specification.provenance, origin: 'AI_GENERATED', contract_version: 'test-specs-v1', start_line: null, end_line: null } };
    routes({ [api+'/test-specifications?limit=50']: response(page([specification, ai, blockedSpecification], true)) }); open('/test-specifications');
    expect(await screen.findAllByText('Imported')).toHaveLength(2); expect(screen.getByText('AI-generated')).toBeInTheDocument();
    expect(screen.getByText('No known Requirement links.')).toBeInTheDocument(); expect(screen.getByText(/UNKNOWN-CURRENCY/)).toBeInTheDocument();
    expect(screen.getByText('Missing')).toBeInTheDocument(); expect(screen.getByText(/Additional records/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Execute|Resolve/ })).not.toBeInTheDocument();
  });
  it('renders untrusted source/marker text without executing HTML or following links', async () => {
    const text = '<img src="https://invalid.example" onerror="bad()">';
    routes({ [api+'/requirements?limit=50']: response(page([{ ...blockedRequirement, information_markers: [{ kind: 'AMBIGUITY', description: text }] }])) }); open('/requirements');
    expect(await screen.findByText(text)).toBeInTheDocument(); expect(document.querySelector('img')).toBeNull();
    expect(vi.mocked(fetch).mock.calls.every(([url]) => String(url).startsWith('/api/v1/projects/'))).toBe(true);
  });
});

describe('Traceability and selected detail reads', () => {
  it.each([500, 404])('keeps authoritative coverage when optional Requirement names fail (%s)', async status => {
    routes({
      [api+'/requirements?limit=50']: response({ stack: 'PRIVATE_AUXILIARY_ERROR', message: 'PRIVATE_AUXILIARY_ERROR' }, status),
      [api+'/traceability?limit=50']: response({ ...traceability, requirements: page(traceability.requirements.items, true), links: page(traceability.links.items, true) }),
    });
    open('/traceability');
    expect(await screen.findByText(/Requirement names are unavailable/)).toBeInTheDocument();
    const table = await screen.findByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    traceability.requirements.items.forEach(row => {
      const link = within(table).getByRole('link', { name: row.requirement_id });
      const cells = within(link.closest('tr')!).getAllByRole('cell');
      expect(cells[0]).toHaveTextContent(row.review_status === 'APPROVED' ? 'Approved' : 'Needs clarification');
      expect(cells[1]).toHaveTextContent(row.linked_test_count === 0 ? '0 — coverage gap' : String(row.linked_test_count));
      expect(cells[2]).toHaveTextContent(String(row.approved_test_count));
    });
    for (const label of ['Covered', 'Partial', 'Not covered']) expect(within(table).getByText(label, { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText(/not a complete matrix/)).toBeInTheDocument();
    expect(screen.getByText(/additional links are not shown/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PRIVATE_AUXILIARY_ERROR');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.map(([url]) => String(url)).sort()).toEqual([api, api+'/readiness', api+'/traceability?limit=50', api+'/requirements?limit=50'].sort());
  });
  it('renders coverage before optional names finish and decorates without detail fan-out', async () => {
    const pending = deferred<Response>();
    routes({ [api+'/requirements?limit=50']: pending.promise }); open('/traceability');
    const fallback = await screen.findByRole('link', { name: requirement.id });
    expect(fallback).toBeInTheDocument(); expect(screen.getByText('Covered', { selector: '.badge' })).toBeInTheDocument();
    expect(screen.queryByText('Loading Traceability…')).not.toBeInTheDocument();
    await act(async () => pending.resolve(response(page([requirement], true))));
    expect(await screen.findByRole('link', { name: requirement.logical_key })).toBeInTheDocument();
    expect(screen.getByText(requirement.title)).toBeInTheDocument(); expect(screen.getByText(/Requirement names come from a bounded list/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(4);
  });

  it('renders all coverage semantics, gaps, status counts and honest independent truncation', async () => {
    routes({ [api+'/traceability?limit=50']: response({ ...traceability, requirements: page(traceability.requirements.items, true), links: page(traceability.links.items, true) }) }); open('/traceability');
    expect(await screen.findByText('0 — coverage gap')).toBeInTheDocument();
    for (const status of ['Covered', 'Partial', 'Not covered']) expect(screen.getByText(status, { selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText(/not a complete matrix/)).toBeInTheDocument(); expect(screen.getByText(/additional links are not shown/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Requirement coverage table' })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('link', { name: specification.id })).toHaveAttribute('href', base+'/test-specifications?test_spec_id=test-a');
    expect(fetch).toHaveBeenCalledTimes(4);
  });
  it.each([['requirements', 'requirement_id', requirement, '/requirements/requirement-a'], ['test-specifications', 'test_spec_id', specification, '/test-specifications/test-a']] as const)('loads one selected record outside the bounded %s list', async (section, param, record, detail) => {
    routes({ [api+'/'+section+'?limit=50']: response(page([], true)), [api+detail]: response(record) });
    open('/'+section+'?'+param+'='+record.id);
    expect(await screen.findByRole('heading', { name: record.title })).toBeInTheDocument();
    expect(screen.getByText(/outside the bounded list/)).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === api+detail)).toHaveLength(1);
    await waitFor(() => expect(document.getElementById((section === 'requirements' ? 'requirement-' : 'test-')+record.id)).toHaveFocus());
  });
  it('uses a listed selected test without a redundant detail request', async () => {
    routes(); open('/test-specifications?test_spec_id=test-a'); await screen.findByText(specification.title);
    expect(fetch).toHaveBeenCalledTimes(4); expect(screen.getByRole('link', { name: 'Clear selection' })).toHaveAttribute('href', base+'/test-specifications');
  });
});

describe('loading, empty and safe error states', () => {
  it.each([['requirements', 'No Requirements have been extracted yet.'], ['test-specifications', 'No Test Specifications have been imported or generated yet.'], ['traceability', 'No Requirements to assess for traceability.']])('handles empty %s without fake records', async (section, message) => {
    routes({ [api+'/'+section+'?limit=50']: response(section === 'traceability' ? { ...traceability, requirements: page([]), links: page([]) } : page([])) }); open('/'+section);
    expect(await screen.findByText(message)).toBeInTheDocument();
  });
  it.each(['requirements', 'test-specifications', 'traceability', 'readiness'])('shows loading for %s', async section => {
    const pending = deferred<Response>(); const path = api+'/'+section+(section === 'readiness' ? '' : '?limit=50'); routes({ [path]: pending.promise }); open('/'+section);
    expect(await screen.findByText('Loading '+(section === 'test-specifications' ? 'Test Specifications' : section === 'requirements' ? 'Requirements' : section === 'traceability' ? 'Traceability' : 'readiness')+'…')).toBeInTheDocument();
  });
  it.each(['requirements', 'test-specifications', 'traceability', 'readiness'])('safely presents errors in %s without raw exceptions or automatic retries', async section => {
    const path = api+'/'+section+(section === 'readiness' ? '' : '?limit=50'); routes({ [path]: response({ stack: 'DO_NOT_RENDER_STACK' }, 500) }); open('/'+section);
    expect(await screen.findByText('HTTP_ERROR')).toBeInTheDocument(); expect(document.body).not.toHaveTextContent('DO_NOT_RENDER_STACK');
    const count = vi.mocked(fetch).mock.calls.length; await act(async () => Promise.resolve()); expect(fetch).toHaveBeenCalledTimes(count);
  });
  it.each(['requirements', 'test-specifications', 'traceability', 'readiness'])('retains safe scoped not-found errors for %s', async section => {
    const path = api+'/'+section+(section === 'readiness' ? '' : '?limit=50'); routes({ [path]: response({ error: { code: 'CAMPAIGN_NOT_FOUND', message: 'Campaign not found' } }, 404) }); open('/'+section);
    expect(await screen.findByRole('alert')).toHaveTextContent('CAMPAIGN_NOT_FOUND');
  });
  it('discards stale Campaign reads when navigating to another Campaign', async () => {
    const old = deferred<Response>(); const other = { ...campaign, id: 'campaign-b', name: 'Second Campaign' };
    routes({ [api]: old.promise, ['/api/v1/projects/project-a/campaigns/campaign-b']: response(other), ['/api/v1/projects/project-a/campaigns/campaign-b/readiness']: response({ ...readiness, campaign_id: other.id }) });
    render(<MemoryRouter initialEntries={[base]}><Link to="/projects/project-a/campaigns/campaign-b">Switch Campaign</Link><App /></MemoryRouter>);
    fireEvent.click(screen.getByRole('link', { name: 'Switch Campaign' })); await screen.findByRole('heading', { name: 'Second Campaign' });
    await act(async () => old.resolve(response(campaign))); expect(screen.queryByRole('heading', { name: campaign.name })).not.toBeInTheDocument();
  });
});

it.each<ReviewStatus | CoverageStatus | ReadinessStatus>(['DRAFT', 'READY_FOR_REVIEW', 'NEEDS_CLARIFICATION', 'APPROVED', 'COVERED', 'PARTIAL', 'NOT_COVERED', 'READY', 'NOT_READY'])('presents %s with visible readable text', status => {
  const { container } = render(<CampaignStatusBadge status={status} />);
  expect(container.querySelector('.badge')).toHaveAttribute('title', status); expect(container.querySelector('.badge')?.textContent).toBeTruthy();
  expect(container.textContent).not.toMatch(/PASS|FAIL/);
});
