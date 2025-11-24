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
    allow_origins=["*"],   # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"ok": True, "service": "vinyl-api", "db": DB_PATH}

@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "ts": int(time.time())}

@app.get("/health")
def health_root() -> Dict[str, Any]:
    return {"status": "ok"}

@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return {"status": "ok"}

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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cover_embeddings (
          record_id INTEGER PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
          vec TEXT NOT NULL,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

@app.on_event("startup")
def on_startup() -> None:
    folder = os.path.dirname(DB_PATH) or "."
    os.makedirs(folder, exist_ok=True)
    init_db()

def fetch_record(conn: sqlite3.Connection, rid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
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
    row = fetch_record(conn, rid)
    out = dict(row)
    conn.close()
    return out

def db_insert_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    keys = list(payload.keys())
    vals = [payload[k] for k in keys]
    placeholders = ", ".join("?" for _ in keys)
    cur.execute(
        f"INSERT INTO records ({', '.join(keys)}) VALUES ({placeholders})",
        tuple(vals),
    )
    rid = cur.lastrowid
    conn.commit()
    row = fetch_record(conn, rid)
    out = dict(row)
    conn.close()
    return out

def db_delete_records(ids: List[int]) -> int:
    if not ids:
        return 0
    conn = db()
    cur = conn.cursor()
    placeholders = ", ".join("?" for _ in ids)
    cur.execute(f"DELETE FROM records WHERE id IN ({placeholders})", tuple(ids))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

def db_get_tracks(rid: int) -> List[Dict[str, Any]]:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, record_id, side, position, title, duration FROM tracks WHERE record_id = ? ORDER BY id",
        (rid,),
    ).fetchall()
    out = [dict(r) for r in rows]
    conn.close()
    return out

def db_replace_tracks(rid: int, tracks: List[Dict[str, Any]]) -> None:
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

def bump_record_updated(rid: int) -> None:
    conn = db()
    conn.execute("UPDATE records SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

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

class RecordOut(RecordIn):
    id: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

class RecordsResponse(BaseModel):
    items: List[RecordOut]
    total: int

class DiscogsApplyIn(BaseModel):
    release_id: Optional[int] = Field(None, description="Discogs release id to force")

# NEW: track editing payloads
class TrackIn(BaseModel):
    side: Optional[str] = None
    position: Optional[str] = None
    title: str
    duration: Optional[str] = None

class TracksReplaceIn(BaseModel):
    tracks: List[TrackIn] = Field(default_factory=list)

# =============================================================================
# Listing / CRUD
# =============================================================================

@app.get("/api/records")
def list_records(
    search: Optional[str] = Query(None),
    sort_key: Optional[str] = Query("artist"),
    sort_dir: Optional[str] = Query("asc"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()

    clauses: List[str] = []
    params: List[Any] = []

    if search:
        like = f"%{search.strip()}%"
        clauses.append(
            "(artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ?)"
        )
        params.extend([like, like, like, like])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    sort_key = sort_key or "artist"
    if sort_key not in {"artist", "title", "year"}:
        sort_key = "artist"

    sort_dir = (sort_dir or "asc").lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"

    sql_base = f"FROM records {where_sql}"
    total = cur.execute(f"SELECT COUNT(*) {sql_base}", params).fetchone()[0]

    sql = f"SELECT * {sql_base} ORDER BY {sort_key} COLLATE NOCASE {sort_dir} LIMIT ? OFFSET ?"
    rows = cur.execute(sql, (*params, limit, offset)).fetchall()
    conn.close()

    items: List[Dict[str, Any]] = [dict(r) for r in rows]
    return {"items": items, "total": total}

@app.post("/api/records")
def create_record(payload: RecordIn = Body(...)) -> Dict[str, Any]:
    # Provide default country if blank
    if not (payload.country or "").strip():
        payload.country = "US"
    return db_insert_record(payload.dict())

@app.get("/api/meta/records/schema")
def meta_records_schema() -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute("PRAGMA table_info(records)").fetchall()
    conn.close()
    cols = []
    for r in rows:
        cols.append(
            {
                "cid": r["cid"],
                "name": r["name"],
                "type": r["type"],
                "notnull": r["notnull"],
                "dflt_value": r["dflt_value"],
                "pk": r["pk"],
            }
        )
    return {"columns": cols}

@app.get("/api/records/{rid}")
def get_record(rid: int) -> Dict[str, Any]:
    return db_get_record_or_404(rid)

@app.delete("/api/records/{rid}")
def delete_record(rid: int) -> Dict[str, Any]:
    deleted = db_delete_records([rid])
    return {"ok": True, "deleted": deleted}

@app.post("/api/records/bulk/delete")
def bulk_delete_records(ids: List[int] = Body(...)) -> Dict[str, Any]:
    deleted = db_delete_records(ids)
    return {"deleted": deleted}

# =============================================================================
# CSV export / import
# =============================================================================

@app.get("/api/meta/import-template")
def meta_import_template() -> Response:
    headers = [
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
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    csv_bytes = buf.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="vinyl_import_template.csv"'},
    )

@app.get("/api/export/csv")
def export_csv() -> Response:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM records ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE"
    ).fetchall()
    conn.close()

    headers = list(rows[0].keys()) if rows else []

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r[h] for h in headers])

    csv_bytes = buf.getvalue().encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="vinyl_records_export.csv"'},
    )

