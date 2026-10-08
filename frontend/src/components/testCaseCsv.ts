import type { CampaignTestSpecification } from '../api/campaignTypes';

export const TEST_CASE_CSV_HEADERS = [
  'title', 'test_type', 'priority', 'preconditions', 'steps', 'overall_expected_result',
] as const;

function quote(value: string): string {
  // Apply protection after presentation formatting, to every exported cell.
  const unsafe = /^[\s\u0000-\u001f]*[=+\-@]/u.test(value) || /^[\u0000-\u001f]/u.test(value);
  const safe = unsafe ? "'" + value : value;
  return '"' + safe.replaceAll('"', '""') + '"';
}

export function testCasesCsv(cases: CampaignTestSpecification[]): string {
  const rows = cases.map(test => {
    const preconditions = test.preconditions.length <= 1
      ? test.preconditions[0] ?? ''
      : test.preconditions.map((item, index) => `${index + 1}. ${item}`).join('\n');
    const steps = [...test.steps].sort((a, b) => a.index - b.index)
      .map(step => `${step.index}. Action: ${step.action}\n   Expected: ${step.expected ?? ''}`)
      .join('\n\n');
    return [test.title, test.test_type, test.priority, preconditions, steps,
      test.overall_expected_result ?? ''].map(quote).join(',');
  });
  return [TEST_CASE_CSV_HEADERS.map(quote).join(','), ...rows].join('\r\n') + '\r\n';
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
