from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.schemas import CategoryIn, DeviceModelIn, ManufacturerIn, RuleIn, ValuationRequest, VariantIn
from app.services.valuation_engine import valuate

router = APIRouter(prefix="/api/v1/electronics", tags=["electronics"])


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "categories": db.query(models.DeviceCategory).all(),
        "manufacturers": db.query(models.Manufacturer).all(),
        "models": db.query(models.DeviceModel).limit(300).all(),
        "rules": db.query(models.ValuationRule).all(),
    }


@router.post("/manufacturers")
def create_manufacturer(data: ManufacturerIn, db: Session = Depends(get_db)):
    row = models.Manufacturer(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "manufacturer": row}


@router.post("/categories")
def create_category(data: CategoryIn, db: Session = Depends(get_db)):
    row = models.DeviceCategory(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "category": row}


@router.post("/models")
def create_model(data: DeviceModelIn, db: Session = Depends(get_db)):
    row = models.DeviceModel(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "model": row}


@router.post("/variants")
def create_variant(data: VariantIn, db: Session = Depends(get_db)):
    if not db.get(models.DeviceModel, data.model_id):
        raise HTTPException(404, "모델을 찾을 수 없습니다.")
    row = models.ModelVariant(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "variant": row}


@router.post("/rules")
def create_rule(data: RuleIn, db: Session = Depends(get_db)):
    row = models.ValuationRule(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "rule": row}


@router.post("/valuate")
def valuate_item(data: ValuationRequest, db: Session = Depends(get_db)):
    return valuate(db, data)


@router.get("/unmatched")
def unmatched(db: Session = Depends(get_db)):
    rows = db.query(models.UnmatchedModel).order_by(models.UnmatchedModel.count.desc()).limit(200).all()
    return {"ok": True, "items": rows}
