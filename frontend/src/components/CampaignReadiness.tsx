import { Link } from 'react-router-dom';
import type { CampaignReadiness as Readiness, ReadinessBlocker } from '../api/campaignTypes';
import { CampaignStatusBadge } from './CampaignStatusBadge';

const blockers: Record<ReadinessBlocker, { text: string; area: '' | 'requirements' | 'test-specifications' | 'traceability' }> = {
  CAMPAIGN_NOT_APPROVED: { text: 'Campaign preparation has not been approved.', area: '' },
  NO_REQUIREMENTS: { text: 'No Requirements have been prepared.', area: 'requirements' },
  REQUIREMENTS_NOT_APPROVED: { text: 'One or more Requirements still need approval.', area: 'requirements' },
  REQUIREMENTS_NEED_CLARIFICATION: { text: 'One or more Requirements need clarification.', area: 'requirements' },
  NO_TEST_SPECIFICATIONS: { text: 'No Test Specifications have been prepared.', area: 'test-specifications' },
  REQUIREMENT_COVERAGE_GAP: { text: 'One or more Requirements do not have approved test coverage.', area: 'traceability' },
  INVALID_REQUIREMENT_APPROVAL: { text: 'Stored Requirement approval evidence is inconsistent; operator attention is required.', area: 'requirements' },
  INVALID_TEST_APPROVAL: { text: 'Stored Test Specification approval evidence is inconsistent; operator attention is required.', area: 'test-specifications' },
};

export function CampaignReadiness({ value, base }: { value: Readiness; base: string }) {
  const counts = [
    ['Requirements', value.total_requirements], ['Approved Requirements', value.approved_requirements],
    ['Requirements needing clarification', value.clarification_requirements], ['Test Specifications', value.total_test_specifications],
    ['Approved Test Specifications', value.approved_test_specifications], ['Covered Requirements', value.covered_requirements],
    ['Partially covered Requirements', value.partial_requirements], ['Uncovered Requirements', value.uncovered_requirements],
  ] as const;
  return <><div className="preparation-status-grid">
    <section className="panel"><h3>Preparation status</h3><CampaignStatusBadge status={value.campaign_preparation_status} /><p className="hint">Explicit Campaign preparation status.</p></section>
    <section className="panel"><h3>Readiness</h3><CampaignStatusBadge status={value.status} /><p className="hint">Derived from saved approvals and Requirement coverage. No execution is started.</p></section>
  </div><section className="panel campaign-section"><h3>Preparation summary</h3><p className="hint">Full Campaign aggregates from the readiness assessment.</p>
    <dl className="campaign-counts">{counts.map(([label, count]) => <div key={label}><dt>{label}</dt><dd>{count}</dd></div>)}</dl>
  </section><section className="panel campaign-section"><h3>Readiness blockers</h3>
    {value.blocker_codes.length ? <ul className="readiness-blockers">{value.blocker_codes.map(code => {
      const item = blockers[code] ?? { text: 'An additional preparation blocker requires operator attention.', area: '' };
      return <li key={code}><p>{item.text}</p><Link to={item.area ? `${base}/${item.area}` : base}>Inspect {item.area === 'traceability' ? 'Traceability' : item.area === 'requirements' ? 'Requirements' : item.area === 'test-specifications' ? 'Test Specifications' : 'Campaign overview'}</Link>
        <details><summary>Technical detail</summary><code>{code}</code></details></li>;
    })}</ul> : <p>No preparation blockers. Ready describes preparation, not a test result.</p>}
  </section></>;
}
