# app/routes/records.py
from __future__ import annotations
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.services.cover_best_match import fetch_best_cover_for_record, pick_best_image
from app.db import get_db  # your existing dependency
from app.models import Record  # your SQLAlchemy model

router = APIRouter(prefix="/api/records", tags=["records"])

def record_to_dict(r: Record) -> Dict[str, Any]:
    return {
        "id": r.id,
        "artist": r.artist,
        "title": r.title,
        "year": r.year,
        "label": r.label,
        "format": r.format,
        "country": r.country,
        "catalog_number": r.catalog_number,
        "barcode": r.barcode,
        "discogs_id": r.discogs_id,
        "discogs_release_id": r.discogs_release_id,
        "discogs_thumb": r.discogs_thumb,
        "cover_url": r.cover_url,
        "cover_local": r.cover_local,
        "cover_url_auto": r.cover_url_auto,
    }

@router.post("/{record_id}/cover/fetch")
async def fetch_cover_best_match(record_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    r: Optional[Record] = db.query(Record).filter(Record.id == record_id).one_or_none()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Record not found")

    # Build a plain dict for the matching service
    input_rec = record_to_dict(r)

    match = await fetch_best_cover_for_record(input_rec)
    if not match:
        # Respect constraints: only LP & required country; nothing found
        raise HTTPException(status_code=404, detail="No LP releases found for required country")

    full, thumb = pick_best_image(match)
    if not full and not thumb:
        raise HTTPException(status_code=404, detail="Matching release has no images")

    # Persist updates
    if full:
        r.cover_url_auto = full
    if thumb:
        r.discogs_thumb = thumb
    if match.get("id"):
        try:
            r.discogs_release_id = int(match["id"])
        except Exception:
            pass

    db.add(r)
    db.commit()
    db.refresh(r)

    return {
        "status": "ok",
        "updated": {
            "cover_url_auto": r.cover_url_auto,
            "discogs_thumb": r.discogs_thumb,
            "discogs_release_id": r.discogs_release_id,
        }
    }