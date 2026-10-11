"""Offline bounded document provenance and parsing rejection."""
from io import BytesIO
from zipfile import ZipFile
from uuid import uuid4
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
from qa_sentinel.agents.documents import parse_document, SourceTooLarge


def docx(text='Booking dates', extra=None):
    data=BytesIO()
    with ZipFile(data,'w') as z:
        z.writestr('[Content_Types].xml','<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        if extra:z.writestr(*extra)
    return data.getvalue()


def parse(name,raw):return parse_document(uuid4(),uuid4(),name=name,content=raw)


def pdf():
    out=BytesIO();writer=PdfWriter();page=writer.add_blank_page(width=400,height=400)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 300 Td (Supported booking dates) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream);writer.write(out);return out.getvalue()


@pytest.mark.parametrize('name,raw',[('spec.txt',b'Heading\r\nRule'),('spec.md',b'# Heading\n- Rule'),('spec.docx',docx()),('spec.pdf',pdf())])
def test_supported_documents(name,raw):
    source=parse(name,raw)
    assert source.status=='INGESTED' and source.normalized_text
    if name.endswith(('.pdf','.docx')):
        assert source.document.coordinates[0].start_line==1
        assert source.document.coordinates[-1].end_line<=source.line_count
        assert source.original_bytes==len(raw)


@pytest.mark.parametrize('name,raw',[('../spec.txt',b'x'),('C:\\spec.txt',b'x'),('spec.exe',b'x'),('spec.pdf',b'fake pdf'),('spec.docx',b'fake zip'),('spec.docx',docx(extra=('../evil.txt','x'))),('spec.docx',docx(extra=('word/vbaProject.bin','x'))),('spec.docx',docx(text='&evil;'))])
def test_document_validation_fails_closed(name,raw):
    with pytest.raises(ValueError):parse(name,raw)


def test_docx_images_disclosed_without_reading_them():
    source=parse('spec.docx',docx(extra=('word/media/image.png','NOT_AN_IMAGE')))
    assert 'IMAGES_NOT_ANALYZED' in source.document.limitations


def test_limits():
    with pytest.raises(SourceTooLarge):parse('spec.txt',b'x'*(2*1024*1024+1))
    with pytest.raises(SourceTooLarge):parse('spec.docx',docx(text='x'*65537))


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_xml_entities_are_rejected_even_with_alternate_encoding(encoding):
    xml = '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY facts "unsafe">]><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&facts;</w:t></w:r></w:p></w:body></w:document>'
    out = BytesIO()
    with ZipFile(BytesIO(docx())) as original, ZipFile(out, 'w') as archive:
        archive.writestr('[Content_Types].xml', original.read('[Content_Types].xml'))
        archive.writestr('word/document.xml', xml.encode(encoding))
    with pytest.raises(ValueError):
        parse('spec.docx', out.getvalue())


def test_pdf_no_text_and_encrypted_content_fail_closed():
    for encrypted in [False, True]:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        if encrypted:
            writer.encrypt('never opened')
        out = BytesIO()
        writer.write(out)
        with pytest.raises(ValueError):
            parse('spec.pdf', out.getvalue())
