import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Link } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { StateBadge } from '../components/StatusBadge';
import { CampaignStatusBadge } from '../components/CampaignStatusBadge';
import { campaign, readiness, requirement, blockedRequirement, specification, traceability } from '../test/campaigns';
import { page, project, response } from '../test/fixtures';

const base = `/projects/${project.id}/campaigns/${campaign.id}`, api = '/api/v1'+base;
function routes(overrides: Record<string, unknown> = {}) {
  const fixtures: Record<string, unknown> = { [api]: campaign, [api+'/readiness']: readiness,
    [api+'/requirements?limit=50']: page([requirement, blockedRequirement]),
    [api+'/traceability?limit=50']: traceability, [api+'/sources?limit=50']: page([]),
    [api+'/test-specifications?limit=50']: page([specification]), ['/api/v1/projects?limit=50']: page([project]), ...overrides };
  vi.mocked(fetch).mockImplementation(async input => {
    const url=String(input);
    if (!(url in fixtures)) throw new Error('Unexpected request '+url);
    return fixtures[url] instanceof Response ? fixtures[url] as Response : response(fixtures[url]);
  });
}
function open(suffix='') {
  return render(<MemoryRouter initialEntries={[base+suffix]}><Link to="/projects">Leave Campaign</Link><App /></MemoryRouter>);
}

describe('workspace navigation and hierarchy', () => {
  it('uses loaded Campaign context, Preparation/Execution groups and no extra requests', async () => {
    routes();open();
    const sidebar=await screen.findByRole('complementary',{name:'Workspace navigation'});
    const nav=await within(sidebar).findByRole('navigation',{name:'Campaign preparation'});
    expect(within(nav).getByText('PREPARATION')).toBeInTheDocument();
    expect(within(nav).getByText('EXECUTION')).toBeInTheDocument();
    expect(within(nav).getAllByRole('link')).toHaveLength(6);
    expect(within(nav).getByRole('link',{name:'Overview'})).toHaveAttribute('aria-current','page');
    expect(within(sidebar).getByText(campaign.name)).toBeInTheDocument();
    await screen.findByText('Not ready');expect(fetch).toHaveBeenCalledTimes(2);
    expect(within(sidebar).queryByText(/Reports|Dashboard|Playwright/)).not.toBeInTheDocument();
  });
  it('retains one navigation set and changes active route through ordinary links', async () => {
    routes();open('/requirements');
    const nav=await screen.findByRole('navigation',{name:'Campaign preparation'});
    expect(within(nav).getByRole('link',{name:'Requirements'})).toHaveAttribute('aria-current','page');
    fireEvent.click(within(nav).getByRole('link',{name:'Traceability'}));
    await screen.findByRole('table');
    expect(within(nav).getByRole('link',{name:'Traceability'})).toHaveAttribute('aria-current','page');
    expect(within(nav).getByRole('link',{name:'Requirements'})).not.toHaveAttribute('aria-current');
    expect(screen.getAllByRole('navigation',{name:'Campaign preparation'})).toHaveLength(1);
    expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method)).toBe(true);
  });
  it('clears Campaign context after leaving and preserves skip-to-content target', async () => {
    routes();open();await screen.findByText('Not ready');
    fireEvent.click(screen.getByRole('link',{name:'Leave Campaign'}));
    await screen.findByRole('heading',{name:'Projects',level:1});
    expect(screen.queryByRole('navigation',{name:'Campaign preparation'})).not.toBeInTheDocument();
    const skip=screen.getByRole('link',{name:'Skip to content'});skip.focus();
    expect(skip).toHaveFocus();expect(skip).toHaveAttribute('href','#main-content');
    expect(screen.getByRole('main')).toHaveAttribute('id','main-content');
    expect(screen.getByRole('main')).toHaveAttribute('tabindex','-1');
  });
  it('keeps current Requirements before source intake and recovery reachable', async () => {
    routes();open('/requirements');
    const main=screen.getByRole('main');
    const heading=await within(main).findByRole('heading',{name:'Requirements',level:2});
    const intake=within(main).getByRole('heading',{name:'Add PRD / Spec'});
    expect(heading.compareDocumentPosition(intake)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(main).getByRole('link',{name:'Add PRD / Spec'})).toHaveAttribute('href','#specification-sources');
    const blocked=(await within(main).findByRole('heading',{name:blockedRequirement.title})).closest('tr')!;
    fireEvent.click(within(blocked).getByText('Add info / Clarify'));
    fireEvent.click(within(blocked).getByRole('button',{name:'Add Clarification / Provide Missing Information'}));
    expect(within(blocked).getByLabelText('Missing facts (no credentials or secrets)')).toBeVisible();
    expect(within(blocked).getByRole('button',{name:'Save Clarification'})).toBeVisible();
    expect(within(blocked).queryByRole('button',{name:'Approve Requirement'})).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method)).toBe(true);
  });
  it('displays Test steps, required evidence, explicit Requirement links and secondary provenance', async () => {
    routes();open('/test-specifications');
    const title=await screen.findByRole('heading',{name:specification.title});
    const record=title.closest('li')!;
    expect(within(record).getByText('Submit a payment')).toBeVisible();
    expect(within(record).getByText('Observed payment state')).toBeVisible();
    expect(within(record).getByRole('link',{name:requirement.id})).toHaveAttribute('href',base+'/requirements?requirement_id='+requirement.id);
    const provenance=within(record).getByText('Provenance and audit identity').closest('details')!;
    expect(provenance).not.toHaveAttribute('open');
    expect(vi.mocked(fetch).mock.calls.some(([url])=>String(url).includes('/requirements/'+requirement.id))).toBe(false);
  });
});

