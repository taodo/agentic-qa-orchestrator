import { useCallback, useEffect, type ReactNode } from 'react';
import type { CollectionPage } from '../api/types';
import { useResource } from '../app/useResource';
import { EmptyState, ErrorState, LoadingState, TruncationNotice } from './Feedback';

export type RefreshRegistry = (key: string, refresh: () => Promise<void>) => () => void;
export function EvidencePanel<T extends { id: string }>({ taskId, name, panelKey, load, render, register, busy }: {
  taskId: string; name: string; panelKey: string;
  load: (id: string) => Promise<CollectionPage<T>>; render: (item: T) => ReactNode;
  register: RefreshRegistry; busy: boolean;
}) {
  const resource = useResource(useCallback(() => load(taskId), [load, taskId]));
  useEffect(() => register(panelKey, resource.reload), [register, panelKey, resource.reload]);
  return <section className="panel" aria-label={name}>
    <div className="panel-heading"><h2>{name}</h2><button type="button" disabled={busy || resource.loading} onClick={() => void resource.reload()}>Refresh {name}</button></div>
    {resource.loading && <LoadingState>{`Loading ${name}…`}</LoadingState>}
    {resource.error && <ErrorState error={resource.error} retry={busy || resource.loading ? undefined : () => void resource.reload()} />}
    {resource.data && <>{!resource.data.items.length ? <EmptyState>{`No persisted ${name.toLowerCase()} yet.`}</EmptyState> :
      <ul className="evidence-list" aria-label={`${name} records`}>{resource.data.items.map(item => <li className="evidence-record" key={item.id}>{render(item)}</li>)}</ul>}
      <TruncationNotice truncated={resource.data.truncated} /></>}
  </section>;
}
