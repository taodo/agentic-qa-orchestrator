import type { RunEvidence } from '../api/runTypes';
import { DateTime } from './DateTime';

// Generic UI consumes a bounded server policy projection, never executor payload fields.
export function RunEvidenceRecord({record}:{record:Omit<RunEvidence,'payload'>}) {
  return <li className="evidence-record">
    <strong>{record.presentation.display_label}</strong><p className="prose">{record.summary}</p>
    <dl className="metadata"><div><dt>Source</dt><dd>{record.source}</dd></div><div><dt>Kind</dt><dd>{record.kind}</dd></div>
      {record.presentation.details.map(detail=><div key={detail.label}><dt>{detail.label}</dt><dd>{detail.value}</dd></div>)}
      <div><dt>Recorded by host</dt><dd><DateTime value={record.recorded_at}/></dd></div>
      <div><dt>Evidence order</dt><dd>{record.sequence}</dd></div></dl>
    <details><summary>Evidence audit identity</summary><p>{record.id} · {record.schema_version} · {record.presentation.variant}</p></details>
  </li>;
}
