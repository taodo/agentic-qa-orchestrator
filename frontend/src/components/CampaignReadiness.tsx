import { Link } from 'react-router-dom';
import type { CampaignReadiness as Readiness, ReadinessBlocker } from '../api/campaignTypes';
import { Metric } from './WorkspaceUI';
import { CampaignStatusBadge } from './CampaignStatusBadge';

const blockers: Record<ReadinessBlocker, { text: string; area: '' | 'requirements' | 'test-specifications' | 'traceability' }> = {
  CAMPAIGN_NOT_APPROVED: { text: 'Campaign preparation has not been approved.', area: '' },
  NO_REQUIREMENTS: { text: 'No Requirements have been prepared. Add a specification and extract Requirements.', area: 'requirements' },
  REQUIREMENTS_NOT_APPROVED: { text: 'One or more Requirements still need approval.', area: 'requirements' },
  REQUIREMENTS_NEED_CLARIFICATION: { text: 'One or more Requirements need clarification.', area: 'requirements' },
  NO_TEST_SPECIFICATIONS: { text: 'No Test Cases have been prepared. Import existing tests or generate tests.', area: 'test-specifications' },
  REQUIREMENT_COVERAGE_GAP: { text: 'One or more Requirements do not have approved test coverage. Inspect Traceability and prepare approved tests.', area: 'traceability' },
  INVALID_REQUIREMENT_APPROVAL: { text: 'Stored Requirement approval evidence is inconsistent; operator attention is required.', area: 'requirements' },
  INVALID_TEST_APPROVAL: { text: 'Stored Test Case approval evidence is inconsistent; operator attention is required.', area: 'test-specifications' },
};

export function PreparationNextStep({ value, base }: { value: Readiness; base: string }) {
  // Navigation guidance only. The backend status and blocker codes remain authoritative.
  const priorities: ReadinessBlocker[] = ['INVALID_REQUIREMENT_APPROVAL', 'INVALID_TEST_APPROVAL',
    'NO_REQUIREMENTS', 'REQUIREMENTS_NEED_CLARIFICATION', 'REQUIREMENTS_NOT_APPROVED',
    'NO_TEST_SPECIFICATIONS', 'REQUIREMENT_COVERAGE_GAP', 'CAMPAIGN_NOT_APPROVED'];
  const code = priorities.find(item => value.blocker_codes.includes(item));
  const item = code ? blockers[code] : undefined;
  const ready = value.status === 'READY';
  return <section className="next-step" aria-label="Next preparation action">
    <div><p className="eyebrow">NEXT STEP</p><h3>{ready ? 'Preparation is ready for a QA Run' : 'Continue preparation'}</h3>
      <p>{ready ? 'Capture approved preparation in an immutable snapshot. Execution is a separate, explicitly synthetic action.' : item ? `Next: ${item.text}` : 'Inspect the saved readiness assessment before progressing.'}</p></div>
    <Link className="button button--primary" to={ready ? `${base}/runs` : item?.area ? `${base}/${item.area}` : base}>
      {ready ? 'Open Runs' : item?.area === 'requirements' ? 'Continue Requirements' : item?.area === 'test-specifications' ? 'Continue Test Cases' : item?.area === 'traceability' ? 'Review coverage' : 'Review Campaign preparation'}
    </Link>
  </section>;
}

const checks: { label: string; codes: ReadinessBlocker[] }[] = [
  { label: 'Campaign preparation approval', codes: ['CAMPAIGN_NOT_APPROVED'] },
  { label: 'Requirements present', codes: ['NO_REQUIREMENTS'] },
  { label: 'Requirement clarification and approval', codes: ['REQUIREMENTS_NEED_CLARIFICATION', 'REQUIREMENTS_NOT_APPROVED', 'INVALID_REQUIREMENT_APPROVAL'] },
  { label: 'Test Cases present', codes: ['NO_TEST_SPECIFICATIONS'] },
  { label: 'Stored Test approval integrity', codes: ['INVALID_TEST_APPROVAL'] },
  { label: 'Approved Requirement coverage', codes: ['REQUIREMENT_COVERAGE_GAP'] },
];

export function CampaignReadiness({ value, base }: { value: Readiness; base: string }) {
  const counts = [
    ['Requirements', value.total_requirements], ['Approved Requirements', value.approved_requirements],
    ['Requirements needing clarification', value.clarification_requirements], ['Test Cases', value.total_test_specifications],
    ['Approved Test Cases', value.approved_test_specifications], ['Covered Requirements', value.covered_requirements],
    ['Partially covered Requirements', value.partial_requirements], ['Uncovered Requirements', value.uncovered_requirements],
  ] as const;
  return <><PreparationNextStep value={value} base={base} /><div className="preparation-status-grid">
    <section className="panel"><h3>Preparation status</h3><CampaignStatusBadge status={value.campaign_preparation_status} /><p className="hint">Explicit Campaign preparation status.</p></section>
    <section className="panel"><h3>Readiness</h3><CampaignStatusBadge status={value.status} /><p className="hint">Derived from saved approvals and Requirement coverage. No execution is started.</p></section>
  </div><section className="panel campaign-section"><h3>Preparation summary</h3><p className="hint">Full Campaign aggregates from the readiness assessment.</p>
    <dl className="campaign-counts">{counts.map(([label, count]) => <Metric key={label} label={label} value={count} />)}</dl>
  </section><section className="panel campaign-section"><h3>Readiness checks</h3>
    <p className="hint">Check status reflects the blocker codes returned by the saved readiness assessment.</p>
    <ul className="readiness-checks">{checks.map(check => {
      const blocked = check.codes.some(code => value.blocker_codes.includes(code));
      return <li key={check.label}><span>{check.label}</span><span className={blocked ? 'check-state warning' : 'check-state success'}>{blocked ? 'Blocking' : 'Satisfied'}</span></li>;
    })}</ul>
  </section><section className="panel campaign-section"><h3>Readiness blockers</h3>
    {value.blocker_codes.length ? <ul className="readiness-blockers">{value.blocker_codes.map(code => {
      const item = blockers[code] ?? { text: 'An additional preparation blocker requires operator attention.', area: '' };
      return <li key={code}><p>{item.text}</p><Link to={item.area ? `${base}/${item.area}` : base}>Inspect {item.area === 'traceability' ? 'Traceability' : item.area === 'requirements' ? 'Requirements' : item.area === 'test-specifications' ? 'Test Cases' : 'Campaign overview'}</Link>
        <details><summary>Technical detail</summary><code>{code}</code></details></li>;
    })}</ul> : <p>No preparation blockers. Ready describes preparation, not a test result.</p>}
  </section></>;
}
