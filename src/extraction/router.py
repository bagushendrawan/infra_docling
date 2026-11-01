import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.extraction.config import Settings
from src.extraction.dependencies import get_worker
from src.extraction.exceptions import ExtractionError
from src.extraction.schemas import ExtractionResponse

router = APIRouter()


def validate_file(path, settings):
    with path.open("rb") as stream:
        signature = stream.read(8)
    if signature.startswith(b"%PDF-"):
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionError(422, "Encrypted PDFs are unsupported")
            pages = len(reader.pages)
        except PdfReadError as exc:
            raise ExtractionError(422, "Invalid PDF") from exc
        if not pages or pages > settings.max_pages:
            raise ExtractionError(413, "PDF page limit exceeded")
        return "application/pdf"
    try:
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG", "TIFF"}:
                raise ExtractionError(415, "Unsupported image format")
            if image.width * image.height > settings.max_image_pixels:
                raise ExtractionError(413, "Image pixel limit exceeded")
            if getattr(image, "n_frames", 1) != 1:
                raise ExtractionError(422, "Only single-frame images are supported")
            image.verify()
            return Image.MIME[image.format]
    except UnidentifiedImageError as exc:
        raise ExtractionError(415, "Expected a PDF, PNG, JPEG, or TIFF") from exc
    except (OSError, Image.DecompressionBombError) as exc:
        raise ExtractionError(422, "Invalid image") from exc


@router.post(
    "/v1/extractions",
    response_model=ExtractionResponse,
    tags=["extraction"],
    summary="Extract one PDF or image",
    description="Returns Markdown and request metadata. Optionally includes native Docling JSON and uploads a table workbook or figures to AWS S3.",
    responses={
        code: {"description": description}
        for code, description in {
            413: "Upload, page, or pixel limit exceeded",
            415: "Unsupported media",
            422: "Invalid request or document",
            502: "Storage or VLM failure",
            503: "Worker busy or unavailable",
            504: "Extraction deadline exceeded",
        }.items()
    },
)
async def extract(
    request: Request,
    worker: Annotated[object, Depends(get_worker)],
    file: Annotated[UploadFile, File()],
    include_elements: Annotated[bool, Form()] = False,
    save_excel: Annotated[bool, Form()] = False,
    save_images: Annotated[bool, Form()] = False,
):
    settings = Settings()
    options = dict(
        include_elements=include_elements,
        save_excel=save_excel,
        save_images=save_images,
    )
    request.state.payload = options
    request.state.filename = Path((file.filename or "upload").replace("\\", "/")).name
    with TemporaryDirectory(prefix="docling-") as directory:
        path = Path(directory) / "input"
        digest = hashlib.sha256()
        size = 0

        # UploadFile and disk operations run in the threadpool.
        def write_chunk(chunk):
            with path.open("ab") as stream: 
                stream.write(chunk)

        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                raise ExtractionError(413, "Upload size limit exceeded")
            digest.update(chunk)
            await run_in_threadpool(write_chunk, chunk)
        if not size:
            raise ExtractionError(422, "Empty upload")
        request.state.media_type = await run_in_threadpool(
            validate_file, path, settings
        )
        request.state.fingerprint = digest.hexdigest()
        result = await worker.extract(
            str(path), options, request.state.request_id, digest.hexdigest()
        )
        request.state.pages = result.pop("pages")
        return result | {"metadata": request.app.state.metadata(request, 200)}
