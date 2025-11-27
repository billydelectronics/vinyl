from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import csv, io, json, math
from fastapi import Body, FastAPI, HTTPException, Query, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pathlib import Path
import requests

# =============================================================================
# Config
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "records.db"
DB_PATH = os.environ.get("VINYL_DB", str(DEFAULT_DB_PATH))

DISCOGS_API = "https://api.discogs.com"
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN")  # optional
USER_AGENT = os.environ.get("USER_AGENT", "VinylRecordTracker/1.0")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "20"))

# =============================================================================
# FastAPI app
# =============================================================================

app = FastAPI(title="Vinyl API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# DB helpers
# =============================================================================


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    except Exception:
        pass
    return conn


def init_db() -> None:
    conn = db()
    cur = conn.cursor()

    # records table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          artist TEXT NOT NULL,
          title TEXT NOT NULL,
          year INTEGER,
          label TEXT,
          format TEXT,
          country TEXT,
          catalog_number TEXT,
          barcode TEXT,
          discogs_id INTEGER,
          discogs_release_id INTEGER,
          discogs_thumb TEXT,
          cover_url TEXT,
          cover_local TEXT,
          cover_url_auto TEXT,
          album_notes TEXT,
          personal_notes TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # tracks table (this is where your real tracks live)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tracks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
          side TEXT,
          position TEXT,
          title TEXT,
          duration TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tracks_record_id ON tracks(record_id)")

    # cover embeddings table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cover_embeddings (
          record_id INTEGER PRIMARY KEY,
          vec TEXT NOT NULL,
          FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
        )
        """
    )

    conn.commit()
    conn.close()


@app.on_event("startup")
def on_startup() -> None:
    # Ensure DB directory exists
    base = os.path.dirname(DB_PATH) or "."
    os.makedirs(base, exist_ok=True)
    init_db()


# =============================================================================
# Health
# =============================================================================


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "ts": int(time.time())}


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return {"status": "ok"}


# =============================================================================
# Models
# =============================================================================


class RecordIn(BaseModel):
    artist: str
    title: str
    year: Optional[int] = None
    label: Optional[str] = None
    format: Optional[str] = None
    country: Optional[str] = None
    catalog_number: Optional[str] = None
    barcode: Optional[str] = None
    discogs_id: Optional[int] = None
    discogs_release_id: Optional[int] = None
    discogs_thumb: Optional[str] = None
    cover_url: Optional[str] = None
    cover_local: Optional[str] = None
    cover_url_auto: Optional[str] = None
    album_notes: Optional[str] = None
    personal_notes: Optional[str] = None


class RecordPatch(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    label: Optional[str] = None
    format: Optional[str] = None
    country: Optional[str] = None
    catalog_number: Optional[str] = None
    barcode: Optional[str] = None
    discogs_id: Optional[int] = None
    discogs_release_id: Optional[int] = None
    discogs_thumb: Optional[str] = None
    cover_url: Optional[str] = None
    cover_local: Optional[str] = None
    cover_url_auto: Optional[str] = None
    album_notes: Optional[str] = None
    personal_notes: Optional[str] = None


class TrackIn(BaseModel):
    side: Optional[str] = None
    position: Optional[str] = None
    title: str
    duration: Optional[str] = None


class TracksReplaceIn(BaseModel):
    tracks: List[TrackIn] = Field(default_factory=list)


class DiscogsApplyIn(BaseModel):
    release_id: Optional[int] = None


# =============================================================================
# Utility helpers
# =============================================================================


def like_pattern(s: str) -> str:
    return f"%{s.replace('%', '%%')}%"


def _nz(x: Any, default: Any) -> Any:
    return default if x is None else x


# =============================================================================
# DB helper functions for records
# =============================================================================


def fetch_record(conn: sqlite3.Connection, rid: int) -> sqlite3.Row:
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
    if not row:
        raise HTTPException(404, detail="Record not found")
    return row


def db_get_record_or_404(rid: int) -> Dict[str, Any]:
    conn = db()
    row = fetch_record(conn, rid)
    out = dict(row)
    conn.close()
    return out


def db_patch_record(rid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload:
        return db_get_record_or_404(rid)

    conn = db()
    cur = conn.cursor()
    cols, vals = [], []
    for k, v in payload.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    cols.append("updated_at = CURRENT_TIMESTAMP")
    cur.execute(f"UPDATE records SET {', '.join(cols)} WHERE id = ?", (*vals, rid))
    conn.commit()
    conn.close()
    return db_get_record_or_404(rid)


def db_delete_records(ids: List[int]) -> int:
    if not ids:
        return 0
    conn = db()
    cur = conn.cursor()
    placeholders = ", ".join("?" for _ in ids)
    cur.execute(f"DELETE FROM records WHERE id IN ({placeholders})", ids)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


# =============================================================================
# Records API
# =============================================================================


@app.get("/api/records")
def list_records(
    search: Optional[str] = Query(None),
    sort_key: Optional[str] = Query("artist"),
    sort_dir: Optional[str] = Query("asc"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    where_clauses: List[str] = []
    params: List[Any] = []

    if search:
        like = like_pattern(search)
        where_clauses.append(
            "(artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    allowed_sort = {"artist", "title", "year", "label", "country", "created_at", "updated_at"}
    if sort_key not in allowed_sort:
        sort_key = "artist"
    sort_dir = "DESC" if (sort_dir or "").lower() == "desc" else "ASC"

    conn = db()
    cur = conn.cursor()
    sql_base = f"FROM records {where_sql}"
    total = cur.execute(f"SELECT COUNT(*) {sql_base}", params).fetchone()[0]

    sql = f"SELECT * {sql_base} ORDER BY {sort_key} COLLATE NOCASE {sort_dir}, id"
    rows = cur.execute(sql, (*params,)).fetchall()
    conn.close()

    items = [dict(r) for r in rows]
    return {"items": items, "total": total}


def derive_year_from_release_detail(detail: Dict[str, Any]) -> Optional[int]:
    year_val = detail.get("year")
    year_str: Optional[str]
    if year_val is not None:
        year_str = str(year_val).strip()
    else:
        released = detail.get("released")
        if not released:
            return None
        year_str = str(released).strip()
    if not year_str:
        return None
    try:
        year_int = int(year_str[:4])
        if 1800 <= year_int <= 2100:
            return year_int
    except Exception:
        return None
    return None


@app.post("/api/records")
def create_record(record: RecordIn) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO records (
          artist, title, year, label, format, country, catalog_number, barcode,
          discogs_id, discogs_release_id, discogs_thumb,
          cover_url, cover_local, cover_url_auto,
          album_notes, personal_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.artist,
            record.title,
            record.year,
            record.label,
            record.format,
            record.country,
            record.catalog_number,
            record.barcode,
            record.discogs_id,
            record.discogs_release_id,
            record.discogs_thumb,
            record.cover_url,
            record.cover_local,
            record.cover_url_auto,
            record.album_notes,
            record.personal_notes,
        ),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return db_get_record_or_404(rid)


@app.get("/api/records/{rid}")
def get_record(rid: int) -> Dict[str, Any]:
    return db_get_record_or_404(rid)


@app.patch("/api/records/{rid}")
def patch_record(rid: int, payload: RecordPatch = Body(...)) -> Dict[str, Any]:
    existing = db_get_record_or_404(rid)
    update_data = payload.dict(exclude_unset=True)
    merged = dict(existing)
    for k, v in update_data.items():
        merged[k] = v
    merged.pop("id", None)
    return db_patch_record(rid, merged)


@app.delete("/api/records/{rid}")
def delete_record(rid: int) -> Dict[str, Any]:
    deleted = db_delete_records([rid])
    return {"ok": True, "deleted": deleted}


@app.post("/api/records/bulk/delete")
def bulk_delete_records(ids: List[int] = Body(...)) -> Dict[str, Any]:
    deleted = db_delete_records(ids)
    return {"deleted": deleted}


# =============================================================================
# Track helpers / API  (using `tracks` table like the old working version)
# =============================================================================


def db_get_tracks(rid: int) -> List[Dict[str, Any]]:
    """Return all tracks for a record from the `tracks` table."""
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, record_id, side, position, title, duration "
        "FROM tracks WHERE record_id = ? ORDER BY id",
        (rid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_replace_tracks(rid: int, tracks: List[Dict[str, Any]]) -> None:
    """Replace all tracks in the `tracks` table for a record."""
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (rid,))
    for t in tracks:
        cur.execute(
            """
            INSERT INTO tracks (record_id, side, position, title, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rid,
                t.get("side"),
                t.get("position"),
                t.get("title"),
                t.get("duration"),
            ),
        )
    conn.commit()
    conn.close()


