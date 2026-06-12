from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import models

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "counts": {
            "categories": db.query(models.DeviceCategory).count(),
            "manufacturers": db.query(models.Manufacturer).count(),
            "models": db.query(models.DeviceModel).count(),
            "variants": db.query(models.ModelVariant).count(),
            "submissions": db.query(models.ResourceSubmission).count(),
            "unmatched": db.query(models.UnmatchedModel).filter(models.UnmatchedModel.status == "pending").count(),
        },
        "recent_unmatched": db.query(models.UnmatchedModel).order_by(models.UnmatchedModel.count.desc()).limit(20).all(),
    }
