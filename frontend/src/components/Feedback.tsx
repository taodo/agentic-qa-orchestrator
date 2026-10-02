import type { ApiError } from '../api/client';
export function LoadingState({ children = 'Loading…' }: { children?: string }) { return <p role="status" className="feedback">{children}</p>; }
export function EmptyState({ children }: { children: string }) { return <p role="status" className="feedback empty">{children}</p>; }
export function ErrorState({ error, retry }: { error: ApiError; retry?: () => void }) {
  return <div role="alert" className="error"><strong>{error.code}</strong><p>{error.message}</p>{retry && <button type="button" onClick={retry}>Retry</button>}</div>;
}
export function TruncationNotice({ truncated }: { truncated: boolean }) { return truncated ? <p className="muted">Showing a bounded collection. Additional records are not included.</p> : null; }
