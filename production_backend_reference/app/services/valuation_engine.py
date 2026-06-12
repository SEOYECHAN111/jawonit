from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app import models
from app.schemas import ValuationRequest


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.92
    return SequenceMatcher(None, a, b).ratio()


def rule_factor(db: Session, rule_type: str, code: str, default: float = 1.0) -> tuple[float, str | None, str]:
    rule = (
        db.query(models.ValuationRule)
        .filter(models.ValuationRule.rule_type == rule_type, models.ValuationRule.code == code, models.ValuationRule.is_active == True)
        .first()
    )
    if not rule:
        rule = (
            db.query(models.ValuationRule)
            .filter(models.ValuationRule.rule_type == rule_type, models.ValuationRule.code == "unknown", models.ValuationRule.is_active == True)
            .first()
        )
    if not rule:
        return default, None, code
    return float(rule.factor), rule.warning, rule.label


def match_category(db: Session, req: ValuationRequest) -> tuple[models.DeviceCategory | None, float]:
    if req.category_code:
        cat = db.query(models.DeviceCategory).filter(models.DeviceCategory.code == req.category_code).first()
        if cat:
            return cat, 1.0

    text = norm(" ".join([req.item_text, req.manufacturer_text or "", req.model_text or "", req.memo or ""]))
    best = None
    score = 0.0
    for cat in db.query(models.DeviceCategory).all():
        candidates = [cat.name, cat.code] + (cat.aliases or [])
        s = max(similarity(text, c) for c in candidates)
        if s > score:
            best, score = cat, s
    return best, score


def match_model(db: Session, category_id: int | None, req: ValuationRequest) -> tuple[models.DeviceModel | None, models.ModelVariant | None, float]:
    text = norm(" ".join([req.manufacturer_text or "", req.model_text or "", req.variant_text or "", req.item_text or ""]))
    if not text:
        return None, None, 0.0

    q = db.query(models.DeviceModel).filter(models.DeviceModel.is_active == True)
    if category_id:
        q = q.filter(models.DeviceModel.category_id == category_id)

    best_model = None
    best_score = 0.0
    for model in q.limit(5000).all():
        man = model.manufacturer.name_ko if model.manufacturer else ""
        candidates = [model.model_name, model.model_family or "", man] + (model.aliases or [])
        s = max(similarity(text, c) for c in candidates if c)
        if s > best_score:
            best_model, best_score = model, s

    best_variant = None
    if best_model:
        var_score = 0.0
        for v in best_model.variants:
            candidates = [v.variant_name, str(v.storage_gb or ""), str(v.ram_gb or ""), v.cpu or "", v.gpu or ""]
            s = max(similarity(text, c) for c in candidates if c)
            if s > var_score:
                best_variant, var_score = v, s
        if best_variant and var_score < 0.35:
            best_variant = None

    return best_model, best_variant, best_score


def create_unmatched(db: Session, raw_text: str, category_guess: str | None):
    raw = norm(raw_text)[:300]
    if not raw:
        return
    row = db.query(models.UnmatchedModel).filter(models.UnmatchedModel.raw_text == raw, models.UnmatchedModel.status == "pending").first()
    if row:
        row.count += 1
        row.updated_at = datetime.utcnow()
    else:
        db.add(models.UnmatchedModel(raw_text=raw, category_guess=category_guess, count=1))
    db.commit()


def valuate(db: Session, req: ValuationRequest) -> dict:
    cat, cat_score = match_category(db, req)
    model, variant, model_score = match_model(db, cat.id if cat else None, req)

    warnings: list[str] = []
    quantity = max(1, min(int(req.quantity or 1), 999))

    if model:
        base = int(model.base_value or 0)
        min_value = int(model.min_value or 0)
        max_value = int(model.max_value or max(base, 1))
        demand_factor = float(model.demand_factor or 1.0)
    elif cat:
        base = int(cat.urban_mining_floor or 1000) * 6
        min_value = int(cat.urban_mining_floor or 0)
        max_value = max(base * 10, 30000)
        demand_factor = 0.45
    else:
        base, min_value, max_value, demand_factor = 1000, 0, 30000, 0.25

    condition_factor, condition_warning, condition_label = rule_factor(db, "condition", req.condition_code, 0.35)
    age_factor, age_warning, age_label = rule_factor(db, "age", req.age_code, 0.45)
    security_factor, security_warning, security_label = rule_factor(db, "security", req.security_code, 0.75)
    variant_factor = float(variant.value_multiplier) if variant else 1.0

    if condition_warning:
        warnings.append(condition_warning)
    if age_warning:
        warnings.append(age_warning)
    if security_warning:
        warnings.append(security_warning)

    if cat and cat.security_level in ("높음", "매우 높음") and not req.data_confirmed:
        warnings.append("저장매체·계정·개인정보 삭제 확인이 필요합니다.")
    if not req.owner_confirmed:
        warnings.append("본인 소유 또는 처분 권한 확인이 필요합니다.")
    if not req.not_stolen_confirmed and cat and cat.code in ("smartphone", "tablet", "laptop", "storage", "server"):
        warnings.append("분실·도난 의심 여부 확인이 필요합니다.")

    mid = base * condition_factor * age_factor * security_factor * demand_factor * variant_factor
    if cat:
        mid = max(mid, int(cat.urban_mining_floor or 0))
    mid = max(min_value, min(max_value, mid))

    unit_low = int(mid * 0.65)
    unit_high = int(mid * 1.35)
    total_low = unit_low * quantity
    total_high = unit_high * quantity

    confidence = max(cat_score * 0.35, 0) + max(model_score * 0.65, 0)
    if model is None:
        confidence = min(confidence, 0.45)
        create_unmatched(db, " ".join([req.item_text, req.manufacturer_text or "", req.model_text or ""]), cat.code if cat else None)

    if "소유" in " ".join(warnings) or "분실" in " ".join(warnings):
        route = "소유 확인 후 관리자 검토"
    elif cat and cat.security_level in ("높음", "매우 높음") and not req.data_confirmed:
        route = "데이터삭제 확인 후 검수"
    elif total_high >= 100000:
        route = "즉시수거/파트너 견적 후보"
    elif quantity >= 10 or total_high >= 50000:
        route = "묶음수거/캠페인 전환"
    else:
        route = "동별 묶음대기"

    requires_review = model is None or confidence < 0.62 or bool(warnings)

    snapshot = {
        "base": base,
        "min_value": min_value,
        "max_value": max_value,
        "condition": {"code": req.condition_code, "label": condition_label, "factor": condition_factor},
        "age": {"code": req.age_code, "label": age_label, "factor": age_factor},
        "security": {"code": req.security_code, "label": security_label, "factor": security_factor},
        "demand_factor": demand_factor,
        "variant_factor": variant_factor,
        "quantity": quantity,
        "calculated_mid": int(mid),
    }

    return {
        "ok": True,
        "category": {"id": cat.id, "code": cat.code, "name": cat.name, "security_level": cat.security_level} if cat else None,
        "matched_model": {"id": model.id, "name": model.model_name, "family": model.model_family, "base_value": model.base_value} if model else None,
        "matched_variant": {"id": variant.id, "name": variant.variant_name, "multiplier": variant.value_multiplier} if variant else None,
        "estimated_low": total_low,
        "estimated_high": total_high,
        "route": route,
        "matched_confidence": round(float(confidence), 3),
        "requires_admin_review": requires_review,
        "warnings": warnings,
        "snapshot": snapshot,
    }
