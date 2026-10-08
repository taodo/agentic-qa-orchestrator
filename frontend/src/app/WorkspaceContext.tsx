import { createContext, useContext, useLayoutEffect, type Dispatch, type SetStateAction } from 'react';

export interface WorkspaceContextValue {
  projectId: string;
  campaignId?: string;
  campaignName?: string;
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
