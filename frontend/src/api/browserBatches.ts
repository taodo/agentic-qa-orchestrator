import { request } from './client';
import { campaignPath } from './campaigns';
import type { CollectionPage } from './types';
import type { QARun,RunEvidence } from './runTypes';
import type { TargetSnapshot } from './targets';
import type { CampaignTestSpecification,ReviewState } from './campaignTypes';
export type BrowserMode='HEADLESS'|'HEADED';
export interface BrowserBatchItem {id:string;test_id:string;position:number;key:string;title:string;preparation_status:string;outcome:string;reason:string|null;affected_step:number|null;hint:string|null;run_test_id:string|null;execution_status:string|null;qa_result:string|null;evidence_count:number|null;evidence:CollectionPage<RunEvidence>|null}
export interface BrowserBatch {id:string;project_id:string;campaign_id:string;status:string;browser_mode:BrowserMode;target_snapshot:TargetSnapshot;selected_count:number;summary:Record<string,number>;run:QARun|null;processing:boolean;reconciliation_required:boolean;interruption_acknowledged_at:string|null;duration_seconds:number|null;items:CollectionPage<BrowserBatchItem>}
export interface BrowserBatchHistory {id:string;status:string;browser_mode:BrowserMode;selected_count:number;created_at:string;run_id:string|null;execution_status:string|null;qa_outcome:string|null}
export const batchPath=(p:string,c:string,id?:string)=>campaignPath(p,c)+'/browser/batches'+(id?'/'+encodeURIComponent(id):'');
export const batchPagePath=(base:string,id:string)=>base+'/browser-batches/'+encodeURIComponent(id);
export const submitBrowserBatch=(p:string,c:string,body:{idempotency_key:string;test_specification_ids:string[];browser_mode:BrowserMode})=>request<BrowserBatch>(batchPath(p,c),{method:'POST',body:JSON.stringify(body)});
export const getBrowserBatch=(p:string,c:string,id:string,after=0,signal?:AbortSignal)=>request<BrowserBatch>(batchPath(p,c,id)+'?limit=50&after_position='+after,{signal});
export const listBrowserBatches=(p:string,c:string)=>request<CollectionPage<BrowserBatchHistory>>(batchPath(p,c)+'?limit=20');
export const acknowledgeBrowserBatch=(p:string,c:string,id:string)=>request<BrowserBatch>(batchPath(p,c,id)+'/acknowledge-interruption',{method:'POST',body:'{}'});
export const reviewBrowserTest=(p:string,c:string,id:string,body:{reviewer_label?:string;note?:string;previous_hash?:string;approval_provenance?:'LOCAL_OPERATOR'})=>request<ReviewState>(campaignPath(p,c)+'/browser/tests/'+encodeURIComponent(id)+'/review',{method:'POST',body:JSON.stringify(body)});
export const approveBrowserTests=(p:string,c:string,test_ids:string[],expected_hashes:Record<string,string>,reviewer_label?:string)=>request<{matched:number;approved:number;skipped:number}>(campaignPath(p,c)+'/browser/tests/approve-selection',{method:'POST',body:JSON.stringify({test_ids,expected_hashes,...(reviewer_label?{reviewer_label}:{approval_provenance:'LOCAL_OPERATOR'})})});
export function browserReviewable(test:CampaignTestSpecification) {
 return !test.unresolved_requirement_refs.length && test.information_markers.every(marker=>marker.kind==='MISSING_TRACEABILITY') && (!test.information_markers.length || !test.requirement_ids.length) && !!test.required_evidence.length && test.overall_expected_result!==null && test.steps.every(step=>step.expected!==null);
}
export const browserExecutable=(test:CampaignTestSpecification)=>test.review_status==='APPROVED' && browserReviewable(test);

export const approveLocalFinding=(p:string,c:string,id:string)=>request<ReviewState>(campaignPath(p,c)+'/browser/requirements/'+encodeURIComponent(id)+'/review',{method:'POST',body:JSON.stringify({approval_provenance:'LOCAL_OPERATOR'})});

export const approveLocalTest=(p:string,c:string,id:string)=>request<ReviewState>(campaignPath(p,c)+'/browser/tests/'+encodeURIComponent(id)+'/operator-review',{method:'POST',body:JSON.stringify({approval_provenance:'LOCAL_OPERATOR'})});
export const approveLocalDesignSelection=(p:string,c:string,selection:import('./productV2').DesignSelection,fingerprint:string)=>request<{matched:number;approved:number;skipped:number}>(campaignPath(p,c)+'/browser/test-design/approval',{method:'POST',body:JSON.stringify({selection,fingerprint,approval_provenance:'LOCAL_OPERATOR'})});
