import httpx
import pytest

from src.extraction.dependencies import get_worker
from src.main import app


class Worker:
    ready = True

    async def extract(self, path, options, request_id, fingerprint):
        return dict(
            markdown="# Extracted",
            elements={} if options["include_elements"] else None,
            excel_files=[],
            images=[],
            pages=1,
        )


@pytest.fixture
async def client():
    app.dependency_overrides[get_worker] = lambda: Worker()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def test_image(client):
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (20, 20)).save(image, "PNG")
    response = await client.post(
        "/v1/extractions",
        files={"file": ("sample.png", image.getvalue())},
        data={"include_elements": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["markdown"] == "# Extracted"
    assert body["elements"] == {}
    assert body["metadata"]["response_code"] == 200
    assert body["metadata"]["filename"] == "sample.png"
    assert body["excel_files"] == body["images"] == []


async def test_invalid(client):
    response = await client.post(
        "/v1/extractions", files={"file": ("bad.txt", b"hello")}
    )
    assert response.status_code == 415
    assert response.json()["metadata"]["response_code"] == 415


async def test_missing_file(client):
    response = await client.post("/v1/extractions")
    assert response.status_code == 422


async def test_corrupt_pdf(client):
    response = await client.post(
        "/v1/extractions", files={"file": ("bad.pdf", b"%PDF-broken")}
    )
    assert response.status_code == 422


async def test_pdf_page_limit(client, monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter

    monkeypatch.setenv("MAX_PAGES", "1")
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.add_blank_page(100, 100)
    buffer = BytesIO()
    writer.write(buffer)
    response = await client.post(
        "/v1/extractions", files={"file": ("large.pdf", buffer.getvalue())}
    )
    assert response.status_code == 413


async def test_worker_busy():
    from src.extraction.config import Settings
    from src.extraction.exceptions import ExtractionError
    from src.extraction.worker import Worker

    worker = Worker(Settings())
    worker.ready = True
    worker.busy = True
    with pytest.raises(ExtractionError) as error:
        await worker.extract("unused")
    assert error.value.status == 503


async def test_worker_timeout_recovers():
    from src.extraction.config import Settings
    from src.extraction.exceptions import ExtractionError
    from src.extraction.worker import Worker

    class Connection:
        def send(self, args):
            pass

    class TimeoutWorker(Worker):
        async def receive(self, timeout):
            raise ExtractionError(504, "timeout")

        async def close(self):
            self.ready = False

        async def start(self):
            self.ready = True

    worker = TimeoutWorker(Settings())
    worker.ready = True
    worker.connection = Connection()
    with pytest.raises(ExtractionError) as error:
        await worker.extract("unused")
    assert error.value.status == 504
    assert worker.ready and not worker.busy
