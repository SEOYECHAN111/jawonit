from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session
from app.database import get_db
from app import models
from app.schemas import ValuationRequest
from app.services.storage import get_object_storage
from app.services.valuation_engine import valuate, match_category, match_model

router = APIRouter(prefix="/api/v1/resources", tags=["resources"])


@router.post("/submit")
async def submit_resource(
    user_id: str = Form(""),
    item_text: str = Form(""),
    category_code: str = Form(""),
    manufacturer_text: str = Form(""),
    model_text: str = Form(""),
    condition_code: str = Form("unknown"),
    age_code: str = Form("unknown"),
    security_code: str = Form("unknown"),
    quantity: int = Form(1),
    memo: str = Form(""),
    owner_confirmed: bool = Form(False),
    data_confirmed: bool = Form(False),
    not_stolen_confirmed: bool = Form(False),
    photo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    photo_url = None
    if photo and photo.filename:
        saved = get_object_storage().upload_fileobj(photo.file, photo.filename, photo.content_type)
        photo_url = saved["url"]

    req = ValuationRequest(
        user_id=user_id or None,
        item_text=item_text,
        category_code=category_code or None,
        manufacturer_text=manufacturer_text or None,
        model_text=model_text or None,
        condition_code=condition_code,
        age_code=age_code,
        security_code=security_code,
        quantity=quantity,
        memo=memo,
        owner_confirmed=owner_confirmed,
        data_confirmed=data_confirmed,
        not_stolen_confirmed=not_stolen_confirmed,
    )
    cat, _ = match_category(db, req)
    model, variant, _ = match_model(db, cat.id if cat else None, req)
    valuation = valuate(db, req)

    submission = models.ResourceSubmission(
        user_id=user_id or None,
        category_id=cat.id if cat else None,
        matched_model_id=model.id if model else None,
        matched_variant_id=variant.id if variant else None,
        item_text=item_text,
        manufacturer_text=manufacturer_text,
        model_text=model_text,
        condition_code=condition_code,
        age_code=age_code,
        security_code=security_code,
        quantity=quantity,
        memo=memo,
        photo_url=photo_url,
        status="needs_admin_review" if valuation["requires_admin_review"] else "valuated",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    result = models.ValuationResult(
        submission_id=submission.id,
        estimated_low=valuation["estimated_low"],
        estimated_high=valuation["estimated_high"],
        route=valuation["route"],
        matched_confidence=valuation["matched_confidence"],
        requires_admin_review=valuation["requires_admin_review"],
        calculation_snapshot=valuation["snapshot"],
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return {"ok": True, "submission_id": submission.id, "photo_url": photo_url, "valuation": valuation}


@router.get("/submissions")
def submissions(db: Session = Depends(get_db)):
    rows = db.query(models.ResourceSubmission).order_by(models.ResourceSubmission.created_at.desc()).limit(200).all()
    return {"ok": True, "items": rows}
