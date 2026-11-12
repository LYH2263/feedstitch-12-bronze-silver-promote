from fastapi import APIRouter, HTTPException

from app.schemas.entities import PromotionRequest
from app.services import promotion_service

router = APIRouter(tags=["promotions"])


@router.get("/promotions")
def list_promotions():
    return promotion_service.list_promotions()


@router.get("/promotions/{batch_id}")
def get_promotion(batch_id: int):
    row = promotion_service.get_promotion(batch_id)
    if not row:
        raise HTTPException(404, "promotion batch not found")
    return row


@router.post("/promotions")
def create_promotion(body: PromotionRequest | None = None):
    try:
        return promotion_service.promote(run_id=body.run_id if body else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
