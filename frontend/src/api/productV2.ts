import { request } from './client';
import { campaignPath } from './campaigns';
import type { CampaignSource, CampaignTestSpecification } from './campaignTypes';
import type { CollectionPage } from './types';
export interface ExecutionCandidate { test: CampaignTestSpecification; content_hash: string; eligible: boolean; reason: string | null }
export const candidates = (p:string,c:string,after='00000000-0000-0000-0000-000000000000') => request<CollectionPage<ExecutionCandidate>>(`${campaignPath(p,c)}/execution-candidates?limit=50&after_id=${encodeURIComponent(after)}`);
export const uploadDocument = (p:string,c:string,name:string,content_base64:string) => request<CampaignSource>(`${campaignPath(p,c)}/documents`,{method:'POST',body:JSON.stringify({name,content_base64})});
export const editTest = (p:string,c:string,id:string,body:{previous_hash:string;reviewer_label:string;note:string;design:Pick<CampaignTestSpecification,'key'|'title'|'test_type'|'priority'|'preconditions'|'steps'|'overall_expected_result'|'required_evidence'|'information_markers'>}) => request<CampaignTestSpecification>(`${campaignPath(p,c)}/test-specifications/${encodeURIComponent(id)}/edits`,{method:'POST',body:JSON.stringify(body)});
export const exportTests = (p:string,c:string,ids:string[],format:'CSV'|'XLSX') => request<{filename:string;media_type:string;content_base64:string;count:number}>(`${campaignPath(p,c)}/test-exports`,{method:'POST',body:JSON.stringify({test_specification_ids:ids,format})});

export const testEditEvidence = (p:string,c:string,id:string) => request<{id:string;previous_id:string;source_id:string;version:number;reviewer_label:string;note:string;created_at:string}|null>(`${campaignPath(p,c)}/test-specifications/${encodeURIComponent(id)}/edit-evidence`);

export const listSpecifications = (p:string,c:string) => request<CollectionPage<CampaignSource>>(`${campaignPath(p,c)}/sources?limit=50&purpose=SPECIFICATION`);
