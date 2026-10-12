import { createContext, useContext, useLayoutEffect, type Dispatch, type SetStateAction } from 'react';

export interface WorkspaceContextValue {
  projectId: string;
  campaignId?: string;
  campaignName?: string;
  target?: {name:string;type:string;environment:string};
}
export const WorkspaceContext = createContext<Dispatch<SetStateAction<WorkspaceContextValue | undefined>> | undefined>(undefined);

// Publish already-loaded context to the shell; navigation never adds data requests.
export function useWorkspaceContext(projectId: string, campaignId?: string, campaignName?: string) {
  const setContext = useContext(WorkspaceContext);
  useLayoutEffect(() => {
    setContext?.({ projectId, campaignId, campaignName });
    return () => setContext?.(undefined);
  }, [setContext, projectId, campaignId, campaignName]);
}

// Optional shell decoration uses the already-loaded live Campaign Target only.
// Run views continue to use immutable Run snapshots; this hook adds no reads.
export function useTargetContext(projectId:string,campaignId:string,target:WorkspaceContextValue['target']) {
  const publish=useContext(WorkspaceContext);
  useLayoutEffect(()=>{
    publish?.(current=>current?.projectId===projectId && current.campaignId===campaignId?{...current,target}:current);
  },[publish,projectId,campaignId,target]);
}
