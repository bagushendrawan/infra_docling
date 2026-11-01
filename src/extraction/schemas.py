from typing import Any

from pydantic import BaseModel


class ExtractionResponse(BaseModel):
    markdown: str
    metadata: dict[str, Any]
    elements: dict[str, Any] | None = None
    excel_files: list[dict[str, Any]]
    images: list[dict[str, Any]]
