import sys
from types import SimpleNamespace

import numpy as np
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling_core.types.doc import BoundingBox, CoordOrigin
from PIL import Image

from src.extraction.ocr import PaddleModel, PaddleOptions


def test_paddle_mapping(monkeypatch):
    calls = []

    class PaddleOCR:
        def __init__(self, **options):
            calls.append(options)

        def predict(self, image):
            assert image.shape == (30, 30, 3)
            yield {
                "rec_texts": ["Hello"],
                "rec_scores": [0.98],
                "rec_polys": [np.array([[0, 0], [30, 0], [30, 15], [0, 15]])],
            }

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=PaddleOCR))
    engine = PaddleModel(
        enabled=True,
        artifacts_path=None,
        options=PaddleOptions(),
        accelerator_options=AcceleratorOptions(),
    )
    box = BoundingBox(l=10, t=20, r=20, b=30, coord_origin=CoordOrigin.TOPLEFT)
    monkeypatch.setattr(engine, "get_ocr_rects", lambda page: [box])
    merged = []
    monkeypatch.setattr(
        engine, "post_process_cells", lambda cells, page, result: merged.extend(cells)
    )
    backend = SimpleNamespace(
        is_valid=lambda: True, get_page_image=lambda **kw: Image.new("RGB", (30, 30))
    )
    page = SimpleNamespace(_backend=backend)
    assert list(engine(object(), [page])) == [page]
    assert merged[0].text == "Hello"
    bounds = merged[0].rect.to_bounding_box()
    assert (bounds.l, bounds.t, bounds.r, bounds.b) == (10, 20, 20, 25)
    assert calls[0]["text_recognition_model_name"] == "en_PP-OCRv5_mobile_rec"
