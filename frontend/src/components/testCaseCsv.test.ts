import { describe, expect, it, vi } from 'vitest';
import { testCasesCsv, testCasesFilename, TEST_CASE_CSV_HEADERS, downloadTestCases } from './testCaseCsv';
import { specification } from '../test/campaigns';

import { readCsv } from '../test/csv';

function record(csv:string){const [headers,values]=readCsv(csv);return Object.fromEntries(headers.map((key,i)=>[key,values[i]]));}

describe('deterministic spreadsheet-safe CSV',()=>{
  it('round-trips quotes, commas, CR/LF, Unicode and lossless structured fields',()=>{
    const test={...specification,title:'Phòng "Đẹp", 日本語\r\nsecond line',preconditions:['x,y','a"b','line\nnext'],
      steps:[{index:1,action:'=not a formula inside JSON',expected:'🙂\r\nResult'}],overall_expected_result:null,
      information_markers:[{kind:'AMBIGUITY' as const,description:'Missing "x",\nwhy?'}]};
    const csv=testCasesCsv([test]),fields=record(csv);
    expect(readCsv(csv)[0]).toEqual(TEST_CASE_CSV_HEADERS);expect(readCsv(csv)).toHaveLength(2);
    expect(fields.title).toBe(test.title);expect(fields.overall_expected_result).toBe('');
    for(const key of ['preconditions','steps','information_markers','requirement_ids','required_evidence','provenance','unresolved_requirement_refs'] as const)expect(JSON.parse(fields[key])).toEqual(test[key]);
    expect(csv).toContain('"Phòng ""Đẹp"", 日本語\r\nsecond line"');expect(csv.endsWith('\r\n')).toBe(true);
    expect(testCasesCsv([test])).toBe(csv);expect(fetch).not.toHaveBeenCalled();
  });
  it.each(['=SUM(A1:A2)','+cmd','-1+2','@call','  =cmd','\t+cmd','\r\n@cmd','\ufeff=cmd'])('neutralizes formula-like plain cells: %j',value=>{
    expect(record(testCasesCsv([{...specification,title:value}])).title).toBe("'"+value);
  });
  it('keeps empty collections/null deterministic and sorts structured object keys',()=>{
    const test={...specification,preconditions:[],required_evidence:[],information_markers:[],overall_expected_result:null};
    const fields=record(testCasesCsv([test]));expect(fields.preconditions).toBe('[]');expect(fields.overall_expected_result).toBe('');
    const reordered={...test,provenance:Object.fromEntries(Object.entries(test.provenance).reverse()) as typeof test.provenance};
    expect(testCasesCsv([reordered])).toBe(testCasesCsv([test]));expect(readCsv(testCasesCsv([]))).toEqual([[...TEST_CASE_CSV_HEADERS]]);
  });
  it('uses safe bounded deterministic ASCII filenames',()=>{
    expect(testCasesFilename('../../Cafe, QA\\escape?','visible')).toBe('cafe-qa-escape-test-cases-visible.csv');
    expect(testCasesFilename('日本語','selected')).toBe('campaign-test-cases-selected.csv');
    expect(testCasesFilename('X'.repeat(200),'visible')).toBe('x'.repeat(60)+'-test-cases-visible.csv');
  });
  it('downloads UTF-8 with BOM and releases its object URL without requests',async()=>{
    let blob:Blob|undefined;const created=vi.fn((value:Blob)=>{blob=value;return 'blob:offline';}),revoked=vi.fn();
    const NativeURL=URL;vi.stubGlobal('URL',class extends NativeURL{static createObjectURL=created;static revokeObjectURL=revoked;});
    const click=vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){expect(this.download).toBe('checkout-test-cases-visible.csv');});
    downloadTestCases([{...specification,title:'Tiếng Việt 日本語'}],'Checkout','visible');
    const bytes=await new Promise<Uint8Array>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(new Uint8Array(reader.result as ArrayBuffer));reader.onerror=reject;reader.readAsArrayBuffer(blob!);});
    expect([...bytes.slice(0,3)]).toEqual([239,187,191]);expect(new TextDecoder().decode(bytes)).toContain('Tiếng Việt 日本語');
    await new Promise(resolve=>setTimeout(resolve,1));expect(revoked).toHaveBeenCalledWith('blob:offline');expect(click).toHaveBeenCalledTimes(1);expect(fetch).not.toHaveBeenCalled();click.mockRestore();
  });
});
