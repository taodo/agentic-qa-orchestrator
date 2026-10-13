import { fireEvent,render,screen,waitFor,within,act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { it,expect,vi } from 'vitest';
import { BrowserFactsForm } from './BrowserFactsForm';
import { BrowserPlanning,CandidateReview,BrowserRunStart } from './BrowserPlanning';
import { specification } from '../test/campaigns';
import { response,deferred,page } from '../test/fixtures';
import type { BrowserCandidate } from '../api/browser';
import type { QARun } from '../api/runTypes';
const p='project',c='campaign',base=`/api/v1/projects/${p}/campaigns/${c}/browser`;
const test={...specification,id:'test',key:'WEB',title:'Known web test',preconditions:[],steps:[{index:1,action:'Navigate and verify heading',expected:'Ready'}],overall_expected_result:'Ready',unresolved_requirement_refs:[]};
const target={schema_version:'web-target-snapshot-v1' as const,target_id:'target',project_id:p,name:'Generic <img src=x onerror=alert(1)>',type:'WEB' as const,environment:'STAGING' as const,base_url:'https://example.invalid'};
const candidate:BrowserCandidate={id:'candidate',test_id:test.id,test_key:test.key,test_title:test.title,target,test_hash:'a'.repeat(64),target_hash:'b'.repeat(64),origin:'AI',prompt_version:'browser-plan-generator-v1',status:'SUCCEEDED',error_code:null,configured_model:'configured',provider_model:'reported',input_tokens:12,output_tokens:null,reasoning_tokens:null,total_tokens:null,plan_hash:'c'.repeat(64),accepted_run_id:null,
 output:{disposition:'CANDIDATE',unable_reason:null,step_bindings:[1,1],plan:{version:'browser-execution-plan-v1',steps:[{action:'NAVIGATE',path:'/known',timeout_ms:5000},{action:'ASSERT_TEXT',locator:{strategy:'CSS',value:'h1'},text:'Ready <script>bad</script>',exact:true,timeout_ms:5000}],test_timeout_ms:30000,redirect_limit:0,screenshot_limit:0,evidence_limit:50}}};
const run={id:'run',executor_kind:'WEB_BROWSER',execution_status:'CREATED',qa_outcome:'NOT_EVALUATED'} as QARun;
const writes=()=>vi.mocked(fetch).mock.calls.filter(([,options])=>options?.method==='POST');
function mount(node:React.ReactNode){return render(<MemoryRouter>{node}</MemoryRouter>);}
function mockRoutes(extra:(url:string,options?:RequestInit)=>Response|Promise<Response>|undefined=()=>undefined){vi.mocked(fetch).mockImplementation(async(input,options)=>{
 const url=String(input),custom=extra(url,options);if(custom)return custom;
 if(url===base+'/capability')return response({planning:'AVAILABLE',execution:'AVAILABLE'});
 if(url===base+'/tests/test/readiness')return response({status:'AVAILABLE',test_id:'test',target});
 return response({error:{code:'NOT_FOUND',message:'Not found'}},404);
});}
it('authors structured approved facts without JSON, then saves a successor intent only once',async()=>{
 const saved=deferred<Response>(),changed=vi.fn(async()=>{});mockRoutes((url)=>url===base+'/tests/test/facts'?saved.promise:undefined);
 mount(<BrowserFactsForm p={p} c={c} test={test} hash={'a'.repeat(64)} changed={changed}/>);
 fireEvent.click(screen.getByRole('button',{name:'Prepare browser facts'}));
 fireEvent.click(screen.getByRole('button',{name:'Add action for step 1'}));
 fireEvent.click(screen.getByRole('button',{name:'Add approved locator'}));
 fireEvent.change(screen.getByLabelText('Locator 1 value'),{target:{value:'h1'}});
 fireEvent.change(screen.getByLabelText('Approved relative paths (one per line)'),{target:{value:'/known'}});
 fireEvent.change(screen.getByLabelText('Facts reviewer label'),{target:{value:'operator'}});
 fireEvent.change(screen.getByLabelText('Facts review note'),{target:{value:'Known facts'}});
 fireEvent.click(screen.getByRole('checkbox'));
 expect(writes()).toHaveLength(0);expect(screen.queryByLabelText(/JSON/)).not.toBeInTheDocument();
 fireEvent.submit(screen.getByRole('form',{name:'Browser facts for WEB'}));fireEvent.submit(screen.getByRole('form',{name:'Browser facts for WEB'}));
 await waitFor(()=>expect(writes()).toHaveLength(1));const body=JSON.parse(writes()[0][1]!.body as string);
 expect(body).toEqual({facts:{contract_version:'browser-facts-v1',required_actions:[['NAVIGATE']],locators:[{strategy:'CSS',value:'h1'}],paths:['/known'],input_values:[]},non_secret:true,previous_hash:'a'.repeat(64),reviewer_label:'operator',note:'Known facts'});
 expect(screen.getByText(/successor Test requiring fresh approval/)).toBeInTheDocument();
 await act(async()=>saved.resolve(response({...test,id:'successor',review_status:'READY_FOR_REVIEW'})));expect(changed).toHaveBeenCalledOnce();
});
it('shows authoritative facts error and keeps approved content unchanged locally',async()=>{
 mockRoutes(url=>url.endsWith('/facts')?response({error:{code:'INVALID_INPUT',message:'Invalid request'}},422):undefined);
 mount(<BrowserFactsForm p={p} c={c} test={{...test,review_status:'APPROVED'}} hash={'a'.repeat(64)} changed={vi.fn(async()=>{})}/>);
 fireEvent.click(screen.getByRole('button',{name:'Prepare browser facts'}));fireEvent.submit(screen.getByRole('form',{name:'Browser facts for WEB'}));
 await screen.findByText(/Invalid request/);expect(writes()).toHaveLength(1);expect(test.preconditions).toEqual([]);
});
it.each(['FACTS_MISSING','FACTS_INVALID','TEST_NOT_APPROVED','TARGET_NOT_WEB','POLICY_REJECTED','PROVIDER_UNAVAILABLE'])('blocks generation honestly for %s without writes',async status=>{
 mockRoutes(url=>url.endsWith('/readiness')?response({status,test_id:'test',target:status==='TARGET_NOT_WEB'?null:target}):undefined);
 mount(<BrowserPlanning p={p} c={c} tests={[test]}/>);fireEvent.change(await screen.findByLabelText('Test for browser planning'),{target:{value:'test'}});
 expect(await screen.findByRole('button',{name:'Generate Browser Plan'})).toBeDisabled();expect(writes()).toHaveLength(0);
});
it('requires distinct Generate and Accept clicks, prevents duplicates and never starts implicitly',async()=>{
 const generated=deferred<Response>(),accepted=deferred<Response>();mockRoutes((url)=>url.endsWith('/generate')?generated.promise:url.endsWith('/accept')?accepted.promise:undefined);
 mount(<BrowserPlanning p={p} c={c} tests={[test]}/>);fireEvent.change(await screen.findByLabelText('Test for browser planning'),{target:{value:'test'}});
 const button=await screen.findByRole('button',{name:'Generate Browser Plan'});expect(writes()).toHaveLength(0);fireEvent.click(button);fireEvent.click(button);expect(writes()).toHaveLength(1);
 await act(async()=>generated.resolve(response(candidate)));const accept=await screen.findByRole('button',{name:'Accept Browser Plan'});
 expect(writes()).toHaveLength(1);expect(screen.queryByRole('button',{name:'Start Browser Run'})).not.toBeInTheDocument();
 fireEvent.click(accept);fireEvent.click(accept);await waitFor(()=>expect(writes()).toHaveLength(2));expect(JSON.parse(writes()[1][1]!.body as string).idempotency_key).toBeTruthy();
 await act(async()=>accepted.resolve(response(run)));expect(writes()).toHaveLength(2);expect(writes().some(([url])=>String(url).endsWith('/start'))).toBe(false);
});
it('renders ordered inert details, distinct provider models and unknown usage without raw reasoning',()=>{
 mount(<CandidateReview p={p} c={c} candidate={candidate}/>);
 const section=screen.getByRole('region',{name:'Browser candidate review'});
 expect(within(section).getAllByRole('listitem').map(row=>row.textContent)).toEqual([expect.stringContaining('NAVIGATE'),expect.stringContaining('ASSERT_TEXT')]);
 expect(screen.getByText(/Configured model: configured · Provider model: reported/)).toBeInTheDocument();
 expect(screen.getAllByText('Unknown')).toHaveLength(3);expect(document.querySelector('img')).toBeNull();expect(document.querySelector('script')).toBeNull();expect(document.body.textContent).toContain('<script>bad</script>');
 expect(document.body.textContent).not.toMatch(/chain.of.thought|raw provider|OPENAI_API_KEY/);expect(writes()).toHaveLength(0);
});
it.each(['STARTED','FAILED'] as const)('does not accept %s generation or fabricate a candidate',status=>{
 mount(<CandidateReview p={p} c={c} candidate={{...candidate,status,output:null,plan_hash:null,error_code:status==='FAILED'?'MODEL_CONNECTION':null}}/>);
 expect(screen.queryByRole('button',{name:'Accept Browser Plan'})).not.toBeInTheDocument();expect(writes()).toHaveLength(0);
});
it('history reads only on explicit request, never model/accept/start',async()=>{
 mockRoutes(url=>url===base+'/generations'?response(page([candidate],true)):url===base+'/generations/candidate'?response(candidate):undefined);
 mount(<BrowserPlanning p={p} c={c} tests={[test]}/>);await screen.findByLabelText('Test for browser planning');
 expect(vi.mocked(fetch).mock.calls).toHaveLength(1);fireEvent.click(screen.getByRole('button',{name:'Load candidate history'}));
 fireEvent.click(await screen.findByRole('button',{name:'Review candidate candidate'}));await screen.findByRole('button',{name:'Accept Browser Plan'});
 expect(writes()).toHaveLength(0);expect(vi.mocked(fetch).mock.calls).toHaveLength(3);
});
it.each(['FAIL','PASS'])('Start is explicit and refreshes completed QA %s without model capability',async outcome=>{
 const pending=deferred<Response>(),refresh=vi.fn(async()=>{});mockRoutes(url=>url.endsWith('/capability')?response({planning:'UNAVAILABLE',execution:'AVAILABLE'}):url.endsWith('/start')?pending.promise:undefined);
 mount(<BrowserRunStart p={p} c={c} run={run} refresh={refresh}/>);const start=await screen.findByRole('button',{name:'Start Browser Run'});expect(writes()).toHaveLength(0);
 fireEvent.click(start);fireEvent.click(start);expect(writes()).toHaveLength(1);await act(async()=>pending.resolve(response({...run,execution_status:'COMPLETED',qa_outcome:outcome})));
 expect(refresh).toHaveBeenCalledOnce();expect(screen.queryByRole('alert')).not.toBeInTheDocument();expect(writes()).toHaveLength(1);
});
it('system failure refreshes persisted Results without creating QA assertion data or retrying',async()=>{
 const refresh=vi.fn(async()=>{});mockRoutes(url=>url.endsWith('/start')?response({...run,execution_status:'FAILED',qa_outcome:'NOT_EVALUATED',browser_error_code:'BROWSER_LAUNCH_FAILED'}):undefined);
 mount(<BrowserRunStart p={p} c={c} run={run} refresh={refresh}/>);fireEvent.click(await screen.findByRole('button',{name:'Start Browser Run'}));await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());expect(writes()).toHaveLength(1);
});
it('public/unavailable host offers no browser action and performs no writes',async()=>{
 mockRoutes(url=>url.endsWith('/capability')?response({planning:'UNAVAILABLE',execution:'UNAVAILABLE'}):undefined);
 mount(<BrowserPlanning p={p} c={c} tests={[test]}/>);await screen.findByText(/Browser planning unavailable/);expect(screen.queryByRole('button',{name:'Generate Browser Plan'})).not.toBeInTheDocument();expect(writes()).toHaveLength(0);
});

it('keeps an explicit selected Test identity when its row leaves the bounded page',async()=>{
 mockRoutes();const view=mount(<BrowserPlanning p={p} c={c} tests={[test]}/>);
 fireEvent.change(await screen.findByLabelText('Test for browser planning'),{target:{value:'test'}});
 await screen.findByRole('button',{name:'Generate Browser Plan'});
 view.rerender(<MemoryRouter><BrowserPlanning p={p} c={c} tests={[]}/></MemoryRouter>);
 expect(screen.getByRole('option',{name:'Selected Test test (outside this page)'})).toBeInTheDocument();
 expect(screen.getByLabelText('Test for browser planning')).toHaveValue('test');expect(writes()).toHaveLength(0);
});
