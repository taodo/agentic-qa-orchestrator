"""Bounded QA fields only. CSV formula defense; XLSX cells are literal inline strings."""
import base64
import csv
from io import BytesIO, StringIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
import re

HEADERS = ('Test Case ID','Title','Requirement','Priority','Preconditions','Steps','Expected Result','Test Data','Status','Clarification / Missing Information')
MAX_EXPORT_BYTES = 4 * 1024 * 1024


def export_tests(tests, requirements, format):
    if not tests or len(tests) > 200: raise ValueError('EXPORT_LIMIT')
    names = {str(r.id):r.key+' — '+r.title for r in requirements}
    rows = [HEADERS]
    for t in tests:
        rows.append((t.key,t.title,'; '.join(names.get(str(id),str(id)) for id in t.requirement_ids),t.priority,
            '\n'.join(t.preconditions),'\n'.join(f'{s.index}. {s.action}\nExpected: {s.expected or "Not specified"}' for s in t.steps),
            t.overall_expected_result or 'Not specified','Not separately captured',t.review_status,
            '\n'.join(m.description for m in t.information_markers)))
    return export_rows(rows, format, 'test-design', len(tests))


def export_rows(rows, format, filename, count):
    if sum(sum(len(str(cell).encode('utf-8')) for cell in row) for row in rows) > MAX_EXPORT_BYTES: raise ValueError('EXPORT_LIMIT')
    if format == 'CSV':
        out=StringIO(newline='');writer=csv.writer(out)
        for row in rows:
            writer.writerow(["'"+str(c) if re.match(r'^[\s\x00-\x1f]*[=+\-@]|^[\x00-\x1f]',str(c)) else str(c) for c in row])
        raw=('\ufeff'+out.getvalue()).encode('utf-8');mime='text/csv;charset=utf-8'
    elif format == 'XLSX':
        if any(len(str(c))>32767 for row in rows for c in row): raise ValueError('EXPORT_CELL_LIMIT')
        sheet=['<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for i,row in enumerate(rows,1):
            sheet.append(f'<row r="{i}">')
            for j,c in enumerate(row):
                if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',str(c)): raise ValueError('EXPORT_XML_INVALID')
                sheet.append(f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t xml:space="preserve">{escape(str(c))}</t></is></c>')
            sheet.append('</row>')
        sheet.append('</sheetData></worksheet>')
        stream=BytesIO()
        with ZipFile(stream,'w',compression=ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
            z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Test Design" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/worksheets/sheet1.xml',''.join(sheet))
        raw=stream.getvalue();mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:raise ValueError('EXPORT_FORMAT_INVALID')
    if len(raw) > MAX_EXPORT_BYTES: raise ValueError('EXPORT_LIMIT')
    return {'filename':filename+'.'+format.lower(),'media_type':mime,'content_base64':base64.b64encode(raw).decode('ascii'),'count':count}
