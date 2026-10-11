"""Bounded inert document parsing. No file paths, includes, URLs or executable content."""
from hashlib import sha256
from io import BytesIO
import re
import unicodedata
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET
from qa_sentinel.domain.campaign_content import CampaignSource, DocumentProvenance, DocumentCoordinate
from .requirement_extraction import ingest, SourceTooLarge

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 65536


def filename(value):
    if type(value) is not str or not 1 <= len(value) <= 200 or any(c in value for c in "\\/:\x00") or value.startswith('.'):
        raise ValueError("DOCUMENT_INVALID")
    if any(unicodedata.category(c) == "Cc" for c in value): raise ValueError("DOCUMENT_INVALID")
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value): raise ValueError("DOCUMENT_INVALID")
    return value


def _assemble(parts, kind):
    lines, coordinates = [], []
    for number, part in enumerate(parts, 1):
        part = unicodedata.normalize('NFC', part.replace('\r\n','\n').replace('\r','\n'))
        start = len(lines) + 1
        lines.extend(part.split('\n'))
        coordinates.append(DocumentCoordinate(kind=kind,index=number,start_line=start,end_line=len(lines)))
        if len(lines) > 4096 or sum(len(line)+1 for line in lines) > MAX_TEXT_CHARS: raise SourceTooLarge("DOCUMENT_LIMIT")
    return '\n'.join(lines), tuple(coordinates)


def _docx(raw):
    with ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > 256 or len(names) != len(set(names)) or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
            raise SourceTooLarge("DOCUMENT_LIMIT")
        for entry in entries:
            if entry.flag_bits & 1 or entry.filename.startswith('/') or '\\' in entry.filename or ':' in entry.filename or '..' in entry.filename.split('/'):
                raise ValueError("DOCUMENT_INVALID")
            if entry.file_size > MAX_EXPANDED_BYTES or (entry.compress_size and entry.file_size > entry.compress_size * 200):
                raise SourceTooLarge("DOCUMENT_LIMIT")
        if any(n.lower().endswith('.bin') for n in names): raise ValueError("DOCUMENT_INVALID")
        if '[Content_Types].xml' not in names or 'word/document.xml' not in names: raise ValueError("DOCUMENT_INVALID")
        def xml(name):
            # Parse only bounded UTF-8 XML, so alternate encodings cannot hide DTDs.
            data = archive.read(name).decode('utf-8-sig')
            if '<!DOCTYPE' in data.upper() or '<!ENTITY' in data.upper():
                raise ValueError("DOCUMENT_INVALID")
            return ET.fromstring(data)
        types = xml('[Content_Types].xml')
        if not any(e.get('PartName') == '/word/document.xml' and e.get('ContentType') == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' for e in types):
            raise ValueError("DOCUMENT_INVALID")
        root = xml('word/document.xml')
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        if root.tag != ns+'document': raise ValueError("DOCUMENT_INVALID")
        body = root.find(ns+'body')
        if body is None: raise ValueError("DOCUMENT_INVALID")
        parts = []
        for para in body.iter(ns+'p'):
            parts.append(''.join(e.text or '' if e.tag == ns+'t' else '\n' if e.tag == ns+'br' else '\t' if e.tag == ns+'tab' else '' for e in para.iter()))
        text, coordinates = _assemble(parts, 'PARAGRAPH')
        limitations = ['LAYOUT_NOT_ANALYZED','NON_BODY_CONTENT_NOT_ANALYZED']
        if any(n.startswith('word/media/') for n in names): limitations.append('IMAGES_NOT_ANALYZED')
        return text, DocumentProvenance(parser='docx-xml-v1',coordinates=coordinates,limitations=limitations)


def _pdf(raw):
    from pypdf import PdfReader, apply_configuration
    if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-1024:]: raise ValueError("DOCUMENT_INVALID")
    # Context-local parser limits, not process-global settings. Images are never decoded.
    with apply_configuration(maximum_declared_stream_length=MAX_EXPANDED_BYTES,
            zlib_maximum_output_length=MAX_EXPANDED_BYTES, lzw_maximum_output_length=MAX_EXPANDED_BYTES,
            run_length_maximum_output_length=MAX_EXPANDED_BYTES, array_based_stream_maximum_output_length=MAX_EXPANDED_BYTES,
            stream_decoding_work_maximum_length=8*MAX_EXPANDED_BYTES, page_tree_maximum_entries=200,
            page_tree_maximum_depth=20, xform_maximum_invocations_per_extraction=100,
            zlib_maximum_recovery_input_length=65536, stream_filters_maximum_length=4):
        reader = PdfReader(BytesIO(raw),strict=True,root_object_recovery_limit=100)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 100: raise ValueError("DOCUMENT_INVALID")
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text())
            if sum(len(part) for part in parts) > MAX_TEXT_CHARS: raise SourceTooLarge("DOCUMENT_LIMIT")
        text, coordinates = _assemble(parts, 'PAGE')
    # Conservatively disclose visual content is outside the parser's analysis for every PDF.
    return text, DocumentProvenance(parser='pypdf-text-v1',coordinates=coordinates,
        limitations=('LAYOUT_NOT_ANALYZED','IMAGES_NOT_ANALYZED'))


def parse_document(project_id, campaign_id, *, name, content):
    name = filename(name)
    if type(content) is not bytes or len(content) > MAX_UPLOAD_BYTES: raise SourceTooLarge("SOURCE_SIZE_LIMIT")
    extension = name.rsplit('.',1)[-1].lower()
    if extension in {'txt','md'}:
        source = ingest(project_id,campaign_id,name=name,source_type='TEXT' if extension=='txt' else 'MARKDOWN',content=content)
        return source
    if extension not in {'pdf','docx'}: raise ValueError("DOCUMENT_FORMAT_UNSUPPORTED")
    try:
        text, provenance = (_pdf if extension=='pdf' else _docx)(content)
        source = ingest(project_id,campaign_id,name=name,source_type='TEXT',content=text)
        if source.status != 'INGESTED': raise ValueError("DOCUMENT_NO_TEXT")
        return CampaignSource.model_validate({**source.model_dump(), 'source_type':extension.upper(),
            'raw_hash':sha256(content).hexdigest(),'original_bytes':len(content),'document':provenance})
    except SourceTooLarge:
        raise
    except Exception:
        # Do not log or return parser exceptions/document text/paths.
        raise ValueError("DOCUMENT_INVALID") from None
