import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { RunEvidenceRecord } from './RunEvidenceRecord';
import type { RunEvidence } from '../api/runTypes';

it('renders authoritative presentation without payload or synthetic field assumptions',()=>{
  const record:Omit<RunEvidence,'payload'>={
    id:'record',project_id:'project',campaign_id:'campaign',run_id:'run',run_test_id:'test',
    sequence:1,recorded_at:'2026-10-09T00:00:00Z',schema_version:'qa-run-evidence-v1',
    kind:'EXECUTION_OBSERVATION',source:'reviewed-test-fixture',summary:'Safe fixture observation',
    presentation:{variant:'test-only-policy',display_label:'REVIEWED FIXTURE',details:[{label:'Fixture detail',value:'Typed projection value'}]},
  };
  // Generic presentation fixture only; this is not an admitted runtime variant.
  const payload=vi.fn(()=>{throw new Error('Generic UI must not inspect payload');});
  Object.defineProperty(record,'payload',{get:payload});
  render(<ul><RunEvidenceRecord record={record}/></ul>);
  expect(screen.getByText('REVIEWED FIXTURE')).toBeInTheDocument();
  expect(screen.getByText('Fixture detail')).toBeInTheDocument();
  expect(screen.getByText('Typed projection value')).toBeInTheDocument();
  expect(screen.queryByText('SYNTHETIC')).not.toBeInTheDocument();
  expect(payload).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();
});
