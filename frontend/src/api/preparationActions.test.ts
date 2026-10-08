import { afterEach, describe, expect, it, vi } from 'vitest';
import { initializeAccess } from './access';
import { ingestSource, listSources, extractRequirements, importTests, generateTests, reviewRequirement, reviewTest, getRequirementReview, getTestReview, transitionCampaign } from './campaigns';
import { response } from '../test/fixtures';
const root='/api/v1/projects/p%2Fa/campaigns/c%2Fb';
const approval={action:'APPROVE' as const,reviewer_label:'qa-human',note:'Reviewed.'};
const writes = [
  [() => ingestSource('p/a','c/b',{name:'PRD',source_type:'MARKDOWN',content:'# Spec'}), '/sources', {name:'PRD',source_type:'MARKDOWN',content:'# Spec'}],
  [() => extractRequirements('p/a','c/b','s/x'), '/sources/s%2Fx/extract-requirements', {}],
  [() => importTests('p/a','c/b',{name:'Tests',format:'CSV',content:'data'}), '/test-imports', {name:'Tests',format:'CSV',content:'data'}],
  [() => generateTests('p/a','c/b',['r1','r2']), '/generate-tests', {requirement_ids:['r1','r2']}],
  [() => reviewRequirement('p/a','c/b','r/x',approval), '/requirements/r%2Fx/review', approval],
  [() => reviewTest('p/a','c/b','t/x',approval), '/test-specifications/t%2Fx/review', approval],
  [() => transitionCampaign('p/a','c/b','READY_FOR_REVIEW'), '/transitions', {status:'READY_FOR_REVIEW'}],
] as const;
afterEach(async()=>{vi.mocked(fetch).mockResolvedValue(response({mode:'demo'}));await initializeAccess();});
describe('accepted scoped preparation clients',()=>{
  it.each(writes)('posts the exact accepted body and hosted CSRF for %s',async(call,path,body)=>{
    vi.mocked(fetch).mockResolvedValueOnce(response({mode:'hosted-demo',csrf:'c'.repeat(64)}));await initializeAccess();vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockResolvedValue(response({}));await call();
    expect(fetch).toHaveBeenCalledExactlyOnceWith(root+path,expect.objectContaining({method:'POST',body:JSON.stringify(body),credentials:'same-origin',headers:{'Content-Type':'application/json','X-QA-Sentinel-CSRF':'c'.repeat(64)}}));
  });
  it.each(writes)('never replays a failed write %s',async(call)=>{
    vi.mocked(fetch).mockResolvedValue(response({error:{code:'INVALID_INPUT',message:'Invalid application input'}},422));
    await expect(call()).rejects.toMatchObject({code:'INVALID_INPUT'});expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    [()=>listSources('p/a','c/b'),'/sources?limit=50'],
    [()=>getRequirementReview('p/a','c/b','r/x'),'/requirements/r%2Fx/review'],
    [()=>getTestReview('p/a','c/b','t/x'),'/test-specifications/t%2Fx/review'],
  ] as const)('uses bounded or individual explicit review reads %s',async(call,path)=>{
    vi.mocked(fetch).mockResolvedValue(response({}));await call();expect(fetch).toHaveBeenCalledExactlyOnceWith(root+path,expect.objectContaining({credentials:'same-origin',headers:{}}));
  });
  it('does not replay after hosted authentication expires',async()=>{
    const assign=vi.fn(), testWindow=Object.create(window);Object.defineProperty(testWindow,'location',{value:{assign}});vi.stubGlobal('window',testWindow);
    vi.mocked(fetch).mockResolvedValueOnce(response({mode:'hosted-demo',csrf:'d'.repeat(64)}));await initializeAccess();vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockResolvedValue(response({error:{code:'HOST_AUTH_REQUIRED',message:'Sign in again'}},401));
    await expect(generateTests('p','c',['r'])).rejects.toMatchObject({code:'HOST_AUTH_REQUIRED'});
    await expect(generateTests('p','c',['r'])).rejects.toMatchObject({code:'HOST_AUTH_REQUIRED'});
    expect(fetch).toHaveBeenCalledTimes(1);expect(assign).toHaveBeenCalledExactlyOnceWith('/login');
  });
});
