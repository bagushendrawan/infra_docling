from typing import ClassVar, Literal

import numpy as np
from docling.datamodel.pipeline_options import OcrOptions
from docling.models.base_ocr_model import BaseOcrModel
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell
from pydantic import Field


class PaddleOptions(OcrOptions):
    kind: ClassVar[Literal["paddle_direct"]] = "paddle_direct"
    lang: list[str] = Field(default_factory=lambda: ["en"])
    detection: str = "PP-OCRv5_server_det"
    recognition: str = "en_PP-OCRv5_mobile_rec"
    device: str = "gpu:0"


class PaddleModel(BaseOcrModel):
    def __init__(self, enabled, artifacts_path, options, accelerator_options):
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        if enabled:
            from paddleocr import PaddleOCR

            self.reader = PaddleOCR(
                text_detection_model_name=options.detection,
                text_recognition_model_name=options.recognition,
                device=options.device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

    @classmethod
    def get_options_type(cls):
        return PaddleOptions

    def __call__(self, conv_res, page_batch):
        for page in page_batch:
            if self.enabled and page._backend and page._backend.is_valid():
                cells = []
                for box in self.get_ocr_rects(page):
                    if box.area() == 0:
                        continue
                    scale = 3.0
                    image = np.asarray(
                        page._backend.get_page_image(scale=scale, cropbox=box).convert(
                            "RGB"
                        )
                    )[:, :, ::-1]
                    for result in self.reader.predict(image):
                        for text, score, polygon in zip(
                            result["rec_texts"],
                            result["rec_scores"],
                            result["rec_polys"],
                            strict=True,
                        ):
                            points = np.asarray(polygon) / scale
                            bounds = (
                                float(points[:, 0].min()) + box.l,
                                float(points[:, 1].min()) + box.t,
                                float(points[:, 0].max()) + box.l,
                                float(points[:, 1].max()) + box.t,
                            )
                            cells.append(
                                TextCell(
                                    index=len(cells),
                                    text=text,
                                    orig=text,
                                    from_ocr=True,
                                    confidence=float(score),
                                    rect=BoundingRectangle.from_bounding_box(
                                        BoundingBox.from_tuple(
                                            bounds, origin=CoordOrigin.TOPLEFT
                                        )
                                    ),
                                )
                            )
                self.post_process_cells(cells, page, conv_res)
            yield page


def ocr_engines():
    return {"ocr_engines": [PaddleModel]}
