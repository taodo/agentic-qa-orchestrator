import type { CollectionPage, TimelineEntry } from '../api/types';
import { DateTime } from './DateTime';
import { EmptyState, TruncationNotice } from './Feedback';
export function Timeline({ page }: { page: CollectionPage<TimelineEntry> }) {
  return <>{!page.items.length ? <EmptyState>No persisted events yet.</EmptyState> : <ol className="timeline" aria-label="Task timeline">
    {page.items.map(entry => <li key={entry.event_id}><div className="event-heading"><strong>{entry.event_type}</strong><DateTime value={entry.timestamp} /></div>
      {entry.summary !== entry.event_type && <p>{entry.summary}</p>}
      <p className="muted">{entry.actor.type} · {entry.actor.id}{entry.timestamp_tied && ' · Timestamp tie: persisted insertion order'}</p>
      {entry.details !== null && <pre className="event-details">{JSON.stringify(entry.details, null, 2)}</pre>}
    </li>)}
  </ol>}<TruncationNotice truncated={page.truncated} /></>;
}
