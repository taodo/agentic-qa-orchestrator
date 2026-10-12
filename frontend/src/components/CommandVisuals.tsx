import type { RunResults } from '../api/runTypes';

// Local decorative SVGs; no remote assets or status inference.
export function MetricIcon({kind}:{kind:'requirements'|'approved'|'run'|'outcome'}) {
  const paths = {
    requirements:<><path d="M7 3h8l3 3v15H6V3h1Zm2 6h6m-6 4h6m-6 4h4"/></>,
    approved:<><rect x="3" y="3" width="18" height="18" rx="5"/><path d="m7 12 3 3 7-7"/></>,
    run:<><path d="m9 5 11 7-11 7V5Z"/><path d="M4 5v14"/></>,
    outcome:<><path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7l-9-4Z"/><path d="M12 8v5m0 3v.1"/></>,
  };
  return <span className={`metric-icon metric-icon--${kind}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[kind]}</svg></span>;
}

export function ResultDistribution({summary,executorKind='SYNTHETIC'}:{summary:RunResults['summary'];executorKind?:'SYNTHETIC'|'WEB_BROWSER'}) {
  const {total,passed,failed,skipped,not_evaluated:unknown}=summary;
  const displayCount=(value:number)=>Number.isSafeInteger(value)&&value>=0?value:'Unavailable';
  // Do not chart contradictory/absent counts; the textual server totals remain visible.
  const valid=[total,passed,failed,skipped,unknown].every(n=>Number.isSafeInteger(n)&&n>=0) && passed+failed+skipped+unknown===total;
  const counts=[['Passed',passed,'pass'],['Failed',failed,'fail'],['Skipped',skipped,'skip'],['Not evaluated',unknown,'unknown']] as const;
  let position=0;
  const segments=valid&&total>0?counts.map(([label,count,tone])=>{
    const length=count/total*100, offset=position;position+=length;
    return count>0?<circle key={label} className={`result-segment result-segment--${tone}`} cx="60" cy="60" r="48" pathLength="100" strokeDasharray={`${length} ${100-length}`} strokeDashoffset={-offset}/>:null;
  }):null;
  return <section className="result-distribution" aria-label="Persisted result distribution"><div className="result-ring">
    <svg viewBox="0 0 120 120" aria-hidden="true"><circle className="result-ring-track" cx="60" cy="60" r="48"/>{segments}</svg>
    <div><strong>{displayCount(total)}</strong><span>saved tests</span></div></div><div><h4>Result distribution</h4>
    {!valid?<p>Distribution unavailable. Inspect the saved totals.</p>:total===0?<p>No tests to chart.</p>:<p className="hint">Persisted QA outcomes · {executorKind}</p>}
    <dl className="result-legend">{counts.map(([label,count,tone])=><div key={label} className={`result-legend--${tone}`}><dt>{label}</dt><dd>{displayCount(count)}</dd></div>)}</dl>
  </div></section>;
}
