"""Small Cloud Storage helpers for note draft generation."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import storage


GCS_BUCKET = os.environ.get("GCS_BUCKET", "pomera-knowledge-data")


def _bucket():
    return storage.Client().bucket(GCS_BUCKET)


def load_json(path: str, default: Any) -> Any:
    blob = _bucket().blob(path)
    if not blob.exists():
        return default
    return json.loads(blob.download_as_text(encoding="utf-8"))


def save_json(path: str, data: Any) -> str:
    blob = _bucket().blob(path)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        content_type="application/json; charset=utf-8",
    )
    return f"gs://{GCS_BUCKET}/{path}"


def save_text(path: str, text: str) -> str:
    blob = _bucket().blob(path)
    blob.upload_from_string(text, content_type="text/markdown; charset=utf-8")
    return f"gs://{GCS_BUCKET}/{path}"