@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Import CSV rows into the records table.
    """

    def to_int_or_none(v: Any) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, int):
            return v
        s = str(v or "").strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None

    def nz(s: Any) -> str:
        if s is None:
            return ""
        if isinstance(s, str):
            return s.strip()
        return str(s).strip()

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    buf = io.StringIO(text)
    reader = csv.reader(buf)

    # Read header row
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(400, detail="CSV file is empty")

    # Map known columns (case-insensitive)
    header_map: Dict[str, str] = {}
    for i, col in enumerate(header):
        key = col.strip().lower()
        if not key:
            continue
        header_map[key] = col

    required = ["artist", "title"]
    for r in required:
        if r not in header_map:
            raise HTTPException(400, detail=f"Missing required column '{r}'")

    rows_imported = 0
    for row in reader:
        rec: Dict[str, Any] = {}
        for key, orig_col in header_map.items():
            idx = header.index(orig_col)
            if idx >= len(row):
                val = ""
            else:
                val = row[idx]
            if key == "artist":
                rec["artist"] = nz(val)
            elif key == "title":
                rec["title"] = nz(val)
            elif key == "year":
                rec["year"] = to_int_or_none(val)
            elif key == "label":
                rec["label"] = nz(val)
            elif key == "format":
                rec["format"] = nz(val)
            elif key == "country":
                rec["country"] = nz(val) or "US"
            elif key == "catalog_number":
                rec["catalog_number"] = nz(val)
            elif key == "barcode":
                rec["barcode"] = nz(val)
            elif key == "discogs_id":
                rec["discogs_id"] = to_int_or_none(val)
            elif key == "discogs_release_id":
                rec["discogs_release_id"] = to_int_or_none(val)
            elif key == "discogs_thumb":
                rec["discogs_thumb"] = nz(val)
            elif key == "cover_url":
                rec["cover_url"] = nz(val)
            elif key == "cover_local":
                rec["cover_local"] = nz(val)
            elif key == "cover_url_auto":
                rec["cover_url_auto"] = nz(val)
            elif key == "album_notes":
                rec["album_notes"] = nz(val)
            elif key == "personal_notes":
                rec["personal_notes"] = nz(val)

        artist = nz(rec.get("artist"))
        title = nz(rec.get("title"))
        if not artist or not title:
            continue

        if "country" not in rec or not rec["country"]:
            rec["country"] = "US"

        db_insert_record(rec)
        rows_imported += 1

    return {"imported": rows_imported}

# =============================================================================
# Tracks: simple APIs
# =============================================================================

@app.get("/api/records/{rid}/tracks")
def api_get_tracks(rid: int) -> List[Dict[str, Any]]:
    _ = db_get_record_or_404(rid)
    return db_get_tracks(rid)

# replace tracks with client-provided list (manual editing)
@app.post("/api/records/{rid}/tracks/replace")
def api_tracks_replace(rid: int, body: TracksReplaceIn) -> Dict[str, Any]:
    _ = db_get_record_or_404(rid)
    items = [{"side": t.side, "position": t.position, "title": t.title, "duration": t.duration} for t in body.tracks]
    db_replace_tracks(rid, items)
    bump_record_updated(rid)
    return {"ok": True, "count": len(items)}

# =============================================================================
# Discogs helpers (HTTP)
# =============================================================================

def _discogs_headers() -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if DISCOGS_TOKEN:
        # Either Authorization: "Discogs token=..." or query param ?token=...
        h["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
    return h

def _http_get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        import requests
    except Exception as e:
        raise HTTPException(500, detail=f"'requests' not installed: {e}")

    p = dict(params or {})
    if DISCOGS_TOKEN and "token" not in p:
        p["token"] = DISCOGS_TOKEN

    try:
        resp = requests.get(url, headers=_discogs_headers(), params=p, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        raise HTTPException(502, detail=f"Discogs HTTP error: {e}")

def discogs_release_details(release_id: int) -> Dict[str, Any]:
    return _http_get(f"{DISCOGS_API}/releases/{release_id}")

def _nz(x: Any) -> str:
    if x is None:
        return ""
    s = str(x).strip()
    return s

def _fmt_tokens_from_release_detail(detail: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    for f in (detail.get("formats") or []):
        name = _nz(f.get("name")).lower()
        desc = [str(x).lower() for x in (f.get("descriptions") or [])]
        tokens.extend([name, *desc])
    return tokens

def candidate_allowed_release(detail: Dict[str, Any], required_country: Optional[str]) -> bool:
    tokens = set(_fmt_tokens_from_release_detail(detail))
    if "lp" not in tokens:
        return False
    if required_country:
        if _nz(detail.get("country")).upper() != required_country.upper():
            return False
    return True

def country_pref(row: Dict[str, Any]) -> str:
    c = _nz(row.get("country")).upper()
    return c or "US"

def pick_best_image(detail: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    images = detail.get("images") or []
    if not images:
        return None, None

    primary = None
    secondary = None
    for img in images:
        if img.get("type") == "primary" and img.get("uri"):
            primary = img
            break
    if not primary:
        for img in images:
            if img.get("uri"):
                secondary = img
                break

    chosen = primary or secondary or images[0]
    cover = chosen.get("uri")
    thumb = chosen.get("uri150") or chosen.get("resource_url")
    return cover, thumb

def candidate_allowed_search(item: Dict[str, Any], required_country: Optional[str]) -> bool:
    fmt = " ".join((item.get("format") or [])).lower()
    if "lp" not in fmt and "vinyl" not in fmt:
        return False
    if required_country:
        c = _nz(item.get("country")).upper()
        if c and c != required_country.upper():
            return False
    return True

def discogs_query_plan_for_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    artist = _nz(row.get("artist"))
    title = _nz(row.get("title"))
    year  = _nz(row.get("year"))
    cat   = _nz(row.get("catalog_number"))
    barcode = _nz(row.get("barcode"))

    params_list: List[Dict[str, Any]] = []

    if barcode:
        params_list.append({"barcode": barcode, "type": "release"})

    if cat:
        params_list.append({"catno": cat, "artist": artist, "release_title": title, "type": "release"})

    base = {"artist": artist, "release_title": title, "type": "release"}
    params_list.append(base)

    if year:
        params_list.append({**base, "year": year})

    return params_list

def score_candidate_search_item(item: Dict[str, Any], row: Dict[str, Any]) -> int:
    """
    Simple heuristic on search items (no extra HTTP).
    """
    score = 0
    artist = _nz(row.get("artist")).lower()
    title = _nz(row.get("title")).lower()
    year  = _nz(row.get("year"))

    cand_artist = _nz(item.get("artist")).lower()
    cand_title  = _nz(item.get("title")).lower()
    cand_year   = _nz(item.get("year"))

    if cand_artist and artist:
        score += 25 if cand_artist == artist else (12 if artist in cand_artist else 0)
    if cand_title and title:
        score += 25 if cand_title == title else (12 if title in cand_title else 0)
    if year and cand_year:
        try:
            if int(cand_year) == int(year):
                score += 10
        except Exception:
            pass

    return score

def derive_best_release_id_for_record(rid: int) -> Optional[int]:
    """
    Use the Discogs search API plus a bit of heuristic scoring to pick an LP release
    that matches the record (preferring correct country, year, and exact artist/title).
    """
    row = db_get_record_or_404(rid)
    required_country = country_pref(row)

    best_id: Optional[int] = None
    best_score = -1

    for params in discogs_query_plan_for_row(row):
        js = _http_get(f"{DISCOGS_API}/database/search", params)
        for item in js.get("results") or []:
            if not candidate_allowed_search(item, required_country):
                continue
            sc = score_candidate_search_item(item, row)
            if sc > best_score:
                try:
                    cand_id = int(item.get("id"))
                except Exception:
                    continue
                best_score = sc
                best_id = cand_id

        if best_id is not None and best_score >= 40:
            break

    return best_id

# Discogs search helpers used by the picker UI
# (now also respect LP-only + country in the results)
# =============================================================================

@app.get("/api/records/{rid}/discogs/search")
def api_discogs_search_for_record(rid: int) -> Dict[str, Any]:
    row = db_get_record_or_404(rid)
    required_country = country_pref(row)

    out: List[Dict[str, Any]] = []
    for params in discogs_query_plan_for_row(row):
        js = _http_get(f"{DISCOGS_API}/database/search", params)
        for r in js.get("results") or []:
            if not candidate_allowed_search(r, required_country):
                continue
            out.append({
                "id": r.get("id"),
                "title": r.get("title"),
                "year": r.get("year"),
                "country": r.get("country"),
                "label": r.get("label"),
                "format": r.get("format"),
                "thumb": r.get("thumb"),
            })
        if out:
            break  # first query with results is enough
    return {"results": out}

@app.get("/api/discogs/release/{release_id}")
def api_discogs_release_preview(release_id: int) -> Dict[str, Any]:
    return discogs_release_details(release_id)

# =============================================================================
# API: Discogs cover + tracks  (LP-only + required country)
# =============================================================================

@app.post("/api/records/{rid}/cover/fetch")
def api_cover_fetch(rid: int, body: Optional[DiscogsApplyIn] = Body(None)) -> Dict[str, Any]:
    _ = db_get_record_or_404(rid)

    # If caller forced a release, use it (but still honor LP + country when we fetch images)
    if body and body.release_id:
        release_id = int(body.release_id)
    else:
        release_id = derive_best_release_id_for_record(rid)

    if not release_id:
        raise HTTPException(404, detail="No suitable Discogs LP release found for required country")

    row = db_get_record_or_404(rid)
    detail = discogs_release_details(release_id)
    if not candidate_allowed_release(detail, country_pref(row)):
        raise HTTPException(404, detail="Chosen release does not satisfy LP + country constraint")

    cover_url_auto, discogs_thumb = pick_best_image(detail)
    if not cover_url_auto and not discogs_thumb:
        raise HTTPException(404, detail="Matching release has no images")

    payload: Dict[str, Any] = {
        "discogs_release_id": int(detail.get("id") or release_id),
        "cover_url_auto": cover_url_auto,
    }
    if discogs_thumb:
        payload["discogs_thumb"] = discogs_thumb

    updated = db_patch_record(rid, payload)
    return updated

@app.post("/api/records/{rid}/tracks/save")
def api_tracks_save(rid: int, body: Optional[DiscogsApplyIn] = Body(None)) -> Dict[str, Any]:
    _ = db_get_record_or_404(rid)
    if body and body.release_id:
        release_id = int(body.release_id)
    else:
        release_id = derive_best_release_id_for_record(rid)

    if not release_id:
        raise HTTPException(404, detail="No suitable Discogs LP release found for required country")

    row = db_get_record_or_404(rid)
    detail = discogs_release_details(release_id)
    if not candidate_allowed_release(detail, country_pref(row)):
        raise HTTPException(404, detail="Chosen release does not satisfy LP + country constraint")

    tracks = discogs_fetch_tracklist_for_release(release_id, detail)
    items = [{"side": t["side"], "position": t["position"], "title": t["title"], "duration": t["duration"]} for t in tracks]
    db_replace_tracks(rid, items)
    bump_record_updated(rid)
    return {"ok": True, "count": len(tracks)}

# =============================================================================
# Tracklist extraction (reused)
# =============================================================================

def discogs_fetch_tracklist_for_release(release_id: int, detail: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Accepts optional pre-fetched release detail to avoid a second HTTP call.
    """
    rel = detail or discogs_release_details(release_id)
    out: List[Dict[str, Any]] = []
    for t in rel.get("tracklist", []) or []:
        pos = (t.get("position") or "").strip()
        title = (t.get("title") or "").strip()
        duration = (t.get("duration") or "").strip()
        # Best-effort side from position's leading letter (A, B, C, ...)
        side = "A"
        if pos and pos[0].isalpha():
            side = pos[0].upper()
        out.append({"position": pos, "title": title, "duration": duration, "side": side})
    return out

