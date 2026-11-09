"""The web API: accept an upload, queue it, and return the result later.

The API never analyses anything itself. It stores the file, leaves a note on
the queue and replies straight away, so a slow scan cannot tie up the website.
"""

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import FastAPI, File, HTTPException, Path as PathParam, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.filetypes import HEADER_BYTES, sniff
from app.shared import scans
from app.shared.aws import connect
from app.shared.config import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("trueframe.api")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ScanId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]

# Extra room for the multipart wrapper around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = Settings.from_env()
    app.state.aws = connect(app.state.settings)
    yield


app = FastAPI(title="TrueFrame", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def reject_oversized_uploads(request: Request, call_next):
    """Refuse a too-large upload from its headers, before reading the body."""
    if request.url.path == "/api/scans":
        length = request.headers.get("content-length", "")
        limit = request.app.state.settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
        if length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "That file is too large."}, status_code=413)
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/scans", status_code=202)
def create_scan(request: Request, file: UploadFile = File(...)) -> dict:
    settings = request.app.state.settings
    aws = request.app.state.aws

    if file.size is not None and file.size > settings.max_upload_bytes:
        raise HTTPException(413, "That file is too large.")

    header = file.file.read(HEADER_BYTES)
    file.file.seek(0)
    media_type = sniff(header)
    if media_type is None:
        raise HTTPException(415, "Please upload a JPEG, PNG, WebP, MP4, MOV or WebM file.")

    scan_id = uuid.uuid4().hex
    s3_key = f"uploads/{scan_id}"

    aws.s3.upload_fileobj(
        file.file, settings.bucket, s3_key, ExtraArgs={"ContentType": media_type}
    )
    scans.create(aws.table, scan_id, file.filename or "upload", media_type, s3_key)
    try:
        aws.sqs.send_message(
            QueueUrl=settings.queue_url,
            MessageBody=json.dumps(
                {"scan_id": scan_id, "s3_key": s3_key, "media_type": media_type}
            ),
        )
    except ClientError:
        log.exception("Could not queue scan %s", scan_id)
        scans.mark_failed(aws.table, scan_id, "The scan could not be queued. Please try again.")
        raise HTTPException(503, "The scan could not be queued. Please try again.") from None

    log.info("Queued scan %s (%s)", scan_id, media_type)
    return {"scan_id": scan_id, "status": scans.QUEUED}


@app.get("/api/scans/{scan_id}")
def read_scan(request: Request, scan_id: ScanId) -> dict:
    scan = scans.get(request.app.state.aws.table, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found. Scans are deleted after 24 hours.")
    return {
        "scan_id": scan_id,
        "status": scan["status"],
        "filename": scan["filename"],
        "media_type": scan["media_type"],
        "report": json.loads(scan["report"]) if "report" in scan else None,
        "error": scan.get("error"),
    }


@app.get("/api/scans/{scan_id}/frames/{index}")
def read_frame(
    request: Request,
    scan_id: ScanId,
    index: Annotated[int, PathParam(ge=0, le=1000)],
) -> Response:
    aws = request.app.state.aws
    try:
        obj = aws.s3.get_object(
            Bucket=request.app.state.settings.bucket, Key=f"frames/{scan_id}/{index}.jpg"
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            raise HTTPException(404, "Frame not found.") from None
        raise
    return Response(content=obj["Body"].read(), media_type="image/jpeg")


# Must come last: anything not matched above is treated as a web page.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
