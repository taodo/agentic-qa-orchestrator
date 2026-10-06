import { useId, useState } from 'react';
import type { JsonValue } from '../api/types';

export function JsonContent({ value }: { value: JsonValue }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  // This is the approved public artifact content, rendered only as escaped text.
  const json = JSON.stringify(value, null, 2);
  return <div className="json-content">
    <button type="button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(!expanded)}>{expanded ? 'Collapse JSON' : 'Expand JSON'}</button>
    <pre id={id} className={`event-details ${expanded ? 'expanded-json' : 'json-preview'}`}>{expanded ? json : json.slice(0, 240)}{!expanded && json.length > 240 ? '\n… Expand to inspect the complete JSON structure.' : ''}</pre>
  </div>;
}
