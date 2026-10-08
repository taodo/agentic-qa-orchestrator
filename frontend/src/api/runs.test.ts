import { afterEach, describe, expect, it, vi } from 'vitest';
import { initializeAccess } from './access';
import { createRun, getRun, listRuns, listRunTests, listRunRequirements, startRun } from './runs';
import { response } from '../test/fixtures';

afterEach(async () => { vi.mocked(fetch).mockResolvedValue(response({mode:'demo'})); await initializeAccess(); vi.unstubAllGlobals(); });
describe('scoped Run transport', () => {
  it.each([
    [() => listRuns('p/a','c/b'), '/projects/p%2Fa/campaigns/c%2Fb/runs?limit=50'],
    [() => getRun('p/a','c/b','r/c'), '/projects/p%2Fa/campaigns/c%2Fb/runs/r%2Fc'],
    [() => listRunTests('p/a','c/b','r/c',50), '/projects/p%2Fa/campaigns/c%2Fb/runs/r%2Fc/tests?limit=50&after_position=50'],
    [() => listRunRequirements('p/a','c/b','r/c'), '/projects/p%2Fa/campaigns/c%2Fb/runs/r%2Fc/requirements?limit=50&after_position=0'],
  ] as const)('encodes owners/identity and bounds snapshot reads',async (call,path) => {
    vi.mocked(fetch).mockResolvedValue(response({})); await call();
    expect(fetch).toHaveBeenCalledExactlyOnceWith('/api/v1'+path,expect.objectContaining({credentials:'same-origin',headers:{}}));
  });
  it('uses existing same-origin hosted CSRF for explicit Create and Start',async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({mode:'hosted-demo',csrf:'b'.repeat(64)})); await initializeAccess(); vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockImplementation(async () => response({}));
    await createRun('p','c',{idempotency_key:'intent',note:'RC'}); await startRun('p','c','r');
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenLastCalledWith('/api/v1/projects/p/campaigns/c/runs/r/start',expect.objectContaining({method:'POST',body:'{}',credentials:'same-origin',headers:{'Content-Type':'application/json','X-QA-Sentinel-CSRF':'b'.repeat(64)}}));
  });
  it('never replays writes after authentication failure',async () => {
    const assign=vi.fn(), testWindow=Object.create(window);
    Object.defineProperty(testWindow,'location',{value:{assign}}); vi.stubGlobal('window',testWindow);
    vi.mocked(fetch).mockResolvedValue(response({error:{code:'HOST_AUTH_REQUIRED',message:'secret server text'}},401));
    await expect(startRun('p','c','r')).rejects.toMatchObject({code:'HOST_AUTH_REQUIRED',message:'Sign in again to continue.'});
    await expect(startRun('p','c','r')).rejects.toMatchObject({code:'HOST_AUTH_REQUIRED'});
    expect(fetch).toHaveBeenCalledTimes(1); expect(assign).toHaveBeenCalledExactlyOnceWith('/login');
  });
});
