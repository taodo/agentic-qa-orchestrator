import { useEffect, useId, useState, type ReactNode } from 'react';

// The same disclosure interaction for Requirements and Test Cases.
export function PreparationRow({ id, initialOpen=false, children }: {
  id:string; initialOpen?:boolean; children:(state:{open:boolean;setOpen:(value:boolean)=>void;detailId:string})=>ReactNode;
}) {
  const [open,setOpen]=useState(initialOpen), detailId=useId();
  useEffect(()=>setOpen(initialOpen),[initialOpen]);
  return <tr id={id} tabIndex={0} aria-expanded={open} aria-controls={detailId} className={open?'preparation-row is-expanded':'preparation-row'}
    onClick={event=>{
      if(event.defaultPrevented || !(event.target instanceof Element))return;
      const control=event.target.closest('a,button,input,select,textarea,label,summary,form,[role="button"],[role="link"],[role="checkbox"],[contenteditable="true"],[tabindex]');
      if(control && control!==event.currentTarget)return;
      setOpen(!open);
    }} onKeyDown={event=>{
      if(event.target===event.currentTarget && (event.key==='Enter' || event.key===' ')){event.preventDefault();setOpen(!open);}
    }}>{children({open,setOpen,detailId})}</tr>;
}
