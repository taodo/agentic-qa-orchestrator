import { useLayoutEffect, useRef } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PreparationRow } from './PreparationRow';

function Table({initialOpen=false}:{initialOpen?:boolean}) {
  return <table><tbody><PreparationRow id="row" initialOpen={initialOpen}>{({open})=><td><details open={open}><summary>Details</summary>Content</details></td>}</PreparationRow></tbody></table>;
}
function EarlyInteraction() {
  const scope=useRef<HTMLDivElement>(null);
  useLayoutEffect(()=>{scope.current!.querySelector('tr')!.dispatchEvent(new MouseEvent('click',{bubbles:true}));},[]);
  return <div ref={scope}><Table/></div>;
}
describe('Preparation row initialization',()=>{
  it('does not undo an interaction before passive mount effects settle',()=>{
    render(<EarlyInteraction/>);
    expect(screen.getByRole('row')).toHaveAttribute('aria-expanded','true');
    expect(screen.getByText('Details').closest('details')).toHaveAttribute('open');
  });
  it('still synchronizes explicit selected-record changes',()=>{
    const view=render(<Table/>);
    expect(screen.getByRole('row')).toHaveAttribute('aria-expanded','false');
    view.rerender(<Table initialOpen/>);
    expect(screen.getByRole('row')).toHaveAttribute('aria-expanded','true');
    view.rerender(<Table/>);
    expect(screen.getByRole('row')).toHaveAttribute('aria-expanded','false');
  });
});
