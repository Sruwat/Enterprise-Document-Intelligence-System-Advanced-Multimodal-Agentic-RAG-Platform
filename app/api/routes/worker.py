from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_context import get_current_user
from app.core.dependencies import get_aiwana_worker, get_worker_queue
from app.core.schemas import UserRecord

router = APIRouter(prefix="/worker", tags=["worker"])


@router.get("/health")
def worker_health(
    worker=Depends(get_aiwana_worker),
    queue=Depends(get_worker_queue),
    user: UserRecord = Depends(get_current_user),
):
    return {"worker": worker.heartbeat(), "queue": queue.status(), "user_id": user.user_id}
