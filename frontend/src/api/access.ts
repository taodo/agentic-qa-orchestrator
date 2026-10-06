// Host access material lives only in memory. The HttpOnly session cookie is
// never read by JavaScript; this independent CSRF proof cannot authenticate.
type Access = { mode: 'hosted-demo'; csrf: string } | null;
let access: Access = null;
let expired = false;

export function hostedAccess() { return access !== null; }
export function csrfHeaders(method: string): Record<string, string> {
  return access && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase())
    ? { 'X-QA-Sentinel-CSRF': access.csrf } : {};
}
export function loginRecovery() {
  access = null;
  if (!expired) { expired = true; window.location.assign('/login'); }
}
export function accessExpired() { return expired; }

export async function initializeAccess() {
  access = null; expired = false;
  const response = await fetch('/auth/session', { cache: 'no-store', credentials: 'same-origin' });
  // Standalone API hosting and accepted non-session hosts remain usable.
  if (response.status === 404) return;
  // The development Vite fallback is HTML rather than a host projection.
  if (response.ok && response.headers.get('content-type')?.includes('text/html')) return;
  const data: unknown = await response.json();
  if (response.status === 401 && data && typeof data === 'object' && 'error' in data &&
    data.error && typeof data.error === 'object' && 'code' in data.error && data.error.code === 'HOST_AUTH_REQUIRED') {
    loginRecovery(); throw new Error('Hosted access required.');
  }
  if (!response.ok) throw new Error('Host access unavailable.');
  if (data && typeof data === 'object' && 'mode' in data && data.mode === 'hosted-demo') {
    if (!('csrf' in data) || typeof data.csrf !== 'string' || !/^[a-f0-9]{64}$/.test(data.csrf)) throw new Error('Host access unavailable.');
    access = { mode: 'hosted-demo', csrf: data.csrf };
  }
}

export async function logout() {
  if (!access) return;
  const response = await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin',
    headers: csrfHeaders('POST'), redirect: 'manual' });
  // Fetch hides same-origin redirect details in browsers. Only fixed recovery
  // navigation follows; the POST is never replayed.
  if (response.ok || response.status === 303 || response.type === 'opaqueredirect' || response.status === 401) loginRecovery();
  else throw new Error('Unable to sign out.');
}
