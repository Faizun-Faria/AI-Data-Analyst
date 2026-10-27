"""The raw landing zone: a local folder by default, or an S3 bucket.

Files land under <source>/<batch_id>/<export name>. Local copies are written to a
temporary name and renamed into place, so a half-copied file never looks landed; an S3
object only appears once its upload completes.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol


class RawStore(Protocol):
    def put(self, path: Path, key: str) -> str:
        """Copy a local file into the zone under key; return where it landed."""
        ...


class LocalStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put(self, path: Path, key: str) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".part")
        shutil.copyfile(path, partial)
        os.replace(partial, dest)
        return dest.resolve().as_posix()


class S3Store:
    def __init__(self, uri: str) -> None:
        bucket, _, prefix = uri.removeprefix("s3://").partition("/")
        if not bucket:
            raise ValueError(f"no bucket in {uri!r}; expected s3://bucket/optional/prefix")
        self.bucket = bucket
        self.prefix = prefix.strip("/")

        import boto3  # only needed when landing in S3

        self.client = boto3.client("s3")

    def put(self, path: Path, key: str) -> str:
        object_key = f"{self.prefix}/{key}" if self.prefix else key
        self.client.upload_file(str(path), self.bucket, object_key)
        return f"s3://{self.bucket}/{object_key}"


def open_store(raw_uri: str) -> RawStore:
    if raw_uri.startswith("s3://"):
        return S3Store(raw_uri)
    return LocalStore(raw_uri)
