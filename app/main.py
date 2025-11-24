from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import csv, io, json, math
from fastapi import Body, FastAPI, HTTPException, Query, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# =============================================================================
# Config
# =============================================================================

DB_PATH = os.environ.get("VINYL_DB", "/app/data/records.db")

DISCOGS_API = "https://api.discogs.com"
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN")  # optional
USER_AGENT = os.environ.get("USER_AGENT", "VinylRecordTracker/1.0")
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "20"))

app = FastAPI(title="Vinyl API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    cover_local: Optional[str] = None
    cover_url: Optional[str] = None
    cover_url_auto: Optional[str] = None
    discogs_thumb: Optional[str] = None


class RecordUpdate(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    label: Optional[str] = None
    format: Optional[str] = None
    country: Optional[str] = None
    catalog_number: Optional[str] = None
    barcode: Optional[str] = None
    discogs_id: Optional[int] = None
    cover_local: Optional[str] = None
    cover_url: Optional[str] = None
    cover_url_auto: Optional[str] = None
    discogs_thumb: Optional[str] = None


class TrackIn(BaseModel):
    side: Optional[str] = None
    position: Optional[str] = None
    title: str
    duration: Optional[str] = None


class TrackUpdate(BaseModel):
    side: Optional[str] = None
    position: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None


class DiscogsSearchResult(BaseModel):
    id: int
    title: str
    year: Optional[int]
    label: Optional[str]
    country: Optional[str]
    format: Optional[str]
    catalog_number: Optional[str]
    barcode: Optional[str]
    thumb: Optional[str]


class EmbeddingRebuildResult(BaseModel):
    processed: int
    skipped_no_image: int
    errors: int


# =============================================================================
# DB helpers
# =============================================================================


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn


def init_db() -> None:
    conn = db()
    # Enable WAL mode for better concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    # Optional but recommended for faster writes with slight durability trade-off
    conn.execute("PRAGMA synchronous=NORMAL;")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          artist TEXT,
          title TEXT,
          year INTEGER,
          label TEXT,
          format TEXT,
          country TEXT,
          catalog_number TEXT,
          barcode TEXT,
          discogs_id INTEGER,
          cover_local TEXT,
          cover_url TEXT,
          cover_url_auto TEXT,
          discogs_thumb TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tracks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id INTEGER NOT NULL,
          side TEXT,
          position TEXT,
          title TEXT NOT NULL,
          duration TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cover_embeddings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          record_id INTEGER NOT NULL,
          vector BLOB NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def bump_record_updated(rid: int) -> None:
    conn = db()
    conn.execute("UPDATE records SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rid,))
    conn.commit()
    conn.close()


# =============================================================================
# Discogs helper
# =============================================================================

import requests


def discogs_headers() -> Dict[str, str]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if DISCOGS_TOKEN:
        headers["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
    return headers


def discogs_search(query: str, per_page: int = 20, page: int = 1) -> Dict[str, Any]:
    params = {
        "q": query,
        "type": "release",
        "per_page": per_page,
        "page": page,
    }
    resp = requests.get(
        f"{DISCOGS_API}/database/search",
        headers=discogs_headers(),
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, detail=f"Discogs search failed: {resp.text}")
    return resp.json()


def discogs_release(release_id: int) -> Dict[str, Any]:
    resp = requests.get(
        f"{DISCOGS_API}/releases/{release_id}",
        headers=discogs_headers(),
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, detail=f"Discogs release fetch failed: {resp.text}")
    return resp.json()


# =============================================================================
# CLIP / embedding helpers
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
        import torch  # type: ignore
        import clip   # type: ignore
    except Exception as e:
        raise HTTPException(500, detail=f"CLIP dependencies not available: {e}")

    # Device selection: CUDA > MPS > CPU
    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Uses Apple GPU via Metal Performance Shaders (not Neural Engine)
        device = "mps"
    else:
        device = "cpu"

    model_name = os.environ.get("CLIP_MODEL_NAME", "ViT-B/32")
    model, preprocess = clip.load(model_name, device=device)
    model.eval()

    _CLIP_MODEL = model
    _CLIP_PREPROCESS = preprocess
    _CLIP_DEVICE = device
    return model, preprocess, device


def image_to_embedding(url: str) -> Optional[bytes]:
    """
    Download image from URL, run through CLIP, and return a float32 vector as bytes.
    """
    import torch  # type: ignore
    from PIL import Image  # type: ignore

    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return None

    try:
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception:
        return None

    model, preprocess, device = get_clip_model()
    image_tensor = preprocess(img).unsqueeze(0).to(device)

    with torch.no_grad():
        emb = model.encode_image(image_tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        emb = emb.cpu().numpy().astype("float32")

    return emb.tobytes()


def bytes_to_vector(b: bytes) -> List[float]:
    import numpy as np  # type: ignore

    arr = np.frombuffer(b, dtype="float32")
    return arr.tolist()


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    import numpy as np  # type: ignore

    a = np.array(vec_a, dtype="float32")
    b = np.array(vec_b, dtype="float32")

    if a.shape != b.shape:
        raise ValueError("Vectors must be same shape")

    dot = float((a * b).sum())
    norm_a = float((a * a).sum()) ** 0.5
    norm_b = float((b * b).sum()) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# =============================================================================
# Startup
# =============================================================================


@app.on_event("startup")
def on_startup():
    init_db()


# =============================================================================
# Routes
# =============================================================================


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


# ---------- Records CRUD ----------


@app.get("/api/records")
def list_records(
    search: Optional[str] = Query(None),
    sort: Optional[str] = Query("artist"),
    direction: Optional[str] = Query("asc"),
) -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()

    base_query = "SELECT * FROM records"
    where_clauses = []
    params: List[Any] = []

    if search:
        like = f"%{search}%"
        where_clauses.append(
            "(artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    sort_column = "artist"
    if sort in {"artist", "title", "year"}:
        sort_column = sort

    dir_sql = "ASC" if direction != "desc" else "DESC"

    sql = f"{base_query} ORDER BY {sort_column} COLLATE NOCASE {dir_sql}, id ASC"

    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/records/{record_id}")
def get_record(record_id: int) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM records WHERE id = ?", (record_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail="Record not found")

    rec = dict(row)

    cur.execute("SELECT * FROM tracks WHERE record_id = ? ORDER BY id ASC", (record_id,))
    tracks = [dict(t) for t in cur.fetchall()]
    conn.close()

    rec["tracks"] = tracks
    return rec


@app.post("/api/records", status_code=201)
def create_record(record: RecordIn) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO records (
          artist, title, year, label, format, country,
          catalog_number, barcode, discogs_id, cover_local,
          cover_url, cover_url_auto, discogs_thumb
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            record.cover_local,
            record.cover_url,
            record.cover_url_auto,
            record.discogs_thumb,
        ),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()

    return {"id": rid}


@app.patch("/api/records/{record_id}")
def update_record(record_id: int, patch: RecordUpdate) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    fields = []
    params: List[Any] = []

    data = patch.dict(exclude_unset=True)
    for key, value in data.items():
        fields.append(f"{key} = ?")
        params.append(value)

    if not fields:
        conn.close()
        return {"updated": False}

    params.append(record_id)

    sql = f"UPDATE records SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    cur.execute(sql, params)
    conn.commit()
    conn.close()

    return {"updated": True}


@app.delete("/api/records/{record_id}", status_code=204)
def delete_record(record_id: int):
    conn = db()
    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return Response(status_code=204)


# ---------- Tracks CRUD ----------


@app.post("/api/records/{record_id}/tracks", status_code=201)
def create_track(record_id: int, track: TrackIn) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM records WHERE id = ?", (record_id,))
    if not cur.fetchone():
        conn.close()
        raise HTTPException(404, detail="Record not found")

    cur.execute(
        """
        INSERT INTO tracks (record_id, side, position, title, duration)
        VALUES (?, ?, ?, ?, ?)
        """,
        (record_id, track.side, track.position, track.title, track.duration),
    )
    tid = cur.lastrowid
    conn.commit()
    conn.close()

    return {"id": tid}


@app.patch("/api/tracks/{track_id}")
def update_track(track_id: int, patch: TrackUpdate) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    fields = []
    params: List[Any] = []

    data = patch.dict(exclude_unset=True)
    for key, value in data.items():
        fields.append(f"{key} = ?")
        params.append(value)

    if not fields:
        conn.close()
        return {"updated": False}

    params.append(track_id)

    sql = f"UPDATE tracks SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    cur.execute(sql, params)
    conn.commit()
    conn.close()

    return {"updated": True}


@app.delete("/api/tracks/{track_id}", status_code=204)
def delete_track(track_id: int):
    conn = db()
    conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    conn.commit()
    conn.close()
    return Response(status_code=204)


# ---------- Import / Export ----------


@app.get("/api/records/export")
def export_records() -> Response:
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM records ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE")
    records = cur.fetchall()

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
            "cover_local",
            "cover_url",
            "cover_url_auto",
            "discogs_thumb",
        ]
    )

    for r in records:
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
                r["cover_local"] or "",
                r["cover_url"] or "",
                r["cover_url_auto"] or "",
                r["discogs_thumb"] or "",
            ]
        )

    csv_data = output.getvalue()
    conn.close()

    headers = {
        "Content-Disposition": 'attachment; filename="records_export.csv"',
        "Content-Type": "text/csv; charset=utf-8",
    }
    return Response(content=csv_data, media_type="text/csv", headers=headers)


@app.get("/api/records/template")
def download_template() -> Response:
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
            "cover_local",
            "cover_url",
            "cover_url_auto",
            "discogs_thumb",
        ]
    )
    csv_data = output.getvalue()

    headers = {
        "Content-Disposition": 'attachment; filename="records_template.csv"',
        "Content-Type": "text/csv; charset=utf-8",
    }
    return Response(content=csv_data, media_type="text/csv", headers=headers)


