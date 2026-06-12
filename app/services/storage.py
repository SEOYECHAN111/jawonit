from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import BinaryIO
import boto3
from botocore.client import Config as BotoConfig
from app.core.config import get_settings

settings = get_settings()


class ObjectStorage:
    def upload_fileobj(self, fileobj: BinaryIO, filename: str, content_type: str | None = None) -> dict:
        raise NotImplementedError


class LocalStorage(ObjectStorage):
    def __init__(self):
        self.root = Path(settings.local_upload_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_fileobj(self, fileobj: BinaryIO, filename: str, content_type: str | None = None) -> dict:
        ext = Path(filename).suffix.lower()
        key = f"{uuid.uuid4().hex}{ext}"
        path = self.root / key
        with path.open("wb") as f:
            f.write(fileobj.read())
        return {"key": key, "url": f"/uploads/{key}", "storage": "local", "content_type": content_type}


class S3Storage(ObjectStorage):
    def __init__(self):
        self.bucket = settings.s3_bucket
        if not self.bucket:
            raise RuntimeError("S3_BUCKET is required")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def upload_fileobj(self, fileobj: BinaryIO, filename: str, content_type: str | None = None) -> dict:
        ext = Path(filename).suffix.lower()
        key = f"jawonitda/uploads/{uuid.uuid4().hex}{ext}"
        extra = {"ContentType": content_type or "application/octet-stream"}
        self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs=extra)
        base = settings.s3_public_base_url.rstrip("/") if settings.s3_public_base_url else ""
        url = f"{base}/{key}" if base else key
        return {"key": key, "url": url, "storage": "s3", "content_type": content_type}


def get_object_storage() -> ObjectStorage:
    if settings.object_storage_mode.lower() == "s3":
        return S3Storage()
    return LocalStorage()
