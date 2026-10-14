import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { CampaignRequirement } from '../api/campaignTypes';
import { reviewRequirement, reviewTest } from '../api/campaigns';
import { approveLocalFinding, approveLocalTest, reviewBrowserTest } from '../api/browserBatches';
import { publicError } from '../api/client';
import { usePreparationAction } from '../app/usePreparationAction';
import type { PreparationScope } from './PreparationSources';
import { ErrorState } from './Feedback';

export function RequirementBulkApproval({rows,...scope}:PreparationScope & {rows:CampaignRequirement[];selected:string[];localOperator?:boolean}) {
  return <PreparationBulkApproval {...scope} kind="Requirement" rows={rows.map(row=>({id:row.id,key:row.key,eligible:row.review_status==='READY_FOR_REVIEW' && !row.information_markers.length}))}/>;
}

export function PreparationBulkApproval({ rows, selected, changed, projectId, campaignId, kind, compact=false, localOperator=false, sourceFree=false }: PreparationScope & {
  rows:{id:string;key:string;eligible:boolean}[];selected:string[];kind:'Requirement'|'Test Case';compact?:boolean;localOperator?:boolean;sourceFree?:boolean;
}) {
  const plural=kind==='Requirement'?'Requirements':'Test Cases';
  const action = usePreparationAction<string[]>(), active = useRef(true);
  const [progress,setProgress] = useState(''), [validation,setValidation] = useState('');
  useEffect(() => { active.current=true; return () => { active.current=false; }; }, []);
  const eligible=rows.filter(row => selected.includes(row.id) && row.eligible);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (action.busy) return; const data=new FormData(event.currentTarget);
    const reviewer_label=String(data.get('reviewer_label') || ''), note=String(data.get('note') || '');
    if (!localOperator && (!/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(reviewer_label) || Array.from(note).length>1000)) { setValidation('Use a valid reviewer label (1–64 characters) and a note up to 1,000 characters.'); return; }
    if (!eligible.length) return;
    setValidation(''); const batch=[...eligible];
    await action.run(async () => {
      const results: string[]=[];
      for (const [index,row] of batch.entries()) {
        if (!active.current) break;
        setProgress(`Recording approval ${index+1} of ${batch.length}…`);
        try {
          if(localOperator){
            if(kind==='Requirement')await approveLocalFinding(projectId,campaignId,row.id);
            else if(sourceFree)await reviewBrowserTest(projectId,campaignId,row.id,{approval_provenance:'LOCAL_OPERATOR'});
            else await approveLocalTest(projectId,campaignId,row.id);
          }else if(sourceFree && kind==='Test Case')await reviewBrowserTest(projectId,campaignId,row.id,{reviewer_label,...(note?{note}:{})});
          else await (kind==='Requirement'?reviewRequirement:reviewTest)(projectId,campaignId,row.id,{action:'APPROVE',reviewer_label,...(note?{note}:{})});
          results.push(`${row.key}: Approval recorded.`);
        }
        catch (error) {
          const safe=publicError(error); results.push(`${row.key}: ${safe.code}. Approval was not confirmed.`);
          if (safe.status===401 || safe.status===403) { results.push(`Stopped after authorization failure. ${batch.length-index-1} remaining requests were not attempted.`); break; }
        }
      }
      if (active.current) setProgress('Bulk approval finished. Review each result below; nothing retries automatically.');
      return results;
    });
    if (active.current) await changed();
  }
  const form = <form aria-label={`Bulk approve ${plural}`} onSubmit={submit}><fieldset disabled={action.busy}>
    <legend>Bulk approval — {eligible.length} eligible selected {plural}</legend>
    <p className="hint">{sourceFree && kind==='Test Case'?'Only selected current Tests with complete information are submitted. Missing Specification/Requirement links are allowed for configured browser tests.':'Only selected current Ready-for-review rows without clarification markers are submitted.'} Other selected rows are ignored. Approval never runs tests.{!localOperator && ' Reviewer labels are operator assertions; never enter secrets.'}</p>
    {localOperator ? <p>Confirm as the local operator. The receipt records this explicit human action, without claiming an authenticated personal identity.</p> : <><label>Bulk reviewer label<input name="reviewer_label" required maxLength={64}/></label>
    <label>Bulk review note (optional)<input name="note" maxLength={1000}/></label></>}
    <button disabled={!eligible.length} type="submit">{action.busy ? 'Recording approvals…' : compact ? 'Confirm approval' : `Approve selected ${plural}`}</button>
    </fieldset><p role="status">{validation || progress}</p>{action.result && <ul aria-label="Bulk approval results">{action.result.map((result,i)=><li key={i}>{result}</li>)}</ul>}{action.error && <ErrorState error={action.error}/>}</form>;
  return compact ? <details className="preparation-action">
    <summary>Approve selected {plural} ({eligible.length} eligible)</summary>{form}
  </details> : form;
}
