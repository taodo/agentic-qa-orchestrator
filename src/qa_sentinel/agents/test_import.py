"""Pure bounded CSV/Markdown importer; text is data, never executable authority."""
import csv
import io
import json
import re
import unicodedata
from hashlib import sha256
from qa_sentinel.domain.test_specification import ImportedTest,TestImport,ImportFormat
from .requirement_extraction import SourceTooLarge

COLUMNS=('key','title','requirement_refs','test_type','priority','preconditions','steps','overall_expected_result','required_evidence','information_markers')
JSON_COLUMNS={'requirement_refs','preconditions','steps','overall_expected_result','required_evidence','information_markers'}

class ImportInvalid(ValueError):pass

def unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ImportInvalid('IMPORT_INVALID_SCHEMA')
        value[key]=item
    return value

def strict_json(value):
    def invalid(*args):raise ImportInvalid('IMPORT_INVALID_SCHEMA')
    return json.loads(value,object_pairs_hook=unique_object,parse_constant=invalid)

def parse_csv(text):
    reader=csv.DictReader(io.StringIO(text,newline=''),strict=True)
    if tuple(reader.fieldnames or ())!=COLUMNS:raise ImportInvalid('IMPORT_INVALID_SCHEMA')
    previous=reader.line_num
    for row in reader:
        start=previous+1;previous=reader.line_num
        if None in row or any(v is None for v in row.values()):raise ImportInvalid('IMPORT_INVALID_SCHEMA')
        yield ImportedTest(**{k:strict_json(v) if k in JSON_COLUMNS else v for k,v in row.items()}),start,previous

def parse_markdown(text):
    lines=text.split('\n')
    if not lines or lines[0]!='# Test cases':raise ImportInvalid('IMPORT_INVALID_SCHEMA')
    index=1
    while index<len(lines):
        if not lines[index].strip():index+=1;continue
        match=re.fullmatch(r'## ([A-Z0-9][A-Z0-9_-]{0,63})',lines[index])
        if not match or index+1>=len(lines) or lines[index+1]!='```json':raise ImportInvalid('IMPORT_INVALID_SCHEMA')
        start=index+1;index+=2;body=[]
        while index<len(lines) and lines[index]!='```':body.append(lines[index]);index+=1
        if index>=len(lines):raise ImportInvalid('IMPORT_INVALID_SCHEMA')
        data=strict_json('\n'.join(body))
        if not isinstance(data,dict) or 'key' in data:raise ImportInvalid('IMPORT_INVALID_SCHEMA')
        yield ImportedTest(key=match[1],**data),start,index+1
        index+=1

def parse_import(project_id,campaign_id,*,name,format,content):
    format=ImportFormat(format)
    if type(content) not in (str,bytes) or len(content)>65536:raise SourceTooLarge('SOURCE_SIZE_LIMIT')
    raw=content.encode('utf-8') if isinstance(content,str) else content
    if len(raw)>65536:raise SourceTooLarge('SOURCE_SIZE_LIMIT')
    raw_hash=sha256(raw).hexdigest();text=None;error=None;cases=[]
    try:
        if format==ImportFormat.XLSX:raise ImportInvalid('XLSX_UNSUPPORTED')
        text=unicodedata.normalize('NFC',raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n'))
        if any(unicodedata.category(c)=='Cc' and c not in '\n\t' for c in text):raise ImportInvalid('IMPORT_BINARY_TEXT')
        if len(text.split('\n'))>4096:raise ImportInvalid('IMPORT_LINE_LIMIT')
        keys=set()
        for case,start,end in (parse_csv(text) if format==ImportFormat.CSV else parse_markdown(text)):
            if len(cases)>=100:raise ImportInvalid('IMPORT_CASE_LIMIT')
            if case.key in keys:raise ImportInvalid('IMPORT_DUPLICATE_KEY')
            keys.add(case.key);cases.append((case,start,end))
        if not cases:raise ImportInvalid('IMPORT_INVALID_SCHEMA')
    except UnicodeError:error='IMPORT_INVALID_UTF8'
    except ImportInvalid as failure:error=str(failure)
    except (ValueError,TypeError,csv.Error,RecursionError):error='IMPORT_INVALID_SCHEMA'
    content_hash=raw_hash if text is None else sha256(text.encode('utf-8')).hexdigest()
    if error:text=None;cases=[]
    return TestImport(project_id=project_id,campaign_id=campaign_id,name=name,format=format,
        raw_hash=raw_hash,content_hash=content_hash,original_bytes=len(raw),normalized_text=text,
        status='REJECTED' if error else 'IMPORTED',error_code=error,test_count=len(cases)),tuple(cases)
