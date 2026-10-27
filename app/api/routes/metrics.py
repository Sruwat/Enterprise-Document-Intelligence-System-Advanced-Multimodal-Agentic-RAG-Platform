from fastapi import APIRouter, Depends

from app.core.dependencies import get_evaluation_service

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics_snapshot(evaluation_service=Depends(get_evaluation_service)):
    return evaluation_service.metrics_snapshot()
