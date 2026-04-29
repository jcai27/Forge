from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_inventory_events: list[dict] = []


class InventoryAdjustment(BaseModel):
    sku: str = Field(min_length=1)
    warehouse_id: str = Field(min_length=1)
    delta: int
    reason: str = Field(min_length=1)


@router.get("/health")
def healthcheck():
    return {"status": "starter-ok"}


@router.get("/inventory/adjustments")
def list_adjustments():
    return {"items": _inventory_events}


@router.post("/inventory/adjustments")
def create_adjustment(adjustment: InventoryAdjustment):
    if adjustment.delta == 0:
        raise HTTPException(status_code=400, detail="delta must not be zero")
    event = adjustment.model_dump()
    _inventory_events.append(event)
    return {"item": event}

