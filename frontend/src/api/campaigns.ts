import { request } from './client';
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
