import { afterEach, describe, expect, it, vi } from 'vitest';
import { initializeAccess } from './access';
import { createCampaign, getCampaign, getRequirement, getTestSpecification, getReadiness, getTraceability, listCampaigns, listRequirements, listTestSpecifications } from './campaigns';
import { response } from '../test/fixtures';
import { campaign } from '../test/campaigns';

afterEach(async () => { vi.mocked(fetch).mockResolvedValue(response({ mode: 'demo' })); await initializeAccess(); });
describe('scoped Phase 2 read clients', () => {
  it.each([
    [() => listCampaigns('p/a'), '/projects/p%2Fa/campaigns?limit=50'],
    [() => getCampaign('p/a', 'c/b'), '/projects/p%2Fa/campaigns/c%2Fb'],
    [() => listRequirements('p/a', 'c/b'), '/projects/p%2Fa/campaigns/c%2Fb/requirements?limit=50'],
    [() => listTestSpecifications('p/a', 'c/b'), '/projects/p%2Fa/campaigns/c%2Fb/test-specifications?limit=50'],
    [() => getTraceability('p/a', 'c/b'), '/projects/p%2Fa/campaigns/c%2Fb/traceability?limit=50'],
    [() => getReadiness('p/a', 'c/b'), '/projects/p%2Fa/campaigns/c%2Fb/readiness'],
    [() => getRequirement('p/a', 'c/b', 'r/c'), '/projects/p%2Fa/campaigns/c%2Fb/requirements/r%2Fc'],
    [() => getTestSpecification('p/a', 'c/b', 't/c'), '/projects/p%2Fa/campaigns/c%2Fb/test-specifications/t%2Fc'],
  ] as const)('encodes ownership and uses one existing transport request to %s', async (call, path) => {
    vi.mocked(fetch).mockResolvedValue(response({})); await call();
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/v1'+path, expect.objectContaining({ credentials: 'same-origin', headers: {} }));
  });
  it('creates with name/objective only and never replays an error', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ error: { code: 'INVALID_INPUT', message: 'Invalid application input' } }, 422));
    await expect(createCampaign('p/a', { name: 'Checkout', objective: 'Verify payment' })).rejects.toMatchObject({ code: 'INVALID_INPUT' });
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/v1/projects/p%2Fa/campaigns', expect.objectContaining({ method: 'POST', body: '{"name":"Checkout","objective":"Verify payment"}' }));
  });
  it('preserves hosted CSRF on creation and no auth material is persisted', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ mode: 'hosted-demo', csrf: 'b'.repeat(64) })); await initializeAccess(); vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockResolvedValue(response(campaign, 201));
    await createCampaign('p', { name: 'Checkout' });
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/v1/projects/p/campaigns', expect.objectContaining({ credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-QA-Sentinel-CSRF': 'b'.repeat(64) }, body: '{"name":"Checkout"}' }));
  });
});
