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

export interface DesignCriteria { search:string; status:string }
export interface DesignRow { test:CampaignTestSpecification; content_hash:string; approvable:boolean }
export interface DesignPage { items:DesignRow[]; total:number; page:number; page_size:number; total_pages:number }
export interface DesignSelection { criteria:DesignCriteria; ids?:string[]; expected_versions?:Record<string,string> }
export interface SelectionSummary { fingerprint:string; matched:number; eligible:number }
export const designPage = (p:string,c:string,criteria:DesignCriteria,page:number,size:number) => request<DesignPage>(`${campaignPath(p,c)}/test-design?${new URLSearchParams({search:criteria.search,status:criteria.status,page:String(page),page_size:String(size)})}`);
export const selectionSummary = (p:string,c:string,selection:DesignSelection) => request<SelectionSummary>(`${campaignPath(p,c)}/test-design/selection`,{method:'POST',body:JSON.stringify(selection)});
export const approveSelection = (p:string,c:string,selection:DesignSelection,fingerprint:string,reviewer_label:string) => request<{matched:number;approved:number;skipped:number}>(`${campaignPath(p,c)}/test-design/approval`,{method:'POST',body:JSON.stringify({selection,fingerprint,reviewer_label})});
export const exportRun = (p:string,c:string,run:string,format:'CSV'|'XLSX') => request<{filename:string;media_type:string;content_base64:string;count:number}>(`${campaignPath(p,c)}/runs/${encodeURIComponent(run)}/export?format=${format}`);
export function saveExport(result:{filename:string;media_type:string;content_base64:string}) {
  const bytes=Uint8Array.from(atob(result.content_base64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:result.media_type}));const link=document.createElement('a');
  try { link.href=url;link.download=result.filename;document.body.appendChild(link);link.click(); } finally { link.remove();setTimeout(()=>URL.revokeObjectURL(url),0); }
}
