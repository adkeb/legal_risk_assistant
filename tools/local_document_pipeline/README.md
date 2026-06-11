# Local document pipeline

This folder contains a small CLI around the backend parser and Milvus ingestion
path. It uses the same `.env` values as the backend app, including embedding and
Milvus configuration.

Parse without writing vectors:

```bash
industry_information_assistant/backend/.venv/bin/python \
  tools/local_document_pipeline/parse_or_ingest.py --parse-only 数据库
```

Parse, embed, and insert into Milvus:

```bash
industry_information_assistant/backend/.venv/bin/python \
  tools/local_document_pipeline/parse_or_ingest.py 数据库 \
  --index kb_legal_risk_database
```

Useful OCR environment variables:

- `PADDLEOCR_VL_MODEL_DIR`: local PaddleOCR-VL-1.6 directory. Defaults to
  `models/PaddleOCR-VL-1.6` under the repository root.
- `PADDLEOCR_USE_LAYOUT_DETECTION`: defaults to `false` to avoid downloading the
  extra layout model. Set to `true` only after the layout model is available.
- `LOCAL_OCR_DPI`: PDF render DPI for OCR. Defaults to `200`.
- `LOCAL_OCR_MAX_PAGES`: `0` means OCR all rendered PDF pages.
