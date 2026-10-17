from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from threadit.core import ApiError, now, session
from threadit.views import attachment_json

router = APIRouter()

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _too_large() -> ApiError:
    return ApiError(
        413, "too_large", f"Attachment exceeds {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB."
    )


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_ATTACHMENT_BYTES:
        raise _too_large()
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_ATTACHMENT_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/attachments", status_code=201)
async def upload_attachment(
    request: Request, filename: str = Query(min_length=1, max_length=255)
):
    with session(request):
        pass  # authenticate before reading the body
    data = await _read_body(request)
    if not data:
        raise ApiError(422, "invalid_input", "Attachment body is empty.")
    content_type = (
        request.headers.get("content-type", "").strip()[:100] or "application/octet-stream"
    )
    with session(request, write=True) as (conn, user):
        attachment_id = conn.execute(
            "INSERT INTO attachments (uploader_id, filename, content_type, size, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], filename.strip() or "file", content_type, len(data), data, now()),
        ).lastrowid
        return attachment_json(
            conn.execute(
                "SELECT id, filename, content_type, size FROM attachments WHERE id = ?",
                (attachment_id,),
            ).fetchone()
        )


@router.get("/api/attachments/{attachment_id}")
def download_attachment(attachment_id: int, request: Request):
    with session(request) as (conn, _):
        row = conn.execute(
            "SELECT a.filename, a.content_type, a.data FROM attachments a"
            " LEFT JOIN messages m ON m.id = a.message_id"
            " WHERE a.id = ? AND m.deleted_at IS NULL",
            (attachment_id,),
        ).fetchone()
    if row is None:
        raise ApiError(404, "attachment_not_found", f"Attachment {attachment_id} does not exist.")
    inline = row["content_type"].split(";")[0].strip().lower() in INLINE_TYPES
    disposition = "inline" if inline else "attachment"
    return Response(
        row["data"],
        media_type=row["content_type"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row['filename'])}",
        },
    )
