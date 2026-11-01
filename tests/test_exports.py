from io import BytesIO
from types import SimpleNamespace

from docling_core.types.doc import DoclingDocument, TableCell, TableData
from openpyxl import load_workbook

from src.extraction.config import Settings
from src.extraction.service import Converter


def test_workbook_and_disabled_storage(tmp_path, monkeypatch):
    doc = DoclingDocument(name="test")
    for _ in range(2):
        cells = [
            TableCell(
                text=text,
                start_row_offset_idx=row,
                end_row_offset_idx=row + 1,
                start_col_offset_idx=0,
                end_col_offset_idx=1,
                column_header=row == 0,
            )
            for row, text in enumerate(["Header", "=1+1"])
        ]
        doc.add_table(data=TableData(num_rows=2, num_cols=1, table_cells=cells))
    converter = Converter.__new__(Converter)
    converter.settings = Settings(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        aws_region="us-east-1",
        s3_bucket_name="test",
    )
    converter.converter = SimpleNamespace(
        convert=lambda *a, **kw: SimpleNamespace(
            status=SimpleNamespace(value="success"), document=doc
        )
    )
    source = tmp_path / "source"
    source.write_bytes(b"%PDF-fake")
    stored = []

    class S3:
        def put_object(self, **kwargs):
            stored.append(kwargs)

        def generate_presigned_url(self, *a, **kw):
            return "https://example.test/download"

    monkeypatch.setattr("boto3.client", lambda *a, **kw: S3())
    result = converter.extract(
        source,
        dict(include_elements=True, save_excel=False, save_images=False),
        "request",
        "hash",
    )
    assert stored == []
    assert len(result["elements"]["tables"]) == 2
    result = converter.extract(
        source,
        dict(include_elements=False, save_excel=True, save_images=False),
        "request",
        "hash",
    )
    assert len(stored) == len(result["excel_files"]) == 1
    assert "/excel/request.xlsx" in stored[0]["Key"]
    workbook = load_workbook(BytesIO(stored[0]["Body"]))
    assert workbook.sheetnames == ["table_1", "table_2"]
    assert workbook.active["A1"].value == "Header"
    assert workbook.active["A2"].value == "=1+1"
    assert workbook.active["A2"].data_type == "s"
