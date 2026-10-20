import os
import unicodedata
from datetime import datetime, timezone
from hashlib import sha256
from hmac import new as new_hmac
from pathlib import Path
from typing import NamedTuple, Optional
from urllib.parse import quote, unquote, urlsplit

import httpx

from backend.app.core.config import Settings


def _uploads_dir() -> Path:
    return Path(os.getenv("TECHVAULT_UPLOAD_DIR", "data/uploads"))


class StoredFile(NamedTuple):
    path: Path
    size_bytes: int
    object_uri: Optional[str] = None
    content_sha256: str = ""


class StoragePresignUnavailable(RuntimeError):
    pass


class ObjectStorageUnavailable(RuntimeError):
    pass


class FileSizeLimitExceeded(RuntimeError):
    pass


def _aws_uri_encode(value: str, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def _presign_s3_url(
    method: str,
    source_uri: str,
    settings: Settings,
    endpoint: str,
    ttl_seconds: int,
    *,
    now: Optional[datetime] = None,
) -> str:
    source = urlsplit(source_uri or "")
    if source.scheme.lower() != "s3" or not source.netloc:
        raise StoragePresignUnavailable("Object storage URI is required.")
    if source.netloc != settings.minio_bucket:
        raise StoragePresignUnavailable("Object storage bucket is not configured.")

    object_key = unquote(source.path.lstrip("/"))
    object_segments = object_key.split("/")
    if not object_key or any(segment in {"", ".", ".."} for segment in object_segments):
        raise StoragePresignUnavailable("Object storage key is invalid.")

    parsed_endpoint = urlsplit(endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
    ):
        raise StoragePresignUnavailable("Object storage endpoint is invalid.")
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise StoragePresignUnavailable("Object storage credentials are unavailable.")

    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = timestamp.strftime("%Y%m%d")
    credential_scope = "{date}/{region}/s3/aws4_request".format(
        date=date_stamp,
        region=settings.s3_region,
    )

    endpoint_path = unquote(parsed_endpoint.path).rstrip("/")
    canonical_uri = _aws_uri_encode(
        "{prefix}/{bucket}/{key}".format(
            prefix=endpoint_path,
            bucket=settings.minio_bucket,
            key=object_key,
        ),
        safe="/-_.~",
    )
    query_values = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": settings.minio_access_key + "/" + credential_scope,
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(ttl_seconds),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = "&".join(
        "{name}={value}".format(
            name=_aws_uri_encode(name),
            value=_aws_uri_encode(value),
        )
        for name, value in sorted(query_values.items())
    )
    canonical_headers = "host:{host}\n".format(host=parsed_endpoint.netloc)
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            canonical_query,
            canonical_headers,
            "host",
            "UNSIGNED-PAYLOAD",
        ]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    date_key = new_hmac(
        ("AWS4" + settings.minio_secret_key).encode("utf-8"),
        date_stamp.encode("utf-8"),
        sha256,
    ).digest()
    region_key = new_hmac(date_key, settings.s3_region.encode("utf-8"), sha256).digest()
    service_key = new_hmac(region_key, b"s3", sha256).digest()
    signing_key = new_hmac(service_key, b"aws4_request", sha256).digest()
    signature = new_hmac(
        signing_key, string_to_sign.encode("utf-8"), sha256
    ).hexdigest()

    return "{scheme}://{host}{path}?{query}&X-Amz-Signature={signature}".format(
        scheme=parsed_endpoint.scheme,
        host=parsed_endpoint.netloc,
        path=canonical_uri,
        query=canonical_query,
        signature=signature,
    )


def presign_s3_download_url(
    source_uri: str,
    settings: Settings,
    *,
    now: Optional[datetime] = None,
) -> str:
    endpoint = settings.minio_public_url.strip() or settings.minio_url.strip()
    return _presign_s3_url(
        "GET",
        source_uri,
        settings,
        endpoint,
        settings.download_url_ttl_seconds,
        now=now,
    )


