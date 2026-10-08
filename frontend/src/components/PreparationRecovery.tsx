import { useId, useState } from 'react';
import { addClarification, getRequirementHistory } from '../api/campaigns';
import type { CampaignRequirement } from '../api/campaignTypes';
import { usePreparationAction } from '../app/usePreparationAction';
import { SourceExtraction, textBytes, type PreparationScope } from './PreparationSources';
import { ErrorState } from './Feedback';

export function PreparationRecovery({requirement,projectId,campaignId,changed}:{requirement:CampaignRequirement}&PreparationScope) {
  const history=usePreparationAction<Awaited<ReturnType<typeof getRequirementHistory>>>();
  const action=usePreparationAction<Awaited<ReturnType<typeof addClarification>>>();
  const [open,setOpen]=useState(false),[content,setContent]=useState(''),[validation,setValidation]=useState('');
  const [intent,setIntent]=useState<{request_key:string;content:string}>();
  const id=useId();
  const current=history.result?.items.find(item=>item.requirement.id===requirement.id)?.is_current;
  return <div className="preparation-action">
    <button disabled={history.busy} onClick={()=>void history.run(()=>getRequirementHistory(projectId,campaignId,requirement.id))}>{history.busy?'Loading Requirement history…':'View Requirement version history'}</button>
    {history.error && <ErrorState error={history.error}/>}
    {history.result && <section><h4>Requirement version history</h4>{history.result.items.map(item=><article key={item.requirement.id} className="evidence-record"><h5>Version {item.version} — {item.is_current?'Current Requirement':'Superseded Requirement'}</h5><p>{item.requirement.id} · {item.requirement.logical_key} · {item.requirement.review_status}</p><p>{item.requirement.title}: {item.requirement.description}</p>{item.requirement.source_references.map((ref,i)=><blockquote key={i}>Source {ref.source_id}, lines {ref.start_line}–{ref.end_line}: {ref.excerpt}</blockquote>)}</article>)}</section>}
    {requirement.review_status==='NEEDS_CLARIFICATION' && current!==false && <>
      <button disabled={action.busy} onClick={()=>setOpen(!open)}>Add Clarification / Provide Missing Information</button>
      {open && <form aria-label="Provide missing information" onSubmit={event=>{event.preventDefault();if(!content.trim() || textBytes(content)>4000){setValidation('Provide non-empty missing facts up to 4,000 UTF-8 bytes.');return;}setValidation('');void action.run(()=>{
        const body=intent ?? {request_key:crypto.randomUUID(),content};setIntent(body);return addClarification(projectId,campaignId,requirement.id,body);
      });}}><p>Missing facts become inert source evidence. Adding clarification never calls a model or approves content. Explicit revision creates a new Requirement identity, requires review again and retires tests linked to the previous version from current coverage. Import/generate and review replacement tests.</p>
        <label htmlFor={id}>Missing facts (no credentials or secrets)</label><textarea id={id} maxLength={4000} value={content} disabled={action.busy || !!intent} onChange={e=>setContent(e.target.value)}/>
        <button disabled={action.busy || !!action.result || action.error?.code==='HOST_AUTH_REQUIRED'}>{action.busy?'Saving clarification…':intent?'Retry Save Clarification':'Save Clarification'}</button>
        {action.error && <><ErrorState error={action.error}/><p>Explicit retry retains the same key and facts. Nothing retries automatically.</p><button type="button" disabled={action.busy} onClick={()=>{setIntent(undefined);setContent('');}}>New clarification request</button></>}
        {validation && <p role="status">{validation}</p>}
      </form>}
      {action.result && <><p role="status">Clarification saved. Source: {action.result.source_id}. Revision remains explicit and may consume tokens.</p><SourceExtraction source={{id:action.result.source_id,name:'Clarification addendum'}} projectId={projectId} campaignId={campaignId} changed={changed} initialLabel="Revise Requirement"/></>}
    </>}
    {current===false && <p className="notice">Historical content cannot be revised or approved. Use the current Requirement version.</p>}
  </div>;
}
