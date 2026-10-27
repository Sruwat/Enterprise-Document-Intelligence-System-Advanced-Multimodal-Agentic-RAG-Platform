from fastapi import APIRouter, Depends

from app.core.dependencies import get_evaluation_service
from app.core.schemas import EvaluationRunRequest

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/run")
def run_evaluation(request: EvaluationRunRequest, evaluation_service=Depends(get_evaluation_service)):
    return evaluation_service.run_seeded_evaluation(request.dataset_path, request.query_limit)


@router.post("/graph-lift")
def run_graph_lift_evaluation(request: EvaluationRunRequest, evaluation_service=Depends(get_evaluation_service)):
    return evaluation_service.run_graph_lift_evaluation(request.dataset_path)


@router.get("/summary")
def evaluation_summary(evaluation_service=Depends(get_evaluation_service)):
    return evaluation_service.summarize()


@router.get("/launch-gates")
def evaluation_launch_gates(evaluation_service=Depends(get_evaluation_service)):
    return evaluation_service.launch_gates()
