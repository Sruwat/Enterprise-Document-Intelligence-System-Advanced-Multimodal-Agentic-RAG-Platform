from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth_context import get_current_user
from app.core.schemas import UserRecord
from app.services.industry_packs import list_industry_packs

router = APIRouter(prefix="/industry-packs", tags=["industry-packs"])


@router.get("")
def industry_packs(_: UserRecord = Depends(get_current_user)) -> list[dict]:
    return list_industry_packs()
