import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { App } from '../app/App';
import { CampaignForm } from '../components/CampaignForm';
import { campaign, readiness } from '../test/campaigns';
import { deferred, page, project, response } from '../test/fixtures';
const base = '/api/v1/projects/'+project.id;
function open() { return render(<MemoryRouter initialEntries={['/projects/'+project.id]}><App /></MemoryRouter>); }
function mock(post: () => Promise<Response> = async () => response(campaign, 201), list = page([campaign])) {
  return vi.mocked(fetch).mockImplementation((input, options) => {
    const url=String(input);
    if (options?.method === 'POST') return post();
    if (url === base+'/campaigns?limit=50') return Promise.resolve(response(list));
    if (url === base+'/campaigns/'+campaign.id+'/readiness') return Promise.resolve(response(readiness));
    if (url === base+'/campaigns/'+campaign.id) return Promise.resolve(response(campaign));
    if (url === '/api/v1/projects/other') return Promise.resolve(response({ ...project, id: 'other', name: 'Other Project' }));
    if (url === '/api/v1/projects/other/campaigns?limit=50') return Promise.resolve(response(page([])));
    if (url === base) return Promise.resolve(response(project));
    return Promise.reject(new Error('Unexpected request: '+url));
  });
}
function fill() {
  fireEvent.change(screen.getByLabelText(/Campaign name/), { target: { value: '  Checkout QA  ' } });
  fireEvent.change(screen.getByLabelText(/Objective/), { target: { value: 'Payment preparation' } });
}
describe('Project Campaign primary journey', () => {
  it('lists scoped Campaigns and discloses truncation without loading legacy runtime', async () => {
    mock(undefined,page([campaign],true)); open();
    expect(await screen.findByRole('link',{ name: campaign.name })).toHaveAttribute('href','/projects/'+project.id+'/campaigns/'+campaign.id);
    expect(screen.getByText('Approved',{ selector: '.badge' })).toBeInTheDocument();
    expect(screen.getByText(/Additional records/)).toBeInTheDocument();
    expect(screen.queryByRole('button',{ name: 'Create Task' })).not.toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('shows Campaign list loading and then an honest empty state', async () => {
    const pending=deferred<Response>(); mock(undefined,page([]));
    vi.mocked(fetch).mockImplementation(input => String(input).includes('campaigns?') ? pending.promise : Promise.resolve(response(project)));
    open(); expect(await screen.findByText('Loading Campaigns…')).toBeInTheDocument();
    await act(async () => pending.resolve(response(page([]))));
    expect(await screen.findByText(/No Campaigns yet/)).toBeInTheDocument();
  });
  it('creates only metadata, prevents duplicate submission and opens returned server identity', async () => {
    const pending=deferred<Response>(); const calls=mock(()=>pending.promise); open(); await screen.findByRole('link',{name: campaign.name}); fill();
    const button=screen.getByRole('button',{name:'Create Campaign'}); fireEvent.click(button); fireEvent.click(button);
    expect(calls.mock.calls.filter(([,options])=>options?.method==='POST')).toHaveLength(1);
    const post=calls.mock.calls.find(([,options])=>options?.method==='POST')!;
    expect(post[0]).toBe(base+'/campaigns'); expect(JSON.parse(String(post[1]?.body))).toEqual({name:'Checkout QA',objective:'Payment preparation'});
    await act(async()=>pending.resolve(response(campaign,201)));
    expect(await screen.findByRole('heading',{name:'Overview'})).toBeInTheDocument();
  });
  it('preserves values after a safe failure and never retries the POST automatically', async () => {
    const calls=mock(async()=>response({error:{code:'INVALID_REQUEST',message:'Campaign metadata rejected'}},422)); open(); await screen.findByRole('link',{name:campaign.name}); fill(); fireEvent.click(screen.getByRole('button',{name:'Create Campaign'}));
    expect(await screen.findByText('INVALID_REQUEST')).toBeInTheDocument(); expect(screen.getByLabelText(/Campaign name/)).toHaveValue('  Checkout QA  ');
    expect(screen.getByLabelText(/Objective/)).toHaveValue('Payment preparation'); expect(screen.queryByRole('button',{name:'Retry'})).not.toBeInTheDocument();
    expect(calls.mock.calls.filter(([,options])=>options?.method==='POST')).toHaveLength(1);
  });
  it('does not navigate after an old Project creation completes', async () => {
    const pending=deferred<Response>(); mock(()=>pending.promise);
    render(<MemoryRouter initialEntries={['/projects/'+project.id]}><Link to="/projects/other">Other Project link</Link><App /></MemoryRouter>);
    await screen.findByRole('link',{name:campaign.name}); fill(); fireEvent.click(screen.getByRole('button',{name:'Create Campaign'})); fireEvent.click(screen.getByText('Other Project link'));
    await screen.findByRole('heading',{name:'Other Project'}); await act(async()=>pending.resolve(response(campaign,201)));
    expect(screen.getByRole('heading',{name:'Other Project'})).toBeInTheDocument(); expect(screen.queryByRole('heading',{name:'Overview'})).not.toBeInTheDocument();
  });
  it.each([' ', 'x'.repeat(201)])('rejects invalid name before request', value => {
    render(<CampaignForm projectId={project.id} onCreated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Campaign name/),{target:{value}}); fireEvent.submit(screen.getByRole('button',{name:'Create Campaign'}).closest('form')!);
    expect(screen.getByRole('status')).toHaveTextContent('1–200'); expect(fetch).not.toHaveBeenCalled();
  });
  it('rejects oversized objective before request', () => {
    render(<CampaignForm projectId={project.id} onCreated={vi.fn()} />); fill();
    fireEvent.change(screen.getByLabelText(/Objective/),{target:{value:'x'.repeat(4001)}}); fireEvent.submit(screen.getByRole('button',{name:'Create Campaign'}).closest('form')!);
    expect(fetch).not.toHaveBeenCalled();
  });
});
