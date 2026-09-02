"""Local extraction/preview only. This router never calls an AI provider."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile

from app.ai.attachments import MAX_FILES, MAX_FILE_BYTES, extract_in_worker
from app.security.concurrency import BoundedGate, GateTimeout

attachment_router = APIRouter(prefix='/api/ai/files', tags=['Document preview'])
_extraction_gate = BoundedGate('document_preview', 1)


@attachment_router.post('/extract')
async def extract_files(request: Request):
    if not request.headers.get('content-type', '').startswith('multipart/form-data'):
        raise HTTPException(415, 'Use multipart/form-data for file attachments.')
    documents = []
    try:
        async with _extraction_gate.acquire(5):
            async with request.form(max_files=MAX_FILES, max_fields=0) as form:
                uploads = form.getlist('files')
                if not 1 <= len(uploads) <= MAX_FILES or any(not isinstance(f, UploadFile) for f in uploads):
                    raise HTTPException(400, 'Attach one or two files.')
                if sum(upload.size or 0 for upload in uploads) > MAX_FILE_BYTES:
                    raise HTTPException(413, 'Files must total 20 MB or less.')
                total_bytes = 0
                for upload in uploads:
                    data = await upload.read(MAX_FILE_BYTES - total_bytes + 1)
                    total_bytes += len(data)
                    if total_bytes > MAX_FILE_BYTES:
                        raise HTTPException(413, 'Files must total 20 MB or less.')
                    doc = await extract_in_worker(upload.filename or 'document', data)
                    documents.append({
                        'name': doc.name, 'characters': doc.characters,
                        'warnings': doc.warnings[:10],
                        'sections': [{'location': location, 'text': text} for location, text in doc.sections],
                    })
    except GateTimeout:
        raise HTTPException(503, 'Document processing is busy. Please retry shortly.')
    return JSONResponse({'files': documents, 'analysis_enabled': False}, headers={'Cache-Control': 'no-store'})
