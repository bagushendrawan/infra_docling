import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from openpyxl import Workbook

from src.extraction.exceptions import ExtractionError


class Converter:
    def __init__(self, settings):
        import paddle
        import torch
        from docling.datamodel import layout_model_specs
        from docling.datamodel.accelerator_options import AcceleratorOptions
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
        )
        from docling.document_converter import (
            DocumentConverter,
            ImageFormatOption,
            PdfFormatOption,
        )

        from src.extraction.ocr import PaddleOptions

        self.settings = settings
        if settings.docling_device.startswith("cuda") and (
            not torch.cuda.is_available()
            or not paddle.is_compiled_with_cuda()
            or not paddle.device.cuda.device_count()
        ):
            raise RuntimeError(
                "Both PyTorch and PaddlePaddle require a working CUDA device"
            )
        if settings.vlm_enabled and not settings.openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY required when VLM_ENABLED=true")
        options = PdfPipelineOptions(
            allow_external_plugins=True,
            do_ocr=True,
            do_table_structure=True,
            generate_picture_images=True,
        )
        options.accelerator_options = AcceleratorOptions(device=settings.docling_device)
        options.layout_options.model_spec = layout_model_specs.DOCLING_LAYOUT_HERON
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        options.ocr_options = PaddleOptions(
            detection=settings.paddle_det_model,
            recognition=settings.paddle_rec_model,
            device=settings.docling_device.replace("cuda", "gpu"),
        )
        self.converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options),
                InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
            }
        )
        self.converter.initialize_pipeline(InputFormat.PDF)
        self.converter.initialize_pipeline(InputFormat.IMAGE)

    def extract(self, path, options, request_id, fingerprint):
        from docling.datamodel.base_models import DocumentStream
        from docling_core.types.doc import ImageRefMode, PictureDescriptionData

        settings = self.settings
        s3 = None
        if options["save_excel"] or options["save_images"]:
            if not all(
                (
                    settings.s3_bucket_name,
                    settings.aws_region,
                    settings.aws_access_key_id,
                    settings.aws_secret_access_key,
                )
            ):
                raise ExtractionError(503, "S3 configuration is incomplete")
            s3 = boto3.client(
                "s3",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.aws_secret_access_key.get_secret_value(),
            )
        raw = Path(path).read_bytes()
        source = DocumentStream(
            name="input.pdf" if raw.startswith(b"%PDF-") else "input.png",
            stream=BytesIO(raw),
        )
        result = self.converter.convert(source, raises_on_error=False)
        if result.status.value != "success":
            raise ExtractionError(422, "Document conversion failed or was incomplete")
        doc = result.document
        prefix = f"docling/{datetime.now(UTC):%d%m%Y}_{fingerprint}"
        uploaded = []

        def upload(data, name, content_type):
            key = f"{prefix}/{name}"
            s3.put_object(
                Bucket=settings.s3_bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            uploaded.append(key)
            return dict(
                bucket=settings.s3_bucket_name,
                key=key,
                uri=f"s3://{settings.s3_bucket_name}/{key}",
                content_type=content_type,
                download_url=s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.s3_bucket_name, "Key": key},
                    ExpiresIn=3600,
                ),
            )

        try:
            images = []
            for index, picture in enumerate(doc.pictures):
                image = picture.get_image(doc)
                if image is None:
                    continue
                buffer = BytesIO()
                image.save(buffer, "PNG")
                if settings.vlm_enabled:
                    with httpx.Client(timeout=settings.vlm_timeout) as client:
                        response = client.post(
                            "https://openrouter.ai/api/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}"
                            },
                            json={
                                "model": settings.openrouter_model,
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": settings.vlm_prompt,
                                            },
                                            {
                                                "type": "image_url",
                                                "image_url": {
                                                    "url": "data:image/png;base64,"
                                                    + base64.b64encode(
                                                        buffer.getvalue()
                                                    ).decode()
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                        )
                        response.raise_for_status()
                        description = response.json()["choices"][0]["message"][
                            "content"
                        ]
                        picture.annotations.append(
                            PictureDescriptionData(
                                text=description, provenance=settings.openrouter_model
                            )
                        )
                if options["save_images"]:
                    images.append(
                        upload(
                            buffer.getvalue(),
                            f"img/{request_id}_{index + 1}.png",
                            "image/png",
                        )
                        | {
                            "element_id": picture.self_ref,
                            "pages": [p.page_no for p in picture.prov],
                        }
                    )
            excel = []
            if options["save_excel"] and doc.tables:
                workbook = Workbook()
                workbook.remove(workbook.active)
                for index, table in enumerate(doc.tables):
                    sheet = workbook.create_sheet(f"table_{index + 1}")
                    frame = table.export_to_dataframe(doc=doc)
                    sheet.append([str(column) for column in frame.columns])
                    for row in frame.itertuples(index=False, name=None):
                        sheet.append(list(row))
                    for row in sheet:
                        for cell in row:
                            if cell.data_type == "f":
                                cell.data_type = "s"
                buffer = BytesIO()
                workbook.save(buffer)
                excel.append(
                    upload(
                        buffer.getvalue(),
                        f"excel/{request_id}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                )
            return dict(
                markdown=doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER),
                elements=doc.export_to_dict() if options["include_elements"] else None,
                excel_files=excel,
                images=images,
                pages=len(doc.pages),
            )
        except (
            BotoCoreError,
            ClientError,
            httpx.HTTPError,
            KeyError,
            ValueError,
        ) as exc:
            for key in uploaded:
                try:
                    s3.delete_object(Bucket=settings.s3_bucket_name, Key=key)
                except (BotoCoreError, ClientError):
                    pass
            raise ExtractionError(
                502, "Artifact storage or figure description failed"
            ) from exc