@app.post("/api/records/import")
async def import_records(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, detail="Only CSV files are supported.")

    try:
        content_bytes = await file.read()
        text = content_bytes.decode("utf-8-sig")
    except Exception:
        raise HTTPException(400, detail="Could not read CSV file.")

    reader = csv.DictReader(io.StringIO(text))
    conn = db()
    cur = conn.cursor()

    imported = 0
    skipped = 0
    errors = 0

    for row in reader:
        artist = (row.get("artist") or "").strip()
        title = (row.get("title") or "").strip()

        if not artist or not title:
            skipped += 1
            continue

        def clean(val: Optional[str]) -> Optional[str]:
            if val is None:
                return None
            val = val.strip()
            return val or None

        year_val = (row.get("year") or "").strip()
        year = int(year_val) if year_val.isdigit() else None

        label = clean(row.get("label"))
        format_ = clean(row.get("format")) or "LP"
        country = clean(row.get("country")) or "US"
        catalog_number = clean(row.get("catalog_number"))
        barcode = clean(row.get("barcode"))
        discogs_id = None
        discogs_val = (row.get("discogs_id") or "").strip()
        if discogs_val.isdigit():
            discogs_id = int(discogs_val)

        cover_local = clean(row.get("cover_local"))
        cover_url = clean(row.get("cover_url"))
        cover_url_auto = clean(row.get("cover_url_auto"))
        discogs_thumb = clean(row.get("discogs_thumb"))

        try:
            cur.execute(
                """
                INSERT INTO records (
                  artist, title, year, label, format, country,
                  catalog_number, barcode, discogs_id, cover_local,
                  cover_url, cover_url_auto, discogs_thumb
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    cover_local,
                    cover_url,
                    cover_url_auto,
                    discogs_thumb,
                ),
            )
            imported += 1
        except Exception:
            errors += 1
            continue

    conn.commit()
    conn.close()

    return {"imported": imported, "skipped": skipped, "errors": errors}


# ---------- Discogs integration ----------


@app.get("/api/discogs/search", response_model=List[DiscogsSearchResult])
def api_discogs_search(query: str = Query(..., min_length=2)) -> List[DiscogsSearchResult]:
    data = discogs_search(query)
    results: List[DiscogsSearchResult] = []

    for item in data.get("results", []):
        fmt = None
        if item.get("format"):
            fmt = ", ".join(item["format"])

        label = None
        if item.get("label"):
            label = ", ".join(item["label"])

        catno = item.get("catno") or None
        barcode = None
        if item.get("barcode"):
            barcode = ", ".join(item["barcode"])

        results.append(
            DiscogsSearchResult(
                id=item["id"],
                title=item.get("title") or "",
                year=item.get("year"),
                label=label,
                country=item.get("country"),
                format=fmt,
                catalog_number=catno,
                barcode=barcode,
                thumb=item.get("thumb") or None,
            )
        )

    return results


@app.get("/api/discogs/release/{release_id}")
def api_discogs_release(release_id: int) -> Dict[str, Any]:
    data = discogs_release(release_id)

    tracklist = []
    for t in data.get("tracklist", []):
        tracklist.append(
            {
                "position": t.get("position"),
                "title": t.get("title"),
                "duration": t.get("duration"),
            }
        )

    images = data.get("images") or []
    primary_image = None
    if images:
        for img in images:
            if img.get("type") == "primary":
                primary_image = img.get("uri")
                break
        if not primary_image:
            primary_image = images[0].get("uri")

    labels = data.get("labels") or []
    label_name = None
    catalog_number = None
    if labels:
        label_name = labels[0].get("name")
        catalog_number = labels[0].get("catno")

    barcode = None
    barcodes = data.get("identifiers") or []
    for ident in barcodes:
        if ident.get("type") == "Barcode":
            barcode = ident.get("value")
            break

    result = {
        "id": data.get("id"),
        "title": data.get("title"),
        "year": data.get("year"),
        "label": label_name,
        "country": data.get("country"),
        "format": ", ".join(data.get("formats", [{}])[0].get("descriptions", []))
        if data.get("formats")
        else None,
        "catalog_number": catalog_number,
        "barcode": barcode,
        "cover_url": primary_image,
        "tracklist": tracklist,
    }
    return result


@app.post("/api/records/{record_id}/discogs/apply/{release_id}")
def apply_discogs_release(record_id: int, release_id: int) -> Dict[str, Any]:
    data = discogs_release(release_id)

    images = data.get("images") or []
    primary_image = None
    thumb = None
    if images:
        for img in images:
            if img.get("type") == "primary":
                primary_image = img.get("uri")
                thumb = img.get("uri150")
                break
        if not primary_image:
            primary_image = images[0].get("uri")
            thumb = images[0].get("uri150")

    labels = data.get("labels") or []
    label_name = None
    catalog_number = None
    if labels:
        label_name = labels[0].get("name")
        catalog_number = labels[0].get("catno")

    barcode = None
    barcodes = data.get("identifiers") or []
    for ident in barcodes:
        if ident.get("type") == "Barcode":
            barcode = ident.get("value")
            break

    year = data.get("year")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE records
        SET discogs_id = ?, label = ?, country = ?, format = ?,
            catalog_number = ?, barcode = ?, cover_url_auto = ?,
            discogs_thumb = ?, year = COALESCE(year, ?),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            data.get("id"),
            label_name,
            data.get("country"),
            ", ".join(data.get("formats", [{}])[0].get("descriptions", []))
            if data.get("formats")
            else None,
            catalog_number,
            barcode,
            primary_image,
            thumb,
            year,
            record_id,
        ),
    )

    cur.execute("DELETE FROM tracks WHERE record_id = ?", (record_id,))

    for t in data.get("tracklist", []):
        cur.execute(
            """
            INSERT INTO tracks (record_id, side, position, title, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record_id,
                t.get("position")[:1] if t.get("position") else None,
                t.get("position"),
                t.get("title"),
                t.get("duration"),
            ),
        )

    conn.commit()
    conn.close()

    return {"applied": True}


# ---------- Cover embeddings ----------


@app.post("/api/cover-embeddings/rebuild", response_model=EmbeddingRebuildResult)
def rebuild_cover_embeddings() -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT id, cover_url_auto FROM records")
    rows = cur.fetchall()

    processed = 0
    skipped_no_image = 0
    errors = 0

    for row in rows:
        rid = row["id"]
        url = row["cover_url_auto"]

        if not url:
            skipped_no_image += 1
            continue

        try:
            vector_bytes = image_to_embedding(url)
            if vector_bytes is None:
                errors += 1
                continue

            cur.execute("DELETE FROM cover_embeddings WHERE record_id = ?", (rid,))
            cur.execute(
                "INSERT INTO cover_embeddings (record_id, vector) VALUES (?, ?)",
                (rid, sqlite3.Binary(vector_bytes)),
            )
            processed += 1
        except HTTPException:
            raise
        except Exception:
            errors += 1
            continue

    conn.commit()
    conn.close()

    return {
        "processed": processed,
        "skipped_no_image": skipped_no_image,
        "errors": errors,
    }