@app.get("/api/records/{rid}/tracks")
def api_get_tracks(rid: int) -> List[Dict[str, Any]]:
    """
    IMPORTANT: return a *plain list* for compatibility with the existing frontend.
    """
    _ = db_get_record_or_404(rid)
    return db_get_tracks(rid)

@app.post("/api/records/{rid}/tracks/replace")
def api_tracks_replace(rid: int, body: TracksReplaceIn) -> Dict[str, Any]:
    """
    Replaces all tracks for a record (used by Discogs Apply and manual editing).
    """
    _ = db_get_record_or_404(rid)
    items = [
        {"side": t.side, "position": t.position, "title": t.title, "duration": t.duration}
        for t in body.tracks
    ]
    db_replace_tracks(rid, items)

    # bump updated_at
    conn = db()
    conn.execute(
        "UPDATE records SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (rid,),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "count": len(items)}


# =============================================================================
# Import / Export
# =============================================================================


@app.get("/api/export")
def export_csv() -> Response:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM records ORDER BY artist, title")
    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "artist",
            "title",
            "year",
            "label",
            "format",
            "country",
            "catalog_number",
            "barcode",
            "discogs_id",
            "discogs_release_id",
            "discogs_thumb",
            "cover_url",
            "cover_local",
            "cover_url_auto",
            "album_notes",
            "personal_notes",
        ]
    )

    for r in rows:
        writer.writerow(
            [
                r["artist"],
                r["title"],
                r["year"] if r["year"] is not None else "",
                r["label"] or "",
                r["format"] or "",
                r["country"] or "",
                r["catalog_number"] or "",
                r["barcode"] or "",
                r["discogs_id"] if r["discogs_id"] is not None else "",
                r["discogs_release_id"] if r["discogs_release_id"] is not None else "",
                r["discogs_thumb"] or "",
                r["cover_url"] or "",
                r["cover_local"] or "",
                r["cover_url_auto"] or "",
                r["album_notes"] or "",
                r["personal_notes"] or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    headers = {"Content-Disposition": "attachment; filename=vinyl_records_export.csv"}
    return Response(content=csv_bytes, media_type="text/csv", headers=headers)


@app.get("/api/template")
def export_template() -> Response:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "artist",
            "title",
            "year",
            "label",
            "format",
            "country",
            "catalog_number",
            "barcode",
            "discogs_id",
            "discogs_release_id",
            "discogs_thumb",
            "cover_url",
            "cover_local",
            "cover_url_auto",
            "album_notes",
            "personal_notes",
        ]
    )

    csv_bytes = output.getvalue().encode("utf-8")
    headers = {"Content-Disposition": "attachment; filename=vinyl_records_template.csv"}
    return Response(content=csv_bytes, media_type="text/csv", headers=headers)


