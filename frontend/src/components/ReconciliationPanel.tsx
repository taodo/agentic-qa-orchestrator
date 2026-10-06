import { reconciliationLabels, recoveryGuidance, type ReconciliationAssessment } from '../api/reconciliation';

export function ReconciliationPanel({ data, loading, error, refresh, disabled }: {
  data?: ReconciliationAssessment; loading: boolean; error: boolean; refresh: () => void; disabled: boolean;
}) {
  return <section className="panel reconciliation-panel" aria-label="Recovery / Reconciliation">
    <div className="panel-heading"><h2>Recovery / Reconciliation</h2><button type="button" disabled={disabled || loading} onClick={refresh}>Refresh reconciliation</button></div>
    <p className="muted">Derived safety guidance, separate from Task state. It does not prove exactly-once execution or resolve external effects. The backend checks again before Run or Resume.</p>
    {loading && <p role="status">Checking reconciliation…</p>}
    {error && <p role="alert">Reconciliation could not be verified. Refresh reconciliation before continuing.</p>}
    {data && <><p><strong>{reconciliationLabels[data.status]}</strong></p>
      {data.status === 'CLEAR' && <p>No unresolved crash evidence was found. Existing workflow gates still apply.</p>}
      {data.status === 'RECOVERABLE' && <p>Durable evidence permits existing recovery rules. Inspect Task state before explicitly continuing.</p>}
      {data.issues.length > 0 && <ul>{data.issues.map((issue, index) => <li key={`${issue.kind}-${index}`}><p>{recoveryGuidance[issue.kind]}</p>{issue.evidence_refs.length > 0 && <p className="muted">Evidence IDs: {issue.evidence_refs.join(', ')}</p>}</li>)}</ul>}
    </>}
  </section>;
}
