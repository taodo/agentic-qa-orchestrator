import { request } from './client';
import { campaignPath } from './campaigns';
import type { CollectionPage } from './types';
import type { CampaignView } from './campaignTypes';
export type TargetEnvironment = 'LOCAL'|'DEVELOPMENT'|'STAGING'|'PRODUCTION'|'OTHER';
export interface TargetInput { name:string;type:'WEB';environment:TargetEnvironment;configuration:{base_url:string} }
export interface Target extends TargetInput { id:string;project_id:string;created_at:string;updated_at:string }
export interface TargetSnapshot { schema_version:'web-target-snapshot-v1';target_id:string;project_id:string;name:string;type:'WEB';environment:TargetEnvironment;base_url:string }
const targetPath=(p:string,id?:string)=>`/projects/${encodeURIComponent(p)}/targets${id?'/'+encodeURIComponent(id):''}`;
export const listTargets=(p:string)=>request<CollectionPage<Target>>(targetPath(p)+'?limit=50');
export const createTarget=(p:string,body:TargetInput)=>request<Target>(targetPath(p),{method:'POST',body:JSON.stringify(body)});
export const updateTarget=(p:string,id:string,body:TargetInput)=>request<Target>(targetPath(p,id),{method:'PATCH',body:JSON.stringify(body)});
export const getCampaignTarget=(p:string,c:string)=>request<Target|null>(campaignPath(p,c)+'/target');
export const associateTarget=(p:string,c:string,target_id:string|null)=>request<CampaignView>(campaignPath(p,c)+'/target',{method:'PUT',body:JSON.stringify({target_id})});