@app.post("/api/import")
def import_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, detail="Only CSV files are supported")

    content = file.file.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))

    conn = db()
    cur = conn.cursor()

    inserted = 0
    updated = 0
    skipped = 0

    for row in reader:
        artist = (row.get("artist") or "").strip()
        title = (row.get("title") or "").strip()
        if not artist or not title:
            skipped += 1
            continue

        year_str = (row.get("year") or "").strip()
        year = int(year_str) if year_str.isdigit() else None

        def clean(v: Optional[str]) -> Optional[str]:
            if v is None:
                return None
            v = v.strip()
            return v or None

        label = clean(row.get("label"))
        format_ = clean(row.get("format"))
        country = clean(row.get("country"))
        catalog_number = clean(row.get("catalog_number"))
        barcode = clean(row.get("barcode"))
        discogs_id_raw = clean(row.get("discogs_id"))
        discogs_id = int(discogs_id_raw) if discogs_id_raw and discogs_id_raw.isdigit() else None
        discogs_release_id_raw = clean(row.get("discogs_release_id"))
        discogs_release_id = (
            int(discogs_release_id_raw)
            if discogs_release_id_raw and discogs_release_id_raw.isdigit()
            else None
        )
        discogs_thumb = clean(row.get("discogs_thumb"))
        cover_url = clean(row.get("cover_url"))
        cover_local = clean(row.get("cover_local"))
        cover_url_auto = clean(row.get("cover_url_auto"))
        album_notes = clean(row.get("album_notes"))
        personal_notes = clean(row.get("personal_notes"))

        cur.execute(
            "SELECT id FROM records WHERE artist = ? AND title = ?",
            (artist, title),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE records
                SET year = ?, label = ?, format = ?, country = ?, catalog_number = ?, barcode = ?,
                    discogs_id = ?, discogs_release_id = ?, discogs_thumb = ?,
                    cover_url = ?, cover_local = ?, cover_url_auto = ?,
                    album_notes = ?, personal_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    year,
                    label,
                    format_,
                    country,
                    catalog_number,
                    barcode,
                    discogs_id,
                    discogs_release_id,
                    discogs_thumb,
                    cover_url,
                    cover_local,
                    cover_url_auto,
                    album_notes,
                    personal_notes,
                    existing["id"],
                ),
            )
            updated += 1
        else:
            cur.execute(
                """
                INSERT INTO records (
                    artist, title, year, label, format, country, catalog_number, barcode,
                    discogs_id, discogs_release_id, discogs_thumb,
                    cover_url, cover_local, cover_url_auto,
                    album_notes, personal_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artist,
                    title,
                    year,
                    label,
                    format_,
                    country,
                    catalog_number,
                    barcode,
                    discogs_id,
                    discogs_release_id,
                    discogs_thumb,
                    cover_url,
                    cover_local,
                    cover_url_auto,
                    album_notes,
                    personal_notes,
                ),
            )
            inserted += 1

    conn.commit()
    conn.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# =============================================================================
# Discogs helpers (search / release fetch)
# =============================================================================


def discogs_headers() -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if DISCOGS_TOKEN:
        h["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
    return h


def discogs_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{DISCOGS_API}{path}"
    try:
        r = requests.get(
            url, headers=discogs_headers(), params=params or {}, timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(502, detail=f"Discogs error: {e}")


@app.get("/api/discogs/search")
def api_discogs_search(
    artist: str = Query(..., description="Artist name"),
    # Frontend may send either `title` or `release_title`; support both.
    title: Optional[str] = Query(
        default=None,
        description="Release title (frontend may use `title`)"
    ),
    release_title: Optional[str] = Query(
        default=None,
        alias="release_title",
        description="Alternate param name used by the frontend / Discogs API"
    ),
    year: Optional[int] = Query(default=None),
    barcode: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """
    Proxy to Discogs /database/search, but accept both `title` and
    `release_title` as query parameters for backward compatibility.
    """
    # Prefer `title` if provided, otherwise fall back to `release_title`
    effective_title = title or release_title

    params: Dict[str, Any] = {
        "artist": artist,
        "type": "release",
    }
    if effective_title:
        # Discogs expects `release_title` here
        params["release_title"] = effective_title
    if year:
        params["year"] = year
    if barcode:
        params["barcode"] = barcode

    data = discogs_get("/database/search", params=params)
    return data


@app.get("/api/discogs/release/{release_id}")
def api_discogs_release(release_id: int) -> Dict[str, Any]:
    data = discogs_get(f"/releases/{release_id}")
    return data


@app.get("/api/discogs/cover/{release_id}")
def api_discogs_cover(release_id: int) -> Dict[str, Any]:
    data = discogs_get(f"/releases/{release_id}")
    images = data.get("images") or []
    if not images:
        return {"images": []}
    out = []
    for img in images:
        out.append(
            {
                "uri": img.get("uri"),
                "uri150": img.get("uri150"),
                "type": img.get("type"),
                "width": img.get("width"),
                "height": img.get("height"),
            }
        )
    return {"images": out}


@app.get("/api/discogs/tracklist/{release_id}")
def api_discogs_tracklist(release_id: int) -> Dict[str, Any]:
    data = discogs_get(f"/releases/{release_id}")
    out = []
    for t in data.get("tracklist") or []:
        position = t.get("position") or None
        title = t.get("title") or ""
        duration = t.get("duration") or None
        out.append(
            {
                "position": position,
                "title": title,
                "duration": duration,
            }
        )
    return {"tracks": out}


# =============================================================================
# Discogs -> record enrichment helpers
# =============================================================================


def extract_best_cover_from_release(data: Dict[str, Any]) -> Optional[str]:
    images = data.get("images") or []
    if not images:
        return None

    for img in images:
        if img.get("type") == "primary" and img.get("uri"):
            return img["uri"]

    for img in images:
        if img.get("uri"):
            return img["uri"]

    return None


def extract_tracklist_from_release(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    tl = data.get("tracklist") or []
    out: List[Dict[str, Any]] = []
    for t in tl:
        title = (t.get("title") or "").strip()
        if not title:
            continue
        pos = (t.get("position") or "").strip() or None
        duration = (t.get("duration") or "").strip() or None
        out.append(
            {
                "position": pos or None,
                "title": title or "Untitled",
                "duration": duration or None,
            }
        )
    return out


@app.post("/api/records/{rid}/discogs/apply")
def api_apply_discogs_release(rid: int, payload: DiscogsApplyIn = Body(...)) -> Dict[str, Any]:
    """
    Given a Discogs release_id, fetch the details, derive a year (if missing),
    and update:
      - year (if missing or same as derived)
      - discogs_release_id
      - cover_url, discogs_thumb
      - tracks table (NOT tracklist)
    """
    release_id = payload.release_id
    if not release_id:
        raise HTTPException(400, detail="release_id is required")

    detail = discogs_get(f"/releases/{release_id}")
    derived_year = derive_year_from_release_detail(detail)
    cover = extract_best_cover_from_release(detail)
    tracks = extract_tracklist_from_release(detail)

    conn = db()
    cur = conn.cursor()

    # Fetch current record
    rec_row = fetch_record(conn, rid)
    current_year = rec_row["year"]
    # Only set year if it's missing or matches derived; otherwise leave user value
    new_year = current_year
    if derived_year is not None and (current_year is None or current_year == derived_year):
        new_year = derived_year

    # Update record with new info
    cur.execute(
        """
        UPDATE records
        SET year = ?, discogs_release_id = ?, cover_url = ?, discogs_thumb = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (new_year, release_id, cover, cover, rid),
    )

    # Replace tracks rows in `tracks` table (side is unknown from Discogs here, so we leave it NULL)
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (rid,))
    for t in tracks:
        cur.execute(
            """
            INSERT INTO tracks (record_id, side, position, title, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rid, None, t["position"], t["title"], t["duration"]),
        )

    conn.commit()
    conn.close()

    return {"ok": True, "derived_year": derived_year, "cover_url": cover, "tracks": tracks}


# =============================================================================
# CLIP (MPS / CUDA / CPU)
# =============================================================================

_CLIP_MODEL = None
_CLIP_PREPROCESS = None
_CLIP_DEVICE = None


def get_clip_model():
    """
    Lazy-load CLIP model and preprocess function.

    Requires:
      - torch
      - pillow
      - clip (pip install git+https://github.com/openai/CLIP.git)
    """
    global _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_DEVICE
    if _CLIP_MODEL is not None and _CLIP_PREPROCESS is not None:
        return _CLIP_MODEL, _CLIP_PREPROCESS, _CLIP_DEVICE

    try:
        import torch
        import clip
    except Exception as e:
        raise HTTPException(500, detail=f"CLIP dependencies not available: {e}")

    # Optional explicit device override (e.g. CLIP_DEVICE=mps in local dev)
    env_device = os.environ.get("CLIP_DEVICE")
    if env_device:
        device = env_device
    else:
        # Prefer MPS on Apple Silicon when available
        has_mps = hasattr(torch.backends, "mps")
        mps_ok = has_mps and getattr(torch.backends.mps, "is_available", lambda: False)()
        mps_built = has_mps and getattr(torch.backends.mps, "is_built", lambda: True)()
        if mps_ok and mps_built:
            device = "mps"
        # Next prefer CUDA on GPU machines
        elif torch.cuda.is_available():
            device = "cuda"
        # Fallback to CPU
        else:
            device = "cpu"

    model_name = os.environ.get("CLIP_MODEL_NAME", "ViT-B/32")
    try:
        model, preprocess = clip.load(model_name, device=device)
    except Exception as e:
        raise HTTPException(
            500,
            detail=f"Failed to load CLIP model '{model_name}' on device '{device}': {e}",
        )

    model.eval()

    _CLIP_MODEL = model
    _CLIP_PREPROCESS = preprocess
    _CLIP_DEVICE = device
    print(f"[clip] Loaded model {model_name} on device {device}")
    return model, preprocess, device


def compute_image_embedding(image_bytes: bytes) -> List[float]:
    try:
        from PIL import Image
        import torch
    except Exception as e:
        raise HTTPException(500, detail=f"Image/torch dependencies not available: {e}")

    from io import BytesIO

    model, preprocess, device = get_clip_model()
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img_t = preprocess(img).unsqueeze(0).to(device)

    with torch.no_grad():
        features = model.encode_image(img_t)
        features = features / features.norm(dim=-1, keepdim=True)
        vec: List[float] = features[0].cpu().tolist()
    return vec


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# =============================================================================
# Cover APIs (embed, match, populate)
# =============================================================================


def ensure_cover_embeddings_table() -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cover_embeddings (
          record_id INTEGER PRIMARY KEY,
          vec TEXT NOT NULL,
          FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def upsert_cover_embedding(record_id: int, vec: List[float]) -> None:
    ensure_cover_embeddings_table()
    conn = db()
    cur = conn.cursor()
    vec_json = json.dumps(vec)
    cur.execute(
        """
        INSERT INTO cover_embeddings (record_id, vec)
        VALUES (?, ?)
        ON CONFLICT(record_id) DO UPDATE SET
          vec = excluded.vec
        """,
        (record_id, vec_json),
    )
    conn.commit()
    conn.close()


def delete_cover_embedding(record_id: int) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM cover_embeddings WHERE record_id = ?", (record_id,))
    conn.commit()
    conn.close()


def get_all_cover_embeddings() -> List[Tuple[int, List[List[float]]]]:
    ensure_cover_embeddings_table()
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT record_id, vec FROM cover_embeddings")
    rows = cur.fetchall()
    conn.close()

    out: List[Tuple[int, List[List[float]]]] = []
    for r in rows:
        try:
            value = json.loads(r["vec"])
            if isinstance(value, list) and value and isinstance(value[0], list):
                vecs: List[List[float]] = []
                for item in value:
                    if isinstance(item, list):
                        vecs.append([float(x) for x in item])
            else:
                vecs = [[float(x) for x in value]]
            out.append((int(r["record_id"]), vecs))
        except Exception:
            continue
    return out


@app.post("/api/cover-embed/{record_id}")
async def api_cover_embed(record_id: int, file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Accept an uploaded cover image for a specific record and store its embedding.
    """
    contents = await file.read()
    vec = compute_image_embedding(contents)
    upsert_cover_embedding(record_id, vec)
    return {"status": "ok", "record_id": record_id}


@app.delete("/api/cover-embed/{record_id}")
def api_cover_embed_delete(record_id: int) -> Dict[str, Any]:
    delete_cover_embedding(record_id)
    return {"status": "ok"}


@app.post("/api/cover-match")
async def api_cover_match(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Accept an uploaded cover photo, compute a CLIP embedding, and find the closest
    matching record in the existing cover_embeddings table.

    Adds a 'confident' flag when the best match is clearly ahead of the rest:
      - best.score >= 0.80
      - (best.score - second_best.score) >= 0.10
    """
    contents = await file.read()
    query_vec = compute_image_embedding(contents)

    # Load all stored embeddings
    all_embeddings = get_all_cover_embeddings()
    if not all_embeddings:
        raise HTTPException(400, detail="No cover embeddings available; please populate first.")

    scored: List[Dict[str, Any]] = []
    for record_id, vecs in all_embeddings:
        best_for_record = 0.0
        for v in vecs:
            s = cosine_similarity(query_vec, v)
            best_for_record = max(best_for_record, s)
        scored.append({"record_id": record_id, "score": best_for_record})

    if not scored:
        raise HTTPException(400, detail="No comparable cover embeddings found.")

    scored.sort(key=lambda x: x["score"], reverse=True)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None

    confident = False
    if best["score"] >= 0.80 and (second is None or (best["score"] - second["score"] >= 0.10)):
        confident = True

    # Attach basic record info for candidates
    conn = db()
    cur = conn.cursor()
    candidates: List[Dict[str, Any]] = []
    for item in scored[:5]:
        cur.execute("SELECT id, artist, title FROM records WHERE id = ?", (item["record_id"],))
        row = cur.fetchone()
        if not row:
            continue
        candidates.append(
            {
                "id": row["id"],
                "artist": row["artist"],
                "title": row["title"],
                "score": item["score"],
            }
        )
    conn.close()

    # Best match (first candidate if present)
    match_id = candidates[0]["id"] if candidates else None
    match_score = candidates[0]["score"] if candidates else None

    return {
        "match": match_id,
        "score": match_score,
        "candidates": candidates,
        "confident": confident,
    }


@app.post("/api/cover-embeddings/populate")
def api_cover_embeddings_populate(
    limit: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """
    Bulk populate cover_embeddings for all records that have a cover_url / discogs_thumb.

    This endpoint should be used carefully; it loops through many records and fetches images.
    """
    ensure_cover_embeddings_table()
    conn = db()
    cur = conn.cursor()

    q = """
        SELECT id, cover_url, discogs_thumb
        FROM records
        WHERE (cover_url IS NOT NULL AND cover_url != '')
           OR (discogs_thumb IS NOT NULL AND discogs_thumb != '')
        ORDER BY id
    """
    if limit is not None and limit > 0:
        q += " LIMIT ?"
        cur.execute(q, (limit,))
    else:
        cur.execute(q)

    rows = cur.fetchall()
    conn.close()

    processed = 0
    skipped_no_image = 0
    errors = 0

    for r in rows:
        rid = r["id"]
        url = r["cover_url"] or r["discogs_thumb"]
        if not url:
            skipped_no_image += 1
            continue

        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            vec = compute_image_embedding(resp.content)
            upsert_cover_embedding(rid, vec)
            processed += 1
        except HTTPException:
            raise
        except Exception:
            errors += 1
            continue

    return {
        "processed": processed,
        "skipped_no_image": skipped_no_image,
        "errors": errors,
    }