describe('read-only preparation guidance', () => {
  it('distinguishes satisfied and blocking checks while using full server aggregates', async () => {
    routes();open('/readiness');await screen.findByText('Not ready');
    const next=screen.getByRole('region',{name:'Next preparation action'});
    expect(within(next).getByRole('link',{name:'Continue Requirements'})).toHaveAttribute('href',base+'/requirements');
    const checks=screen.getByRole('heading',{name:'Readiness checks'}).closest('section')!;
    expect(within(checks).getAllByText('Satisfied')).toHaveLength(4);
    expect(within(checks).getAllByText('Blocking')).toHaveLength(2);
    const summary=screen.getByRole('heading',{name:'Preparation summary'}).closest('section')!;
    expect(summary).toHaveTextContent('Requirements100');expect(summary).toHaveTextContent('Test Specifications130');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('offers only navigation to Runs when backend says READY, without execution claims', async () => {
    routes({[api+'/readiness']:{...readiness,status:'READY',blocker_codes:[]}});open();
    const next=await screen.findByRole('region',{name:'Next preparation action'});
    expect(within(next).getByRole('link',{name:'Open Runs'})).toHaveAttribute('href',base+'/runs');
    expect(next).toHaveTextContent('explicitly synthetic');
    expect(screen.queryByText('PASS')).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([,options])=>!options?.method)).toBe(true);
  });
  it('does not fabricate guidance or counts when readiness fails', async () => {
    routes({[api+'/readiness']:response({stack:'PRIVATE_ERROR'},500)});open();
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP_ERROR');
    expect(screen.queryByRole('region',{name:'Next preparation action'})).not.toBeInTheDocument();
    expect(screen.queryByRole('heading',{name:'Preparation summary'})).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('PRIVATE_ERROR');
  });
});

describe('textual status system', () => {
  it.each(['DRAFT','READY_FOR_REVIEW','NEEDS_CLARIFICATION','APPROVED','READY','NOT_READY','CREATED','RUNNING','COMPLETED','FAILED','PASS','FAIL','NOT_EVALUATED','NOT_STARTED','PARTIAL','SKIP'])('preserves visible domain status %s', status => {
    render(<StateBadge status={status}/>);
    expect(screen.getByText(status)).toHaveAttribute('title',status);
  });
  it('preserves friendly Campaign labels and exact domain metadata', () => {
    render(<CampaignStatusBadge status="NEEDS_CLARIFICATION"/>);
    expect(screen.getByText('Needs clarification')).toHaveAttribute('title','NEEDS_CLARIFICATION');
  });
});
