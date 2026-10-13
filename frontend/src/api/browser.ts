import { request } from './client';
import { campaignPath } from './campaigns';
import type { CampaignTestSpecification } from './campaignTypes';
import type { QARun } from './runTypes';
import type { TargetSnapshot } from './targets';
import type { CollectionPage } from './types';
export type BrowserOperation='NAVIGATE'|'CLICK'|'FILL'|'SELECT'|'CHECK'|'PRESS'|'WAIT_FOR';
export type LocatorStrategy='ROLE'|'LABEL'|'TEXT'|'TEST_ID'|'PLACEHOLDER'|'CSS';
export interface BrowserLocator {strategy:LocatorStrategy;value?:string;role?:string;name?:string|null;exact?:boolean}
export interface BrowserFacts {contract_version:'browser-facts-v1';required_actions:BrowserOperation[][];locators:BrowserLocator[];paths:string[];input_values:string[]}
export interface BrowserCapability {planning:'AVAILABLE'|'UNAVAILABLE';execution:'AVAILABLE'|'UNAVAILABLE'}
export interface BrowserReadiness {status:'AVAILABLE'|'TARGET_NOT_WEB'|'TEST_NOT_APPROVED'|'FACTS_MISSING'|'FACTS_INVALID'|'POLICY_REJECTED'|'PROVIDER_UNAVAILABLE';test_id:string;target:TargetSnapshot|null}
export interface BrowserStep {action:string;timeout_ms:number;path?:string;locator?:BrowserLocator;value?:string;key?:string;checked?:boolean;condition?:string;text?:string;exact?:boolean;visible?:boolean}
export interface BrowserCandidate {id:string;test_id:string;test_key:string;test_title:string;target:TargetSnapshot;test_hash:string;target_hash:string;origin:'AI';prompt_version:string;status:'STARTED'|'SUCCEEDED'|'FAILED';error_code:string|null;configured_model:string;provider_model:string|null;input_tokens:number|null;output_tokens:number|null;reasoning_tokens:number|null;total_tokens:number|null;plan_hash:string|null;accepted_run_id:string|null;
 output:{disposition:'CANDIDATE';plan:{version:string;steps:BrowserStep[];test_timeout_ms:number;redirect_limit:number;screenshot_limit:number;evidence_limit:number};step_bindings:number[];unable_reason:null}|null}
const path=(p:string,c:string)=>campaignPath(p,c)+'/browser';
const post=(body:unknown)=>({method:'POST',body:JSON.stringify(body)});
export const browserCapability=(p:string,c:string)=>request<BrowserCapability>(path(p,c)+'/capability');
export const browserReadiness=(p:string,c:string,t:string)=>request<BrowserReadiness>(path(p,c)+'/tests/'+encodeURIComponent(t)+'/readiness');
export const saveBrowserFacts=(p:string,c:string,t:string,body:{facts:BrowserFacts;non_secret:true;previous_hash:string;reviewer_label:string;note:string})=>request<CampaignTestSpecification>(path(p,c)+'/tests/'+encodeURIComponent(t)+'/facts',post(body));
export const generateBrowserPlan=(p:string,c:string,t:string)=>request<BrowserCandidate>(path(p,c)+'/tests/'+encodeURIComponent(t)+'/generate',post({}));
export const browserHistory=(p:string,c:string)=>request<CollectionPage<Omit<BrowserCandidate,'output'>>>(path(p,c)+'/generations');
export const getBrowserCandidate=(p:string,c:string,id:string)=>request<BrowserCandidate>(path(p,c)+'/generations/'+encodeURIComponent(id));
export const acceptBrowserPlan=(p:string,c:string,id:string,idempotency_key:string)=>request<QARun>(path(p,c)+'/generations/'+encodeURIComponent(id)+'/accept',post({idempotency_key}));
export const startBrowserRun=(p:string,c:string,id:string)=>request<QARun>(path(p,c)+'/runs/'+encodeURIComponent(id)+'/start',post({}));
export function existingFacts(test:CampaignTestSpecification):BrowserFacts|undefined {
  for(const text of test.preconditions){try{const value=JSON.parse(text);if(value?.contract_version==='browser-facts-v1')return value;}catch{/* Ordinary inert precondition. */}}
}

export function isReservedBrowserFacts(text:string):boolean {
  try{const value=JSON.parse(text);return value!==null && typeof value==='object' && !Array.isArray(value) && value.contract_version==='browser-facts-v1';}catch{return false;}
}
