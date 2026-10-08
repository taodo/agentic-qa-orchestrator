import { request } from './client';
import type { CampaignSource, RequirementExtraction, TestImport, TestGeneration, ApprovalCommand, ReviewState, PreparationStatus } from './campaignTypes';
import type { CollectionPage } from './types';
import type { CampaignView, CampaignRequirement, CampaignTestSpecification, CampaignTraceability, CampaignReadiness } from './campaignTypes';

export const campaignPath = (projectId: string, campaignId?: string) =>
  `/projects/${encodeURIComponent(projectId)}/campaigns${campaignId === undefined ? '' : '/' + encodeURIComponent(campaignId)}`;
export const listCampaigns = (projectId: string) => request<CollectionPage<CampaignView>>(`${campaignPath(projectId)}?limit=50`);
export const createCampaign = (projectId: string, body: { name: string; objective?: string }) =>
  request<CampaignView>(campaignPath(projectId), { method: 'POST', body: JSON.stringify(body) });
export const getCampaign = (projectId: string, campaignId: string) => request<CampaignView>(campaignPath(projectId, campaignId));
export const listRequirements = (projectId: string, campaignId: string) => request<CollectionPage<CampaignRequirement>>(`${campaignPath(projectId, campaignId)}/requirements?limit=50`);
export const listTestSpecifications = (projectId: string, campaignId: string) => request<CollectionPage<CampaignTestSpecification>>(`${campaignPath(projectId, campaignId)}/test-specifications?limit=50`);
export const getTraceability = (projectId: string, campaignId: string) => request<CampaignTraceability>(`${campaignPath(projectId, campaignId)}/traceability?limit=50`);
export const getReadiness = (projectId: string, campaignId: string) => request<CampaignReadiness>(`${campaignPath(projectId, campaignId)}/readiness`);

export const getRequirement = (projectId: string, campaignId: string, requirementId: string) =>
  request<CampaignRequirement>(`${campaignPath(projectId, campaignId)}/requirements/${encodeURIComponent(requirementId)}`);
export const getTestSpecification = (projectId: string, campaignId: string, testId: string) =>
  request<CampaignTestSpecification>(`${campaignPath(projectId, campaignId)}/test-specifications/${encodeURIComponent(testId)}`);

export const listSources = (p: string, c: string) => request<CollectionPage<CampaignSource>>(`${campaignPath(p, c)}/sources?limit=50`);
export const ingestSource = (p: string, c: string, body: { name: string; source_type: 'TEXT' | 'MARKDOWN'; content: string }) =>
  request<CampaignSource>(`${campaignPath(p, c)}/sources`, { method: 'POST', body: JSON.stringify(body) });
export const extractRequirements = (p: string, c: string, sourceId: string) =>
  request<RequirementExtraction>(`${campaignPath(p, c)}/sources/${encodeURIComponent(sourceId)}/extract-requirements`, { method: 'POST', body: '{}' });
export const importTests = (p: string, c: string, body: { name: string; format: 'CSV' | 'MARKDOWN'; content: string }) =>
  request<TestImport>(`${campaignPath(p, c)}/test-imports`, { method: 'POST', body: JSON.stringify(body) });
export const generateTests = (p: string, c: string, requirementIds: string[]) =>
  request<TestGeneration>(`${campaignPath(p, c)}/generate-tests`, { method: 'POST', body: JSON.stringify({ requirement_ids: requirementIds }) });
export const reviewRequirement = (p: string, c: string, id: string, body: ApprovalCommand) =>
  request<ReviewState>(`${campaignPath(p, c)}/requirements/${encodeURIComponent(id)}/review`, { method: 'POST', body: JSON.stringify(body) });
export const reviewTest = (p: string, c: string, id: string, body: ApprovalCommand) =>
  request<ReviewState>(`${campaignPath(p, c)}/test-specifications/${encodeURIComponent(id)}/review`, { method: 'POST', body: JSON.stringify(body) });
export const getRequirementReview = (p: string, c: string, id: string) => request<ReviewState>(`${campaignPath(p, c)}/requirements/${encodeURIComponent(id)}/review`);
export const getTestReview = (p: string, c: string, id: string) => request<ReviewState>(`${campaignPath(p, c)}/test-specifications/${encodeURIComponent(id)}/review`);
export const transitionCampaign = (p: string, c: string, status: Exclude<PreparationStatus, 'DRAFT'>) =>
  request<CampaignView>(`${campaignPath(p, c)}/transitions`, { method: 'POST', body: JSON.stringify({ status }) });

export const retryExtraction = (p:string,c:string,id:string) => request<RequirementExtraction>(`${campaignPath(p,c)}/extractions/${encodeURIComponent(id)}/retry`,{method:'POST',body:'{}'});
export const listExtractionHistory = (p:string,c:string,id:string) => request<CollectionPage<RequirementExtraction>>(`${campaignPath(p,c)}/sources/${encodeURIComponent(id)}/extractions?limit=50`);
export const addClarification = (p:string,c:string,id:string,body:{request_key:string;content:string}) => request<import('./campaignTypes').Clarification>(`${campaignPath(p,c)}/requirements/${encodeURIComponent(id)}/clarifications`,{method:'POST',body:JSON.stringify(body)});
export const getRequirementHistory = (p:string,c:string,id:string) => request<CollectionPage<import('./campaignTypes').RequirementHistoryEntry>>(`${campaignPath(p,c)}/requirements/${encodeURIComponent(id)}/history`);

export const listGenerations = (p:string,c:string) => request<CollectionPage<TestGeneration>>(`${campaignPath(p,c)}/test-generations?limit=50`);
