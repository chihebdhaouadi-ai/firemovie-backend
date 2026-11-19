"""Serves uploaded files during local development, with byte ranges.

Django's own development media view always sends the whole file. Video
players (AVPlayer on iOS in particular) ask for byte ranges and refuse a
video served without them, so chat videos would not play locally. In
production the files come from S3, which handles ranges itself; this view is
only wired up when DEBUG is on.
"""

import mimetypes
import os
import re

from django.http import FileResponse, Http404, HttpResponse
from django.utils._os import safe_join
from django.views.static import serve

_RANGE = re.compile(r'bytes=(\d*)-(\d*)$')


def serve_media(request, path, document_root):
    header = request.headers.get('Range', '')
    match = _RANGE.match(header.strip())
    if not match:
        return serve(request, path, document_root=document_root)
    try:
        full = safe_join(document_root, path)
    except ValueError:
        raise Http404
    if not os.path.isfile(full):
        raise Http404
    size = os.path.getsize(full)
    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    elif end_text:
        # "bytes=-N": the last N bytes.
        start = max(size - int(end_text), 0)
        end = size - 1
    else:
        return serve(request, path, document_root=document_root)
    end = min(end, size - 1)
    if start > end or start >= size:
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{size}'
        return response
    length = end - start + 1
    handle = open(full, 'rb')
    handle.seek(start)

    def chunks(remaining=length, block=64 * 1024):
        try:
            while remaining > 0:
                data = handle.read(min(block, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        finally:
            handle.close()

    content_type = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    response = FileResponse(chunks(), status=206, content_type=content_type)
    response['Content-Length'] = str(length)
    response['Content-Range'] = f'bytes {start}-{end}/{size}'
    response['Accept-Ranges'] = 'bytes'
    return response
