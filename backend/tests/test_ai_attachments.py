import io
import zipfile
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.ai.attachments import extract_document
from app.ai.attachment_router import attachment_router
from app.ai.openrouter_client import openrouter_client
from app.security.middleware import MaxBodySizeMiddleware
from app.security.policies import resolve_policy
from fastapi import FastAPI

app = FastAPI()
app.include_router(attachment_router)
app.add_middleware(MaxBodySizeMiddleware)
client = TestClient(app)


def text(doc):
    return '\n'.join(section[1] for section in doc.sections)


def test_csv_preserves_headers_values_and_locations():
    doc = extract_document('portfolio.csv', 'Ticker,Value\nHPG,12345\nVPB,0'.encode())
    assert 'Columns: Ticker | Value' in text(doc)
    assert 'HPG | 12345' in text(doc)
    assert 'VPB | 0' in text(doc)
    assert doc.sections[1][0] == 'row 2'


def test_csv_field_above_parser_default_uses_extraction_limit(monkeypatch):
    monkeypatch.setattr('app.ai.attachments.MAX_EXTRACTED_CHARS', 140_000)
    doc = extract_document('large.csv', ('Value\n' + 'x' * 150_000).encode())
    assert doc.characters == 140_000
    assert any('140,000 characters' in warning for warning in doc.warnings)


def test_xlsx_preserves_sheet_rows_and_does_not_execute_formulas():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = 'Holdings'
    sheet.append(['Ticker', 'Shares'])
    sheet.append(['HPG', 250])
    sheet.append(['TOTAL', '=SUM(B2:B2)'])
    data = io.BytesIO()
    book.save(data)
    doc = extract_document('holdings.xlsx', data.getvalue())
    assert 'HPG | 250' in text(doc)
    assert '=SUM(B2:B2)' in text(doc)
    assert doc.sections[1][0] == 'sheet Holdings, row 2'
    assert any('not calculated' in warning for warning in doc.warnings)


def test_docx_extracts_text_and_rejects_xml_entities():
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Revenue 12345</w:t></w:r></w:p></w:body></w:document>')
    assert 'Revenue 12345' in text(extract_document('report.docx', data.getvalue()))
    hostile = io.BytesIO()
    with zipfile.ZipFile(hostile, 'w') as archive:
        archive.writestr('word/document.xml', '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    with pytest.raises(HTTPException):
        extract_document('report.docx', hostile.getvalue())


def test_pdf_extracts_text_and_reports_scans():
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 200 Td (HPG revenue 12345) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    data = io.BytesIO()
    writer.write(data)
    doc = extract_document('report.pdf', data.getvalue())
    assert 'HPG revenue 12345' in text(doc)
    assert doc.sections[0][0] == 'page 1'
    blank = PdfWriter()
    blank.add_blank_page(width=300, height=300)
    data = io.BytesIO()
    blank.write(data)
    with pytest.raises(HTTPException, match='no readable text'):
        extract_document('scan.pdf', data.getvalue())


@pytest.mark.parametrize('name,data', [('script.exe', b'MZ'), ('empty.csv', b''), ('fake.pdf', b'not a pdf'), ('binary.txt', b'\x00\x01')])
def test_invalid_files_fail_cleanly(name, data):
    with pytest.raises(HTTPException):
        extract_document(name, data)


def test_text_extraction_reports_truncation(monkeypatch):
    monkeypatch.setattr('app.ai.attachments.MAX_EXTRACTED_CHARS', 20)
    doc = extract_document('large.txt', b'1234567890' * 20)
    assert doc.characters == 20
    assert doc.warnings


def test_document_expansion_is_bounded(monkeypatch):
    monkeypatch.setattr('app.ai.attachments.MAX_ZIP_BYTES', 100)
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('word/document.xml', 'x' * 101)
    with pytest.raises(HTTPException, match='expands'):
        extract_document('large.docx', data.getvalue())


def test_upload_runs_real_parser_and_never_calls_ai(monkeypatch, tmp_path):
    generate = AsyncMock(side_effect=AssertionError('must not send files to AI'))
    monkeypatch.setattr(openrouter_client, 'generate_chat', generate)
    monkeypatch.chdir(tmp_path)
    response = client.post('/api/ai/files/extract', files=[('files', ('numbers.csv', b'Ticker,Value\nHPG,12345', 'text/csv'))])
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    result = response.json()
    assert result['analysis_enabled'] is False
    assert result['files'][0]['name'] == 'numbers.csv'
    assert 'HPG | 12345' in str(result['files'][0]['sections'])
    generate.assert_not_called()


def test_two_file_count_and_combined_size_are_enforced(monkeypatch):
    from app.ai import attachment_router as module
    uploads = [('files', (f'{i}.txt', b'hello')) for i in range(3)]
    assert client.post('/api/ai/files/extract', files=uploads).status_code == 400
    monkeypatch.setattr(module, 'MAX_FILE_BYTES', 10)
    response = client.post('/api/ai/files/extract', files=[('files', ('a.txt', b'123456')), ('files', ('b.txt', b'123456'))])
    assert response.status_code == 413
    assert '20 MB' in response.json()['detail']


def test_upload_has_ai_rate_limit_and_separate_body_limit():
    assert resolve_policy('POST', '/api/ai/files/extract').tier == 'ai'
    middleware = MaxBodySizeMiddleware(app)
    assert middleware._limit_for('/api/ai/files/extract') > 20 * 1024 * 1024
    assert middleware._limit_for('/api/ai/chat') == 256 * 1024
