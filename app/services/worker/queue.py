from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkerJob:
    job_type: str
    payload: dict[str, Any]
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "payload": self.payload,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerJob":
        return cls(
            job_id=payload.get("job_id") or str(uuid.uuid4()),
            job_type=payload["job_type"],
            payload=payload.get("payload") or {},
            attempts=int(payload.get("attempts") or 0),
            max_attempts=int(payload.get("max_attempts") or 3),
            created_at=float(payload.get("created_at") or time.time()),
        )


class WorkerQueue:
    def __init__(self, redis_service=None, queue_name: str = "aiwana:worker:jobs") -> None:
        self.redis_service = redis_service
        self.queue_name = queue_name
        self._local: list[dict[str, Any]] = []

    def enqueue(self, job_type: str, payload: dict[str, Any], *, job_id: str | None = None, max_attempts: int = 3) -> WorkerJob:
        job = WorkerJob(job_type=job_type, payload=payload, job_id=job_id or str(uuid.uuid4()), max_attempts=max_attempts)
        if self.redis_service is None or not self.redis_service.enqueue_json(self.queue_name, job.to_dict()):
            self._local.append(job.to_dict())
        return job

    def dequeue(self) -> WorkerJob | None:
        payload = None
        if self.redis_service is not None:
            payload = self.redis_service.dequeue_json(self.queue_name, timeout_seconds=1)
        if payload is None and self._local:
            payload = self._local.pop(0)
        return WorkerJob.from_dict(payload) if payload else None

    def requeue(self, job: WorkerJob) -> None:
        job.attempts += 1
        if job.attempts < job.max_attempts:
            if self.redis_service is None or not self.redis_service.enqueue_json(self.queue_name, job.to_dict()):
                self._local.append(job.to_dict())

    def status(self) -> dict[str, Any]:
        redis_length = self.redis_service.queue_length(self.queue_name) if self.redis_service is not None else 0
        return {"queue_name": self.queue_name, "queued": redis_length + len(self._local), "redis_enabled": bool(getattr(self.redis_service, "enabled", False))}
