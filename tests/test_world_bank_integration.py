"""Opt-in real GPU extraction; writes reviewable artifacts without S3/VLM calls."""

import json
import os
from pathlib import Path

import httpx
import pytest

from src.main import app


@pytest.mark.skipif(
    os.getenv("RUN_GPU_INTEGRATION") != "1",
    reason="Requires GPU runtime and model downloads",
)
async def test_world_bank_pdf(monkeypatch):
    monkeypatch.setenv("VLM_ENABLED", "false")
    monkeypatch.setenv("EXTRACTION_TIMEOUT", "1800")
    monkeypatch.setenv("STARTUP_TIMEOUT", "1800")
    path = Path(__file__).with_name("world_bank_data_annual_2024.pdf")
    async with app.router.lifespan_context(app):
        assert app.state.worker.ready, (
            "GPU model initialization failed; inspect worker logs"
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test", timeout=1900
        ) as client:
            with path.open("rb") as stream:
                response = await client.post(
                    "/v1/extractions",
                    files={"file": (path.name, stream, "application/pdf")},
                    data={"include_elements": "true"},
                )
            assert response.status_code == 200, response.text
            result = response.json()
    output = path.parent / "artifacts"
    output.mkdir(exist_ok=True)
    (output / "world_bank_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    (output / "world_bank_2024.md").write_text(result["markdown"])
    assert result["metadata"]["pages"] == 49
    assert "ANNUAL REPORT 2024" in result["markdown"].upper()
    assert result["elements"]["tables"], "Expected financial tables"
    assert result["excel_files"] == result["images"] == []
    print(
        f"pages=49 tables={len(result['elements']['tables'])} pictures={len(result['elements']['pictures'])} elapsed_ms={result['metadata']['elapsed_ms']}"
    )
