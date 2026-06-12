from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import get_settings
from app.database import Base, engine, SessionLocal
from app.routers import admin, electronics, resources
from app.seed import seed

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0-production-backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


@app.get("/")
def root():
    return {
        "ok": True,
        "name": "자원잇다 운영용 백엔드",
        "stack": "FastAPI + PostgreSQL/SQLite + Object Storage + Device Model DB + Valuation Engine",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"ok": True}


app.include_router(electronics.router)
app.include_router(resources.router)
app.include_router(admin.router)

# local upload serving only for local mode. In production, use S3/R2 public or signed URLs.
upload_dir = Path(settings.local_upload_dir)
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")
