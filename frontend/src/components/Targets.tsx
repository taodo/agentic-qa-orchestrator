import { Link } from 'react-router-dom';
import { useCallback, useState } from 'react';
import { useResource } from '../app/useResource';
import { usePreparationAction } from '../app/usePreparationAction';
import { listTargets,createTarget,updateTarget,getCampaignTarget,associateTarget,type Target,type TargetSnapshot,type TargetInput } from '../api/targets';
import { ErrorState,LoadingState,TruncationNotice } from './Feedback';
import { useCampaign } from '../pages/CampaignDetailPage';

export function TargetSummary({target,historical=false}:{target:Target|TargetSnapshot|null|undefined;historical?:boolean}) {
  return <section aria-label={historical?'Run Target snapshot':'Target Under Test'}><h3>{historical?'Run Target snapshot':'Target Under Test'}</h3>
    {target?<><strong>{target.name}</strong><p>{target.type} · {target.environment}</p><p className="mono">{'configuration' in target?target.configuration.base_url:target.base_url}</p></>:<p>{historical?'Target information was not captured for this Run.':'Target not configured'}</p>}
    <p className="hint">Target is the configured external system. Current executor is SYNTHETIC; no Target URL is visited.</p>
  </section>;
}

export function TargetOptions({projectId,value,onChange,name='target_id'}:{projectId:string;value:string;onChange:(value:string)=>void;name?:string}) {
  const targets=useResource(useCallback(()=>listTargets(projectId),[projectId]));
  return <>{targets.loading?<LoadingState>Loading Targets…</LoadingState>:targets.error?<ErrorState error={targets.error}/>:<><label>Target Under Test<select name={name} value={value} onChange={e=>onChange(e.target.value)}><option value="">Not configured</option>{value && !targets.data?.items.some(t=>t.id===value) && <option value={value}>Selected Target {value} (outside this list)</option>}{targets.data?.items.map(t=><option key={t.id} value={t.id}>{t.name} · {t.environment}</option>)}</select></label><TruncationNotice truncated={!!targets.data?.truncated}/></>}
    <p className="hint">Choose explicitly. A repository/workspace never supplies a Target automatically.</p></>;
}

export function TargetManager({projectId}:{projectId:string}) {
  const targets=useResource(useCallback(()=>listTargets(projectId),[projectId]));
  const [editing,setEditing]=useState<Target>();
  return <section className="panel"><h2>Target Under Test</h2><p>Configure the external WEB application by URL. Source-code access, a repository and workspace setup are optional and are not required to configure this Target.</p>
    {targets.loading?<LoadingState>Loading Targets…</LoadingState>:targets.error?<ErrorState error={targets.error}/>:<>
      {!targets.data?.items.length && <p>Target not configured</p>}
      {targets.data?.items.map(t=><article key={t.id}><TargetSummary target={t}/><button onClick={()=>setEditing(t)}>Edit {t.name}</button></article>)}<TruncationNotice truncated={!!targets.data?.truncated}/></>}
    <TargetEditor key={editing?.id??'new'} projectId={projectId} target={editing} changed={async()=>{setEditing(undefined);await targets.reload();}}/>
    {editing && <button onClick={()=>setEditing(undefined)}>Cancel Target edit</button>}
  </section>;
}
function TargetEditor({projectId,target,changed}:{projectId:string;target?:Target;changed:()=>Promise<void>}) {
  const action=usePreparationAction<Target>();
  return <form aria-label={target?'Edit WEB Target':'Create WEB Target'} onSubmit={e=>{e.preventDefault();const data=new FormData(e.currentTarget);const body:TargetInput={name:String(data.get('name')),type:'WEB',environment:String(data.get('environment')) as TargetInput['environment'],configuration:{base_url:String(data.get('base_url'))}};
    void action.run(()=>target?updateTarget(projectId,target.id,body):createTarget(projectId,body),async()=>{await changed();});}}>
    <fieldset disabled={action.busy}><legend>{target?'Edit Target':'New Target'}</legend><p>Type: WEB (Web Application)</p>
      <label>Target name<input name="name" required maxLength={200} defaultValue={target?.name??''}/></label>
      <label>Environment<select name="environment" defaultValue={target?.environment??'STAGING'}>{['LOCAL','DEVELOPMENT','STAGING','PRODUCTION','OTHER'].map(env=><option key={env}>{env}</option>)}</select></label>
      <label>Base URL<input name="base_url" type="url" required maxLength={2048} defaultValue={target?.configuration.base_url??''}/></label>
      <p className="hint">HTTP/HTTPS only; no embedded credentials, query or fragment. Saving never checks reachability or executes tests. Later changes do not alter saved Run Target snapshots.</p>
      <button disabled={action.error?.code==='HOST_AUTH_REQUIRED'} type="submit">{action.busy?'Saving Target…':target?'Save Target changes':'Create WEB Target'}</button>
    </fieldset>{action.error && <ErrorState error={action.error}/>}</form>;
}

export function CampaignTarget() {
  const {projectId:p,campaignId:c,campaign,transition}=useCampaign();
  const current=useResource(useCallback(()=>campaign.target_id?getCampaignTarget(p,c):Promise.resolve(null),[p,c,campaign.target_id]));
  const [choosing,setChoosing]=useState(false),[selected,setSelected]=useState('');
  const action=usePreparationAction<Awaited<ReturnType<typeof associateTarget>>>();
  return <section className="panel">{current.loading?<LoadingState>Loading Campaign Target…</LoadingState>:current.error?<ErrorState error={current.error}/>:<TargetSummary target={current.data}/>}
    <button disabled={action.busy} onClick={()=>{setSelected(campaign.target_id??'');setChoosing(!choosing);}}>Choose Campaign Target</button>
    {choosing && <form aria-label="Campaign Target selection" onSubmit={e=>{e.preventDefault();void action.run(()=>associateTarget(p,c,selected||null),async value=>{await transition(value);setChoosing(false);});}}>
      <fieldset disabled={action.busy}><TargetOptions projectId={p} value={selected} onChange={setSelected}/><button disabled={action.error?.code==='HOST_AUTH_REQUIRED'} type="submit">Save Campaign Target</button></fieldset>
    </form>}{action.error && <ErrorState error={action.error}/>}<Link to={`/projects/${encodeURIComponent(p)}/settings`}>Configure Project Targets</Link>
    <p className="hint">Association changes apply to future Runs only. Continue with Specification → Test Design → human approval → Execution → Results.</p>
  </section>;
}
