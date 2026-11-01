from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT.parent / ".env", ROOT / ".env"), extra="ignore"
    )
    environment: str = "local"
    docling_device: str = "cuda:0"
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=200, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    extraction_timeout: float = Field(default=300, gt=0)
    startup_timeout: float = Field(default=600, gt=0)
    paddle_det_model: str = "PP-OCRv5_server_det"
    paddle_rec_model: str = "en_PP-OCRv5_mobile_rec"
    vlm_enabled: bool = False
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "xiaomi/mimo-v2.6-flash"
    vlm_timeout: float = Field(default=60, gt=0)
    vlm_prompt: str = "Describe this figure accurately for a Markdown document. Include visible labels and values."
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    aws_region: str | None = None
    s3_bucket_name: str | None = None
