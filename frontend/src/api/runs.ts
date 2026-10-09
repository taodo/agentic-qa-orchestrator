import { request } from './client';
import { campaignPath } from './campaigns';
import type { CollectionPage } from './types';
import type { QARun, RunRequirement, RunTest, RunResults, RunEvidence } from './runTypes';
export const runsPath = (p: string, c: string, id?: string) => `${campaignPath(p,c)}/runs${id === undefined ? '' : '/'+encodeURIComponent(id)}`;
export const listRuns = (p: string,c: string) => request<CollectionPage<QARun>>(`${runsPath(p,c)}?limit=50`);
export const createRun = (p: string,c: string, body: { idempotency_key: string; note?: string }) => request<QARun>(runsPath(p,c),{method:'POST',body:JSON.stringify(body)});
export const getRun = (p: string,c: string,id: string) => request<QARun>(runsPath(p,c,id));
export const startRun = (p: string,c: string,id: string) => request<QARun>(`${runsPath(p,c,id)}/start`,{method:'POST',body:'{}'});
export const listRunTests = (p: string,c: string,id: string,after=0) => request<CollectionPage<RunTest>>(`${runsPath(p,c,id)}/tests?limit=50&after_position=${after}`);
export const listRunRequirements = (p: string,c: string,id: string,after=0) => request<CollectionPage<RunRequirement>>(`${runsPath(p,c,id)}/requirements?limit=50&after_position=${after}`);

export const getRunResults = (p:string,c:string,id:string,after=0) => request<RunResults>(`${runsPath(p,c,id)}/results?limit=50&after_position=${after}`);
export const getRunTestEvidence = (p:string,c:string,id:string,testId:string) => request<CollectionPage<RunEvidence>>(`${runsPath(p,c,id)}/tests/${encodeURIComponent(testId)}/evidence?limit=20`);
