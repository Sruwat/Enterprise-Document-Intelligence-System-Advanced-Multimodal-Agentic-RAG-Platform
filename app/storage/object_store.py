from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


class ObjectStore:
    """Small storage boundary for local development and private S3 deployments."""

    def __init__(self, *, backend: str = "local", local_root: str | Path = "data/artifacts", bucket: str | None = None, kms_key_id: str | None = None, client=None) -> None:
        self.backend = backend.lower()
        self.local_root = Path(local_root)
        self.bucket = bucket
        self.kms_key_id = kms_key_id
        self._client = client

    def key(self, *, tenant_id: str, workspace_id: str, document_id: str, name: str) -> str:
        safe_name = Path(name).name.replace(" ", "_")
        return f"tenants/{tenant_id}/workspaces/{workspace_id}/documents/{document_id}/{safe_name}"

    def put_file(self, path: str | Path, *, key: str, content_type: str | None = None) -> dict[str, Any]:
        source = Path(path)
        content_type = content_type or mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        if self.backend == "s3":
            client = self._s3_client()
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms_key_id} if self.kms_key_id else {"ServerSideEncryption": "AES256"}
            client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": content_type, **extra})
            return {"backend": "s3", "bucket": self.bucket, "key": key, "uri": f"s3://{self.bucket}/{key}"}
        target = self.local_root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return {"backend": "local", "path": str(target), "key": key}

    def delete(self, *, key: str, path: str | Path | None = None) -> dict[str, Any]:
        if self.backend == "s3":
            self._s3_client().delete_object(Bucket=self.bucket, Key=key)
            return {"status": "deleted", "backend": "s3", "key": key}
        target = Path(path) if path else self.local_root / key
        if target.exists():
            target.unlink()
            return {"status": "deleted", "backend": "local", "path": str(target)}
        return {"status": "not_found", "backend": "local", "path": str(target)}

    def signed_url(self, *, key: str, expires_seconds: int = 900) -> str:
        if self.backend != "s3":
            return str(self.local_root / key)
        return self._s3_client().generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_seconds)

    def _s3_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise RuntimeError("s3_backend_requires_boto3") from exc
            self._client = boto3.client("s3")
        if not self.bucket:
            raise RuntimeError("s3_backend_requires_bucket")
        return self._client
