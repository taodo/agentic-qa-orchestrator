import { useCallback,useEffect,useRef,useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { browserCapability } from '../api/browser';
import { batchPagePath,submitBrowserBatch,type BrowserBatch,type BrowserMode } from '../api/browserBatches';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { ErrorState } from './Feedback';
export function useBrowserCapability(p:string,c:string) {return useResource(useCallback(()=>browserCapability(p,c),[p,c]));}
export function BrowserRunSelected({p,c,base,ids,disabled=false,capability}:{p:string;c:string;base:string;ids:string[];disabled?:boolean;capability:ReturnType<typeof useBrowserCapability>}) {
 const navigate=useNavigate(),[open,setOpen]=useState(false),[mode,setMode]=useState<BrowserMode>('HEADLESS');
 const [intent,setIntent]=useState<{idempotency_key:string;test_specification_ids:string[];browser_mode:BrowserMode}>();
 const action=usePreparationAction<BrowserBatch>(),trigger=useRef<HTMLButtonElement>(null),dialog=useRef<HTMLDialogElement>(null),scope=useRef('');scope.current=p+'/'+c;
 const available=capability.data?.automatic==='AVAILABLE';
 useEffect(()=>{if(open){const node=dialog.current;if(node && !node.open){if(typeof node.showModal==='function')node.showModal();else node.setAttribute('open','');}node?.querySelector<HTMLInputElement>('input')?.focus();}},[open]);
 function close(){if(action.busy)return;setOpen(false);trigger.current?.focus();}
 async function run(){
  if(!available || action.busy)return;
  const body=intent??{idempotency_key:crypto.randomUUID(),test_specification_ids:[...ids],browser_mode:mode};
  const owner=p+'/'+c;setIntent(body);
  await action.run(()=>submitBrowserBatch(p,c,body),async batch=>{if(scope.current===owner)navigate(batchPagePath(base,batch.id));});
 }
 if(!available && capability.data?.source_free_review!=='AVAILABLE')return null;
 return <><button ref={trigger} className="button--primary" disabled={disabled||!available||!ids.length||ids.length>500||action.busy} onClick={()=>{setIntent(undefined);setMode('HEADLESS');setOpen(true);}}>Run selected</button>
 {!available && <p className="hint">{capability.loading?'Checking local browser capability…':capability.data?.automatic_reason??'Automatic browser execution requires a configured trusted local host and WEB Target.'}</p>}
 {open && <dialog ref={dialog} aria-modal="true" aria-label={`Run ${intent?.test_specification_ids.length??ids.length} selected tests`} className="panel browser-run-dialog" onCancel={event=>{event.preventDefault();close();}} onKeyDown={event=>{if(event.key==='Escape'){event.preventDefault();close();}if(event.key==='Tab'){const nodes=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)')??[]);const first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}}}}>
 <h2>Run {intent?.test_specification_ids.length??ids.length} selected tests</h2><fieldset disabled={action.busy||!!intent}><legend>Browser mode</legend>
 <label><input type="radio" name="browser-mode" value="HEADLESS" checked={mode==='HEADLESS'} onChange={()=>setMode('HEADLESS')}/> Headless</label><p className="hint">Faster · Recommended</p>
 <label><input type="radio" name="browser-mode" value="HEADED" checked={mode==='HEADED'} onChange={()=>setMode('HEADED')}/> Headed</label><p className="hint">Watch browser execution</p></fieldset>
 {mode==='HEADED' && ids.length>=25 && <p className="notice">Headed mode is best suited to smaller runs. All selected tests can still be submitted.</p>}
 <p>Tests are prepared automatically. Any test that cannot be safely prepared stays visible as Needs attention.</p>
 {action.error && <><ErrorState error={action.error}/><p>No automatic retry was sent. Retry uses the same immutable request; no new batch is created.</p></>}
 <div className="actions"><button disabled={action.busy} onClick={close}>Cancel</button><button className="button--primary" disabled={action.busy||action.error?.code==='HOST_AUTH_REQUIRED'} onClick={()=>void run()}>{action.busy?'Submitting…':intent?'Retry same request':'Run'}</button></div></dialog>}
 </>;
}