# =============================================================================
# Cover image embeddings & matching (CLIP-based, with rotations)
# =============================================================================

_CLIP_MODEL = None
_CLIP_PREPROCESS = None
_CLIP_DEVICE = "cpu"

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

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_name = os.environ.get("CLIP_MODEL_NAME", "ViT-B/32")
    model, preprocess = clip.load(model_name, device=device)
    model.eval()

    _CLIP_MODEL = model
    _CLIP_PREPROCESS = preprocess
    _CLIP_DEVICE = device
    return model, preprocess, device

def compute_image_embedding(image_bytes: bytes) -> List[float]:
    """
    Compute a normalized image embedding vector from raw image bytes using CLIP.
    """
    try:
        from PIL import Image  # type: ignore
        import torch           # type: ignore
    except Exception as e:
        raise HTTPException(500, detail=f"Image/torch dependencies not available: {e}")

    from io import BytesIO

    model, preprocess, device = get_clip_model()

    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, detail=f"Could not decode image: {e}")

    with torch.no_grad():
        image_tensor = preprocess(img).unsqueeze(0).to(device)
        features = model.encode_image(image_tensor)
        features = features / features.norm(dim=-1, keepdim=True)
        vec: List[float] = features[0].cpu().tolist()
    return vec

def compute_cover_embeddings_with_rotations(image_bytes: bytes) -> List[List[float]]:
    """
    For cover images, compute multiple embeddings:
    - Original
    - Rotated slightly (e.g., -5°, +5°)

    This makes matching more robust to tilted phone photos.
    """
    try:
        from PIL import Image  # type: ignore
        import torch           # type: ignore
    except Exception as e:
        raise HTTPException(500, detail=f"Image/torch dependencies not available: {e}")

    from io import BytesIO

    model, preprocess, device = get_clip_model()

    try:
        base_img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        raise HTTPException(400, detail=f"Could not decode image: {e}")

    angles = [0, -5, 5]  # degrees
    vecs: List[List[float]] = []

    with torch.no_grad():
        for ang in angles:
            if ang == 0:
                img = base_img
            else:
                img = base_img.rotate(ang, resample=Image.BICUBIC, expand=True)
            image_tensor = preprocess(img).unsqueeze(0).to(device)
            features = model.encode_image(image_tensor)
            features = features / features.norm(dim=-1, keepdim=True)
            v: List[float] = features[0].cpu().tolist()
            vecs.append(v)

    return vecs

