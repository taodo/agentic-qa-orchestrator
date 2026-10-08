import { describe, expect, it, vi } from 'vitest';
import { testCasesCsv, testCasesFilename, TEST_CASE_CSV_HEADERS, downloadTestCases } from './testCaseCsv';
import { specification } from '../test/campaigns';

import { readCsv } from '../test/csv';

function record(csv:string){const [headers,values]=readCsv(csv);return Object.fromEntries(headers.map((key,i)=>[key,values[i]]));}

describe('deterministic spreadsheet-safe CSV',()=>{
  it('exports exactly six human-facing columns without audit fields',()=>{
    const rows=readCsv(testCasesCsv([specification]));
    expect(rows[0]).toEqual(['title','test_type','priority','preconditions','steps','overall_expected_result']);
    expect(rows[1]).toHaveLength(6);
    expect(record(testCasesCsv([specification]))).toEqual({
      title:specification.title,test_type:specification.test_type,priority:specification.priority,
      preconditions:specification.preconditions[0],
      steps:'1. Action: Submit a payment\n   Expected: Payment accepted',
      overall_expected_result:specification.overall_expected_result,
    });
    expect(rows.flat()).not.toContain(specification.id);expect(rows.flat()).not.toContain(specification.key);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('renders the booking regression as ordered paired Action/Expected text without JSON',()=>{
    const steps=[
      {index:2,action:'Inspect the post-submission persistence state and compare it with the recorded pre-submission state.',expected:'No partial booking record attributable to the rejected attempt is persisted.'},
      {index:1,action:'Attempt to submit the booking without providing a guest name.',expected:'The booking is rejected.'},
    ];
    const test={...specification,steps},before=JSON.stringify(test);
    expect(record(testCasesCsv([test])).steps).toBe(
      '1. Action: Attempt to submit the booking without providing a guest name.\n   Expected: The booking is rejected.\n\n'+
      '2. Action: Inspect the post-submission persistence state and compare it with the recorded pre-submission state.\n   Expected: No partial booking record attributable to the rejected attempt is persisted.');
    expect(record(testCasesCsv([test])).steps).not.toMatch(/[{}\[\]]/);
    expect(JSON.stringify(test)).toBe(before);expect(testCasesCsv([test])).toBe(testCasesCsv([test]));
  });
  it('renders single and multiple preconditions as readable deterministic lines',()=>{
    expect(record(testCasesCsv([{...specification,preconditions:['A valid room exists.']}])).preconditions).toBe('A valid room exists.');
    expect(record(testCasesCsv([{...specification,preconditions:['A valid room exists.','The room is available for the requested dates.','Record the current booking state before execution.']}])).preconditions)
      .toBe('1. A valid room exists.\n2. The room is available for the requested dates.\n3. Record the current booking state before execution.');
  });
  it('quotes readable multiline cells while preserving commas, quotes, CR/LF and Unicode',()=>{
    const test={...specification,title:'Phòng "Đẹp", 日本語\r\nsecond line',preconditions:['x,y','a"b','line\nnext'],
      steps:[{index:1,action:'Select "phòng", 日本語\r\nnext action line',expected:'🙂\nResult, "OK"'}],
      overall_expected_result:'Booked, "confirmed"\r\nTiếng Việt'};
    const csv=testCasesCsv([test]),rows=readCsv(csv),fields=record(csv);
    expect(rows).toHaveLength(2);expect(rows.every(row=>row.length===6)).toBe(true);
    expect(fields.title).toBe(test.title);expect(fields.overall_expected_result).toBe(test.overall_expected_result);
    expect(fields.preconditions).toBe('1. x,y\n2. a"b\n3. line\nnext');
    expect(fields.steps).toBe('1. Action: Select "phòng", 日本語\r\nnext action line\n   Expected: 🙂\nResult, "OK"');
    expect(csv).toContain('"Phòng ""Đẹp"", 日本語\r\nsecond line"');expect(csv.endsWith('\r\n')).toBe(true);
  });
  it.each(['=SUM(A1:A2)','+cmd','-1+2','@call','  =cmd','\t+cmd','\r\n@cmd','\ufeff=cmd'])('neutralizes formula-like text after rendering: %j',value=>{
    const fields=record(testCasesCsv([{...specification,title:value,preconditions:[value],overall_expected_result:value}]));
    expect(fields.title).toBe("'"+value);expect(fields.preconditions).toBe("'"+value);expect(fields.overall_expected_result).toBe("'"+value);
  });
  it('keeps formula-like step/precondition content inert behind readable numbering',()=>{
    const fields=record(testCasesCsv([{...specification,preconditions:['=cmd','@cmd'],steps:[{index:1,action:'=cmd',expected:'+cmd'}]}]));
    expect(fields.preconditions).toBe('1. =cmd\n2. @cmd');expect(fields.steps).toBe('1. Action: =cmd\n   Expected: +cmd');
  });
  it('keeps absent optional values blank without inventing expected results',()=>{
    const fields=record(testCasesCsv([{...specification,preconditions:[],steps:[{index:1,action:'Observe',expected:null}],overall_expected_result:null}]));
    expect(fields.preconditions).toBe('');expect(fields.overall_expected_result).toBe('');expect(fields.steps).toBe('1. Action: Observe\n   Expected: ');
    expect(readCsv(testCasesCsv([]))).toEqual([[...TEST_CASE_CSV_HEADERS]]);
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
