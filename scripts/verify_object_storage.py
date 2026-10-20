"""Live verification of the MinIO upload, download and delete lifecycle.

Requires the Docker Compose MinIO service on :59000.
Run: .venv/bin/python scripts/verify_object_storage.py
"""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from backend.app.api.storage import (
    delete_s3_object,
    download_s3_object,
    presign_s3_download_url,
    put_s3_object,
)
from backend.app.core.config import Settings


def main() -> None:
    settings = Settings(
        environment="development",
        minio_url="http://127.0.0.1:59000",
        minio_public_url="http://127.0.0.1:59000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        minio_bucket="techvault",
        object_storage_enabled=True,
    )
    object_uri = "s3://techvault/lifecycle-checks/{0}.md".format(
        int(time.time() * 1000)
    )
    payload = b"# Object storage lifecycle\n\nverified\n"

    with TemporaryDirectory(prefix="techvault-object-storage-") as temp_dir:
        root = Path(temp_dir)
        source = root / "source.md"
        downloaded = root / "downloaded.md"
        source.write_bytes(payload)

        put_s3_object(source, object_uri, settings)
        download_s3_object(object_uri, downloaded, settings)
        assert downloaded.read_bytes() == payload

        delete_s3_object(object_uri, settings)
        response = httpx.get(presign_s3_download_url(object_uri, settings))
        assert response.status_code == 404, response.text

    print("object storage upload/download/delete OK")


if __name__ == "__main__":
    main()