def save_cover_embedding(conn: sqlite3.Connection, record_id: int, vecs: List[List[float]]) -> None:
    """
    Persist one or more cover embedding vectors for a record into the cover_embeddings table.
    Stored as JSON list-of-lists. For older data that had a single vector, we treat that
    as a single-element list at read time.
    """
    conn.execute(
        "INSERT OR REPLACE INTO cover_embeddings(record_id, vec, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (record_id, json.dumps(vecs)),
    )

def get_all_cover_embeddings(conn: sqlite3.Connection) -> List[Tuple[int, List[List[float]]]]:
    """
    Return all stored cover embeddings as (record_id, [vectors...]) pairs.
    Each record may have multiple vectors due to rotation augmentation.
    """
    rows = conn.execute("SELECT record_id, vec FROM cover_embeddings").fetchall()
    out: List[Tuple[int, List[List[float]]]] = []
    for r in rows:
        try:
            raw = json.loads(r["vec"])
            if not isinstance(raw, list):
                continue
            if raw and isinstance(raw[0], (int, float, str)):
                vecs = [[float(x) for x in raw]]
            else:
                vecs = []
                for v in raw:
                    if isinstance(v, list):
                        vecs.append([float(x) for x in v])
            if vecs:
                out.append((int(r["record_id"]), vecs))
        except Exception:
            continue
    return out

