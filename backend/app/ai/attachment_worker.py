"""Disposable parser process; hard CPU/memory bounds contain complex documents."""
import json
import sys
from dataclasses import asdict


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform == 'linux':
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    from app.ai.attachments import MAX_FILE_BYTES, extract_document
    from fastapi import HTTPException
    try:
        data = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, 'Files must total 20 MB or less.')
        print(json.dumps({'document': asdict(extract_document(sys.argv[1], data))}))
    except HTTPException as exc:
        print(json.dumps({'error': exc.detail, 'status': exc.status_code}))
    except Exception:
        print(json.dumps({'error': 'The document could not be extracted.', 'status': 400}))


if __name__ == '__main__':
    main()
