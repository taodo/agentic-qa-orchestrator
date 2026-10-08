import type { CampaignTestSpecification } from '../api/campaignTypes';

export const TEST_CASE_CSV_HEADERS=['key','title','review_status','test_type','priority','requirement_ids',
  'preconditions','steps','overall_expected_result','required_evidence','information_markers','unresolved_requirement_refs','provenance','id'] as const;
const structured=new Set<string>(['requirement_ids','preconditions','steps','required_evidence','information_markers','unresolved_requirement_refs','provenance']);
function ordered(value:unknown):unknown {
  if(Array.isArray(value))return value.map(ordered);
  if(value!==null && typeof value==='object')return Object.fromEntries(Object.entries(value).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([key,item])=>[key,ordered(item)]));
  return value;
}
function quote(value:string){return '"'+value.replaceAll('"','""')+'"';}
export function testCasesCsv(cases:CampaignTestSpecification[]):string {
  const rows=cases.map(test=>TEST_CASE_CSV_HEADERS.map(key=>{
    if(structured.has(key))return quote(JSON.stringify(ordered(test[key])));
    const value=test[key]==null?'':String(test[key]);
    // Spreadsheet protection includes leading whitespace/control-character bypasses.
    const unsafe=/^[\s\u0000-\u001f]*[=+\-@]/u.test(value) || /^[\u0000-\u001f]/u.test(value);
    return quote(unsafe?"'"+value:value);
  }).join(','));
  return [TEST_CASE_CSV_HEADERS.map(quote).join(','),...rows].join('\r\n')+'\r\n';
}
export function testCasesFilename(campaignName:string,scope:'visible'|'selected'):string {
  const slug=campaignName.normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,60).replace(/-+$/g,'') || 'campaign';
  return `${slug}-test-cases-${scope}.csv`;
}
export function downloadTestCases(cases:CampaignTestSpecification[],campaignName:string,scope:'visible'|'selected') {
  const blob=new Blob(['\ufeff',testCasesCsv(cases)],{type:'text/csv;charset=utf-8'});
  const url=URL.createObjectURL(blob), link=document.createElement('a');
  try { link.href=url;link.download=testCasesFilename(campaignName,scope);document.body.appendChild(link);link.click(); }
  finally { link.remove();setTimeout(()=>URL.revokeObjectURL(url),0); }
}