def fetch_image_bytes_for_record(row: sqlite3.Row) -> Optional[bytes]:
    """
    Fetch cover image bytes using:
    1. Local file   (cover_local)
    2. Remote URLs  (cover_url, cover_url_auto, discogs_thumb)
    Uses Discogs-style headers to avoid 403 from the CDN.
    """
    local_path = row["cover_local"]

    if local_path:
        try:
            path = str(local_path)
            if not os.path.isabs(path):
                base = os.path.dirname(DB_PATH) or "."
                path = os.path.join(base, path)
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            pass

    url = row["cover_url"] or row["cover_url_auto"] or row["discogs_thumb"]
    if not url:
        return None

    try:
        import requests  # type: ignore
    except Exception as e:
        raise HTTPException(500, detail=f"'requests' not available for image fetching: {e}")

    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/*,*/*",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None

def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Basic cosine similarity between two equal-length vectors.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

@app.post("/api/cover-match")
async def api_cover_match(file: UploadFile = File(...)) -> Dict[str, Any]:
  """
  Accept an uploaded cover photo, compute a CLIP embedding, and find the closest
  matching record in the existing cover_embeddings table.
  """
  image_bytes = await file.read()
  if not image_bytes:
      raise HTTPException(400, detail="Empty file upload")

  query_vec = compute_image_embedding(image_bytes)

  conn = db()
  try:
      candidates = get_all_cover_embeddings(conn)
      if not candidates:
          raise HTTPException(
              404,
              detail="No cover embeddings present. Populate them via /api/cover-embeddings/rebuild.",
          )

      scored: List[Tuple[int, float]] = []
      for rid, vecs in candidates:
          if not vecs:
              continue
          best_for_record = max(cosine_similarity(query_vec, v) for v in vecs)
          scored.append((rid, best_for_record))

      if not scored:
          raise HTTPException(404, detail="No valid embeddings to compare against.")

      scored.sort(key=lambda x: x[1], reverse=True)
      best_id, best_score = scored[0]
      second_best_score = scored[1][1] if len(scored) > 1 else 0.0
      gap = best_score - second_best_score

      top = scored[:5]
      ids = [rid for rid, _ in top]
      placeholders = ",".join("?" for _ in ids)
      rows = conn.execute(
          f"SELECT id, artist, title FROM records WHERE id IN ({placeholders})",
          ids,
      ).fetchall()
      meta_by_id = {int(r["id"]): r for r in rows}

      candidates_out: List[Dict[str, Any]] = []
      for rid, score in top:
          row = meta_by_id.get(int(rid))
          candidates_out.append(
              {
                  "id": int(rid),
                  "artist": (row["artist"] if row else None),
                  "title": (row["title"] if row else None),
                  "score": float(score),
              }
          )

      min_score = float(os.environ.get("COVER_MATCH_MIN_SCORE", "0.35"))
      min_gap = float(os.environ.get("COVER_MATCH_MIN_GAP", "0.05"))

      if best_score >= min_score and gap >= min_gap:
          match_id: Optional[int] = int(best_id)
      else:
          match_id = None

      return {
          "match": match_id,
          "score": float(best_score),
          "candidates": candidates_out,
      }
  finally:
      conn.close()

@app.post("/api/cover-embeddings/rebuild")
def api_rebuild_cover_embeddings(limit: Optional[int] = Query(None)) -> Dict[str, Any]:
    """
    Build (or refresh) cover embeddings for records that have an associated cover.
    """
    conn = db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM records ORDER BY id").fetchall()

    processed = 0
    skipped_no_image = 0
    errors = 0

    for row in rows:
        if limit is not None and processed >= limit:
            break

        rid = int(row["id"])
        try:
            img_bytes = fetch_image_bytes_for_record(row)
            if not img_bytes:
                skipped_no_image += 1
                continue

            vecs = compute_cover_embeddings_with_rotations(img_bytes)
            save_cover_embedding(conn, rid, vecs)
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