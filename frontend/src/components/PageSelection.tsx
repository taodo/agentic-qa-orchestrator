import { useEffect, useRef } from 'react';

/** Native checkbox: affects only the explicit IDs shown on the current page. */
export function PageSelection({count,selected,disabled,onChange}:{count:number;selected:number;disabled:boolean;onChange:(checked:boolean)=>void}) {
  const ref=useRef<HTMLInputElement>(null);
  useEffect(()=>{if(ref.current)ref.current.indeterminate=selected>0 && selected<count;},[count,selected]);
  return <input ref={ref} type="checkbox" aria-label="Select all on current page" checked={count>0 && selected===count} disabled={disabled||!count} onChange={event=>onChange(event.target.checked)}/>;
}
