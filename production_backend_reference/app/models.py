from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(120), index=True)
    name_en: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DeviceCategory(Base):
    __tablename__ = "device_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_route: Mapped[str] = mapped_column(String(200), default="")
    security_level: Mapped[str] = mapped_column(String(40), default="낮음")
    urban_mining_floor: Mapped[int] = mapped_column(Integer, default=0)
    checklist: Mapped[list[str]] = mapped_column(JSON, default=list)


class DeviceModel(Base):
    __tablename__ = "device_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "model_name", name="uq_model_manufacturer_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("device_categories.id"), index=True)
    manufacturer_id: Mapped[int | None] = mapped_column(ForeignKey("manufacturers.id"), nullable=True, index=True)

    model_name: Mapped[str] = mapped_column(String(160), index=True)
    model_family: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    release_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    base_value: Mapped[int] = mapped_column(Integer, default=0)
    min_value: Mapped[int] = mapped_column(Integer, default=0)
    max_value: Mapped[int] = mapped_column(Integer, default=0)
    demand_factor: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    category = relationship("DeviceCategory")
    manufacturer = relationship("Manufacturer")
    variants = relationship("ModelVariant", back_populates="model", cascade="all, delete-orphan")


class ModelVariant(Base):
    __tablename__ = "model_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("device_models.id"), index=True)
    variant_name: Mapped[str] = mapped_column(String(160), index=True)
    storage_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_gb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gpu: Mapped[str | None] = mapped_column(String(120), nullable=True)
    screen_size: Mapped[str | None] = mapped_column(String(80), nullable=True)
    value_multiplier: Mapped[float] = mapped_column(Float, default=1.0)

    model = relationship("DeviceModel", back_populates="variants")


class ValuationRule(Base):
    __tablename__ = "valuation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(60), index=True)  # condition, age, security, accessory
    code: Mapped[str] = mapped_column(String(80), index=True)
    label: Mapped[str] = mapped_column(String(160))
    factor: Mapped[float] = mapped_column(Float, default=1.0)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("device_models.id"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(80), default="admin")
    observed_price: Mapped[int] = mapped_column(Integer)
    condition_code: Mapped[str] = mapped_column(String(80), default="good")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResourceSubmission(Base):
    __tablename__ = "resource_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("device_categories.id"), nullable=True)
    matched_model_id: Mapped[int | None] = mapped_column(ForeignKey("device_models.id"), nullable=True)
    matched_variant_id: Mapped[int | None] = mapped_column(ForeignKey("model_variants.id"), nullable=True)

    item_text: Mapped[str] = mapped_column(String(240), default="")
    manufacturer_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    condition_code: Mapped[str] = mapped_column(String(80), default="unknown")
    age_code: Mapped[str] = mapped_column(String(80), default="unknown")
    security_code: Mapped[str] = mapped_column(String(80), default="unknown")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(80), default="submitted")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ValuationResult(Base):
    __tablename__ = "valuation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("resource_submissions.id"), nullable=True, index=True)
    estimated_low: Mapped[int] = mapped_column(Integer)
    estimated_high: Mapped[int] = mapped_column(Integer)
    route: Mapped[str] = mapped_column(String(200))
    matched_confidence: Mapped[float] = mapped_column(Float, default=0)
    requires_admin_review: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UnmatchedModel(Base):
    __tablename__ = "unmatched_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_text: Mapped[str] = mapped_column(String(300), index=True)
    category_guess: Mapped[str | None] = mapped_column(String(120), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(80), default="pending")  # pending, linked, ignored
    linked_model_id: Mapped[int | None] = mapped_column(ForeignKey("device_models.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