def put_s3_object(local_path: Path, source_uri: str, settings: Settings) -> None:
    try:
        url = _presign_s3_url(
            "PUT",
            source_uri,
            settings,
            settings.minio_url.strip(),
            300,
        )
        response = httpx.put(url, content=local_path.read_bytes(), timeout=60.0)
        if response.status_code < 200 or response.status_code >= 300:
            raise ObjectStorageUnavailable(
                "Object storage rejected the upload with HTTP {0}.".format(
                    response.status_code
                )
            )
    except ObjectStorageUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        raise ObjectStorageUnavailable("Object storage is unavailable.") from error


def download_s3_object(source_uri: str, destination: Path, settings: Settings) -> Path:
    try:
        url = _presign_s3_url(
            "GET",
            source_uri,
            settings,
            settings.minio_url.strip(),
            300,
        )
        response = httpx.get(url, timeout=60.0)
        if response.status_code != 200:
            raise ObjectStorageUnavailable(
                "Object storage returned HTTP {0}.".format(response.status_code)
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return destination
    except ObjectStorageUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        raise ObjectStorageUnavailable("Object storage is unavailable.") from error


def delete_s3_object(source_uri: str, settings: Settings) -> None:
    try:
        url = _presign_s3_url(
            "DELETE",
            source_uri,
            settings,
            settings.minio_url.strip(),
            300,
        )
        response = httpx.delete(url, timeout=60.0)
        if response.status_code not in {200, 202, 204}:
            raise ObjectStorageUnavailable(
                "Object storage rejected the delete with HTTP {0}.".format(
                    response.status_code
                )
            )
    except ObjectStorageUnavailable:
        raise
    except Exception as error:  # noqa: BLE001
        raise ObjectStorageUnavailable("Object storage is unavailable.") from error


def normalize_file_name(file_name: str) -> str:
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("A file name is required.")

    normalized = unicodedata.normalize("NFKC", file_name.strip())
    if (
        normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise ValueError("File names must not contain a path.")
    if normalized.endswith((" ", ".")):
        raise ValueError("File names must not end with a space or period.")
    if normalized != Path(normalized).name or normalized != normalized.rsplit("/", 1)[-1]:
        raise ValueError("File names must be a simple basename.")
    return normalized


def _contained_path(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Storage path escapes the upload directory.") from error
    return resolved


def store_file(
    stream,
    file_name: str,
    identifier: str,
    settings: Optional[Settings] = None,
    *,
    max_bytes: Optional[int] = None,
) -> StoredFile:
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("The maximum file size must not be negative.")
    configured_root = (
        os.getenv("TECHVAULT_UPLOAD_DIR")
        or (settings.upload_dir if settings is not None else str(_uploads_dir()))
    )
    root = Path(configured_root).expanduser().resolve()
    safe_name = normalize_file_name(file_name)
    directory = _contained_path(root, root / identifier[:4])
    directory.mkdir(parents=True, exist_ok=True)
    destination = _contained_path(root, directory / safe_name)
    digest = sha256()
    size = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                next_size = size + len(chunk)
                if max_bytes is not None and next_size > max_bytes:
                    raise FileSizeLimitExceeded(
                        "File exceeds the configured size limit."
                    )
                target.write(chunk)
                digest.update(chunk)
                size = next_size
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    object_uri = None
    if settings is not None and settings.object_storage_enabled:
        object_uri = "s3://{bucket}/documents/{identifier}/{name}".format(
            bucket=settings.minio_bucket,
            identifier=identifier,
            name=safe_name,
        )
        try:
            put_s3_object(destination, object_uri, settings)
        except ObjectStorageUnavailable:
            destination.unlink(missing_ok=True)
            raise
    return StoredFile(
        path=destination,
        size_bytes=size,
        object_uri=object_uri,
        content_sha256=digest.hexdigest(),
    )


def remove_file(stored: StoredFile) -> None:
    stored.path.unlink(missing_ok=True)
