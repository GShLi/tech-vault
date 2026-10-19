import os
from pathlib import Path
from shutil import copyfileobj
from typing import NamedTuple


def _uploads_dir() -> Path:
    return Path(os.getenv("TECHVAULT_UPLOAD_DIR", "data/uploads"))


class StoredFile(NamedTuple):
    path: Path
    size_bytes: int


def store_file(stream, file_name: str, identifier: str) -> StoredFile:
    directory = _uploads_dir() / identifier[:4]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / file_name
    with destination.open("wb") as target:
        copyfileobj(stream, target)
    size = destination.stat().st_size
    return StoredFile(path=destination, size_bytes=size)


def remove_file(stored: StoredFile) -> None:
    stored.path.unlink(missing_ok=True)
