# Docling extraction API

Start from this directory with `uv run python main.py` (localhost:9102).
See [shared setup and API smoke tests](../README.md).

Python 3.12, uv, NVIDIA CUDA, direct PaddleOCR PP-OCRv5, Heron layout and
TableFormer accurate table extraction. No RapidOCR or result cache.

```bash
uv sync --locked
cp .env.example .env
uv run uvicorn src.main:app --host 127.0.0.1 --port 9102 --workers 1
```

The lock uses PaddlePaddle's official CUDA 12.6 package index. Install a compatible
NVIDIA driver and runtime before starting. GPU frameworks and model weights are
large. First startup downloads model assets; retain their standard model directories
for subsequent starts. Startup initializes both PDF and image pipelines; allow up
to `STARTUP_TIMEOUT` seconds. `/health/ready` returns 503 if initialization fails;
restart after correcting configuration. `/health/live` remains available. Use one
Uvicorn process per GPU allocation. Bind only to a trusted private network: this
service has no authentication. Docs are enabled only in local/staging environments.

```bash
curl http://localhost:9102/v1/extractions \
  -F file=@document.pdf \
  -F include_elements=true \
  -F save_excel=false \
  -F save_images=false
```

The response contains `markdown`, `metadata`, `elements` (native Docling document
JSON including its version, or null), `excel_files`, and `images`. Metadata reports
UTC request/response assembly times, elapsed milliseconds, sanitized options,
filename, media type, SHA-256, request ID, and page count. Transmission time is
excluded. Files are limited to PDF, PNG, JPEG and single-frame TIFF. Defaults:
50 MiB, 200 PDF pages, 40 megapixels, 300-second worker deadline. One active
conversion is permitted; additional requests receive 503 with Retry-After.

S3 is contacted only when an export is requested. Settings load from `../.env`,
then this directory's `.env`, then process environment (highest precedence):
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`.
Use an existing bucket with PutObject/GetObject/DeleteObject permissions.
Exports use `docling/{UTC_ddmmyyyy}_{file_sha256}/excel/` or `img/` with unique
request IDs in filenames. One workbook contains one sheet per table. Artifact
entries contain S3 locations and one-hour presigned URLs. No tables or pictures
means an empty list. Temporary files are removed after requests; failed exports
attempt deletion of completed uploads. Forced process termination can leave S3
objects; configure a bucket lifecycle policy if automatic eventual cleanup is needed.

Set `VLM_ENABLED=true` and `OPENROUTER_API_KEY` to describe detected figures with
`xiaomi/mimo-v2.6-flash`. Model, prompt and timeout are configurable. Enabled
upstream failures fail the extraction. VLM is not a full-page extraction engine.

Errors: 413 resource limit, 415 unsupported media, 422 invalid input/document,
502 S3/OpenRouter failure, 503 busy/unavailable worker or missing S3 configuration,
504 conversion deadline. Timed-out/crashed workers are terminated and replaced.

## Verification

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
```

API tests override the worker dependency and require no GPU/external calls.
GPU inference, OCR coordinate accuracy on real scans, layout/table quality,
real AWS exports, and OpenRouter descriptions remain UNVERIFIED until smoke-tested
on the deployment host. Do not mark the roadmap complete until these pass.

### World Bank fixture

The supplied `tests/world_bank_data_annual_2024.pdf` has 49 pages. Run the real
pipeline test (allows 30 minutes for model initialization and extraction):

```bash
RUN_GPU_INTEGRATION=1 uv run pytest tests/test_world_bank_integration.py -s -q
```

It checks page count, report title, detected tables and disabled S3 exports, then
writes `tests/artifacts/world_bank_2024.md` and `.json` for review. These generated
artifacts are ignored. This test does not exercise S3 or OpenRouter.

Current verification: lightweight API/OCR-adapter/workbook tests pass and the
service wheel builds. Real fixture extraction is UNVERIFIED: runtime installation
failed after retries with connection timeouts to the PaddlePaddle GPU wheel CDN
and NVIDIA wheel downloads. Host GPU detection succeeded (RTX 3050, 4 GiB).
