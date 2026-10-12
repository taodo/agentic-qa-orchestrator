import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import { ResultDistribution } from './CommandVisuals';
const summary={total:8,completed:5,passed:3,failed:1,skipped:1,not_evaluated:3,remaining:3};
it('renders all authoritative outcome counts without execution-success inference or requests',()=>{
  const original={...summary};const view=render(<ResultDistribution summary={summary}/>);
  const region=screen.getByRole('region',{name:'Persisted result distribution'});
  for(const [label,count] of [['Passed',3],['Failed',1],['Skipped',1],['Not evaluated',3]]) {
    const entry=within(region).getByText(String(label)).closest('div')!;expect(entry).toHaveTextContent(String(count));
  }
  expect(within(region).getByText('8')).toBeInTheDocument();
  expect(view.container.querySelector('.result-segment--pass')).toHaveAttribute('stroke-dasharray','37.5 62.5');
  expect(view.container.querySelector('.result-segment--unknown')).toHaveAttribute('stroke-dasharray','37.5 62.5');
  expect(summary).toEqual(original);expect(fetch).not.toHaveBeenCalled();
});
it('keeps zero totals honest and avoids a fabricated ring or percentage',()=>{
  const view=render(<ResultDistribution summary={{total:0,completed:0,passed:0,failed:0,skipped:0,not_evaluated:0,remaining:0}}/>);
  expect(screen.getByText('No tests to chart.')).toBeInTheDocument();expect(view.container.querySelectorAll('.result-segment')).toHaveLength(0);
});
it.each([{...summary,passed:9},{...summary,total:-1},{...summary,failed:NaN}])('does not chart contradictory/non-finite counts',value=>{
  const view=render(<ResultDistribution summary={value}/>);expect(screen.getByText('Distribution unavailable. Inspect the saved totals.')).toBeInTheDocument();
  expect(view.container.querySelectorAll('.result-segment')).toHaveLength(0);expect(fetch).not.toHaveBeenCalled();
});
