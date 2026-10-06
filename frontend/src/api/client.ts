import type { ApiErrorEnvelope } from './types';
import { accessExpired, csrfHeaders, loginRecovery } from './access';

export class ApiError extends Error {
  constructor(public readonly code: string, message: string, public readonly status?: number) { super(message); }
}

function isEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!value || typeof value !== 'object' || !('error' in value)) return false;
  const error = value.error;
  return !!error && typeof error === 'object' && 'code' in error && 'message' in error
    && typeof error.code === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(error.code)
    && typeof error.message === 'string' && error.message.length <= 500;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return requestPath<T>(`/api/v1${path}`, options);
}

// Explicit same-origin transport for the host namespace; API v1 stays unchanged.
export async function requestPath<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (accessExpired()) throw new ApiError('HOST_AUTH_REQUIRED', 'Sign in again to continue.', 401);
  let response: Response;
  try { response = await fetch(path, { ...options, credentials: 'same-origin', headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers, ...csrfHeaders(options.method ?? 'GET') } }); }
  catch { throw new ApiError('NETWORK_ERROR', 'Unable to reach QA Sentinel API.'); }
  let payload: unknown;
  try { payload = await response.json(); }
  catch { throw new ApiError('INVALID_RESPONSE', 'QA Sentinel API returned an unreadable response.', response.status); }
  if (!response.ok) {
    if (response.status === 401 && isEnvelope(payload) && payload.error.code === 'HOST_AUTH_REQUIRED') {
      loginRecovery();
      throw new ApiError('HOST_AUTH_REQUIRED', 'Sign in again to continue.', 401);
    }
    if (isEnvelope(payload)) throw new ApiError(payload.error.code, payload.error.message, response.status);
    throw new ApiError('HTTP_ERROR', 'QA Sentinel API could not complete the request.', response.status);
  }
  return payload as T;
}

export function publicError(value: unknown): ApiError {
  return value instanceof ApiError ? value : new ApiError('UNKNOWN_ERROR', 'Unable to complete this action.');
}
