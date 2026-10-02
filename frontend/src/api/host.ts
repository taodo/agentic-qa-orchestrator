import { ApiError, requestPath } from './client';

export interface RuntimeStatus {
  mode: 'local' | 'demo' | 'preview-demo';
  project_id: string;
  runtime_configured: boolean;
  model_ready: boolean | null;
  test_targets_configured: boolean;
}

export async function getRuntimeStatus(projectId: string): Promise<RuntimeStatus> {
  const data = await requestPath<unknown>(`/host/runtime-status/${encodeURIComponent(projectId)}`);
  if (!data || typeof data !== 'object') throw new ApiError('HOST_STATUS_UNAVAILABLE', 'Runtime status unavailable.');
  const value = data as Record<string, unknown>;
  if (typeof value.mode !== 'string' || !['local', 'demo', 'preview-demo'].includes(value.mode) || value.project_id !== projectId ||
    typeof value.runtime_configured !== 'boolean' || typeof value.test_targets_configured !== 'boolean' ||
    !(value.model_ready === null || typeof value.model_ready === 'boolean')) {
    throw new ApiError('HOST_STATUS_UNAVAILABLE', 'Runtime status unavailable.');
  }
  // Select only display fields, never retain/render arbitrary provider/config data.
  return { mode: value.mode as RuntimeStatus['mode'], project_id: projectId,
    runtime_configured: value.runtime_configured, model_ready: value.model_ready,
    test_targets_configured: value.test_targets_configured };
}
