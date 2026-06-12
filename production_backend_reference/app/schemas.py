from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ManufacturerIn(BaseModel):
    name_ko: str
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)


class CategoryIn(BaseModel):
    code: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    default_route: str = ""
    security_level: str = "낮음"
    urban_mining_floor: int = 0
    checklist: list[str] = Field(default_factory=list)


class DeviceModelIn(BaseModel):
    category_id: int
    manufacturer_id: int | None = None
    model_name: str
    model_family: str | None = None
    aliases: list[str] = Field(default_factory=list)
    release_year: int | None = None
    base_value: int = 0
    min_value: int = 0
    max_value: int = 0
    demand_factor: float = 1.0


class VariantIn(BaseModel):
    model_id: int
    variant_name: str
    storage_gb: int | None = None
    ram_gb: int | None = None
    cpu: str | None = None
    gpu: str | None = None
    screen_size: str | None = None
    value_multiplier: float = 1.0


class RuleIn(BaseModel):
    rule_type: str
    code: str
    label: str
    factor: float = 1.0
    warning: str | None = None


class ValuationRequest(BaseModel):
    user_id: str | None = None
    item_text: str = ""
    category_code: str | None = None
    manufacturer_text: str | None = None
    model_text: str | None = None
    variant_text: str | None = None
    condition_code: str = "unknown"
    age_code: str = "unknown"
    security_code: str = "unknown"
    quantity: int = 1
    memo: str | None = None
    owner_confirmed: bool = False
    data_confirmed: bool = False
    not_stolen_confirmed: bool = False


class ValuationResponse(BaseModel):
    ok: bool
    category: dict[str, Any] | None
    matched_model: dict[str, Any] | None
    matched_variant: dict[str, Any] | None
    estimated_low: int
    estimated_high: int
    route: str
    matched_confidence: float
    requires_admin_review: bool
    warnings: list[str]
    snapshot: dict[str, Any]
