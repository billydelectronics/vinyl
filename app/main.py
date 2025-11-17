from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import csv, io
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
    # Ensure foreign keys are enforced for this connection
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

def db_get_tracks(rid: int) -> List[Dict[str, Any]]:
    conn = db()
    rows = conn.execute(
        "SELECT id, record_id, side, position, title, duration FROM tracks WHERE record_id = ? ORDER BY id",
        (rid,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_replace_tracks(rid: int, tracks: List[Dict[str, Any]]) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (rid,))
    for t in tracks:
        cur.execute(
            "INSERT INTO tracks (record_id, side, position, title, duration) VALUES (?, ?, ?, ?, ?)",
            (rid, t.get("side"), t.get("position"), t.get("title"), t.get("duration")),
        )
    conn.commit()
    conn.close()

def bump_record_updated(rid: int) -> None:
    conn = db()
    conn.execute("UPDATE records SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

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
    # add ?token=... if available (keeps Authorization for compatibility)
    p = dict(params or {})
    if DISCOGS_TOKEN and "token" not in p:
        p["token"] = DISCOGS_TOKEN
    r = requests.get(url, params=p, headers=_discogs_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code == 404:
        raise HTTPException(404, detail="Discogs resource not found")
    r.raise_for_status()
    return r.json()

def discogs_release_details(release_id: int) -> Dict[str, Any]:
    return _http_get(f"{DISCOGS_API}/releases/{release_id}")

# =============================================================================
# Best-match search (Country mandatory + LP-only)
# =============================================================================

def _nz(v: Any) -> str:
    return ("" if v is None else str(v)).strip()

def country_pref(row: Dict[str, Any]) -> str:
    """
    Country is mandatory. Use record.country if present/trimmed, else 'US'.
    """
    c = _nz(row.get("country"))
    return c if c else "US"

def make_search_base(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Base Discogs search params. Enforce release type, country, and LP-only.
    """
    return {
        "type": "release",
        "country": country_pref(row),  # mandatory
        "format": "LP",                # LP-only
        "per_page": 50,
        "page": 1,
    }

def _fmt_tokens_from_search_item(item: Dict[str, Any]) -> List[str]:
    # Search results usually expose 'format': ["LP","Album",...]
    fmt = item.get("format")
    if isinstance(fmt, list):
        return [str(x).lower() for x in fmt]
    return []

def _fmt_tokens_from_release_detail(detail: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    for f in (detail.get("formats") or []):
        name = str(f.get("name") or "").lower()
        if name:
            tokens.append(name)
        for d in (f.get("descriptions") or []):
            tokens.append(str(d).lower())
    return tokens

def candidate_allowed_search(item: Dict[str, Any], required_country: str) -> bool:
    # Enforce country
    if _nz(item.get("country")) != required_country:
        return False
    # Enforce LP in format tokens
    tokens = set(_fmt_tokens_from_search_item(item))
    return "lp" in tokens

def candidate_allowed_release(detail: Dict[str, Any], required_country: str) -> bool:
    if _nz(detail.get("country")) != required_country:
        return False
    tokens = set(_fmt_tokens_from_release_detail(detail))
    return "lp" in tokens

def discogs_query_plan_for_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Construct search params from most precise -> least precise, all inheriting base(country, LP).
    """
    base = make_search_base(row)
    artist = _nz(row.get("artist"))
    title  = _nz(row.get("title"))
    year   = row.get("year") if _nz(row.get("year")).isdigit() else None
    label  = _nz(row.get("label"))
    catno  = _nz(row.get("catalog_number"))
    barcode = _nz(row.get("barcode"))

    plan: List[Dict[str, Any]] = []

    # Barcode
    if barcode:
        p = dict(base)
        p["barcode"] = barcode
        if year: p["year"] = year
        plan.append(p)

    # Catalog number (+ narrowing fields)
    if catno:
        p = dict(base)
        p["catno"] = catno
        if label:  p["label"] = label
        if artist: p["artist"] = artist
        if year:   p["year"] = year
        plan.append(p)

    # Structured artist/title (+ year)
    if artist or title:
        p = dict(base)
        if artist: p["artist"] = artist
        if title:  p["release_title"] = title
        if year:   p["year"] = year
        plan.append(p)

    # Loose q fallback
    if artist or title:
        p = dict(base)
        p["q"] = " ".join([artist, title]).strip()
        if year: p["year"] = year
        plan.append(p)

    # Dedup
    seen = set()
    out: List[Dict[str, Any]] = []
    for d in plan:
        key = tuple(sorted(d.items()))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

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
    if cand_year and year and cand_year == year:
        score += 10

    # Prefer results that mention "Album"
    tokens = set(_fmt_tokens_from_search_item(item))
    if "album" in tokens:
        score += 4

    # Prefer items with a thumb
    if _nz(item.get("thumb")):
        score += 3

    return score

def pick_best_image(detail: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    imgs = detail.get("images") or []
    if not imgs:
        return None, None
    primary = next((i for i in imgs if (i.get("type") == "primary") or i.get("front")), None)
    best = primary or imgs[0]
    full = best.get("uri") or best.get("resource_url")
    thumb = best.get("uri150") or best.get("resource_url")
    return full, thumb

# ---- Core: derive best release id for a record (LP-only + country mandatory) ----

def derive_best_release_id_for_record(rid: int) -> Optional[int]:
    """
    Choose the Discogs release id for this record.

    Priority:
      1) Manual `discogs_id` (use directly if it's a valid positive int).
      2) Existing `discogs_release_id` on the record (if present).
      3) Best-match search constrained to LP-only and required country.

    Notes:
      - We do NOT enforce LP/country constraints on the manual IDs; user intent wins.
      - Best-match search continues to enforce LP-only + required country.
    """
    # Load row once
    conn = db()
    row = fetch_record(conn, rid)
    row_dict = dict(row)
    conn.close()

    # 1) Manual override: if user set discogs_id, trust it (as a release id)
    manual = row_dict.get("discogs_id")
    if manual is not None:
        try:
            mid = int(manual)
            if mid > 0:
                return mid
        except Exception:
            pass  # fall through

    # 2) If record already has a discogs_release_id stored, prefer it next
    explicit_release = row_dict.get("discogs_release_id")
    if explicit_release is not None:
        try:
            erid = int(explicit_release)
            if erid > 0:
                return erid
        except Exception:
            pass  # fall through

    # 3) Best-match search (LP-only + mandatory country)
    required_country = country_pref(row_dict)
    plan = discogs_query_plan_for_row(row_dict)

    best_id: Optional[int] = None
    best_score = -10**9

    for params in plan:
        try:
            js = _http_get(f"{DISCOGS_API}/database/search", params)
        except Exception:
            continue

        results = js.get("results") or []
        # Filter to allowed (LP-only, required country) based on search item shape
        allowed = [it for it in results if candidate_allowed_search(it, required_country)]
        if not allowed:
            continue

        # Score and pick
        for it in allowed:
            sc = score_candidate_search_item(it, row_dict)
            if sc > best_score:
                try:
                    cand_id = int(it.get("id"))
                except Exception:
                    continue
                best_score = sc
                best_id = cand_id

        # Early exit if strong enough
        if best_id is not None and best_score >= 40:
            break

    return best_id

# =============================================================================
# Models
# =============================================================================

class RecordCreate(BaseModel):
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

class RecordPatch(RecordCreate):
    pass

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

# NEW: bulk delete payload
class BulkDeleteIn(BaseModel):
    ids: List[int] = Field(default_factory=list)

# =============================================================================
# API: records list + create + schema
# =============================================================================

@app.get("/api/records")
def api_list_records(
    q: Optional[str] = Query(None, description="search text across artist/title/label/catalog_number/barcode"),
    sort: str = Query("updated_at", pattern="^(id|artist|title|year|label|updated_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    sql = "SELECT * FROM records"
    args: List[Any] = []
    if q:
        sql += " WHERE (artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)"
        like = f"%{q}%"
        args.extend([like, like, like, like, like])
    sql += f" ORDER BY {sort} {order.upper()} LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    conn = db()
    rows = conn.execute(sql, tuple(args)).fetchall()
    if q:
        cnt = conn.execute(
            "SELECT COUNT(*) as c FROM records WHERE (artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)",
            (like, like, like, like, like),
        ).fetchone()["c"]
    else:
        cnt = conn.execute("SELECT COUNT(*) as c FROM records").fetchone()["c"]
    conn.close()
    return {"items": [dict(r) for r in rows], "count": cnt, "limit": limit, "offset": offset}

@app.post("/api/records")
def api_create_record(payload: RecordCreate) -> Dict[str, Any]:
    data = {k: v for k, v in payload.dict().items()}
    for k in ("artist", "title"):
        data.setdefault(k, None)
    # Default country to US if not provided/blank
    if not (data.get("country") or "").strip():
        data["country"] = "US"
    created = db_insert_record(data)
    return created

@app.get("/api/meta/records/schema")
def api_records_schema() -> Dict[str, Any]:
    fields = [
        {"name": "artist", "type": "text"},
        {"name": "title", "type": "text"},
        {"name": "year", "type": "number"},
        {"name": "label", "type": "text"},
        {"name": "format", "type": "text"},
        {"name": "country", "type": "text"},
        {"name": "catalog_number", "type": "text"},
        {"name": "barcode", "type": "text"},
        {"name": "discogs_id", "type": "number"},
        {"name": "discogs_release_id", "type": "number"},
        {"name": "discogs_thumb", "type": "text"},
        {"name": "cover_url", "type": "text"},
        {"name": "cover_local", "type": "text"},
        {"name": "cover_url_auto", "type": "text"},
        {"name": "album_notes", "type": "textarea"},
        {"name": "personal_notes", "type": "textarea"},
        {"name": "created_at", "type": "text"},
        {"name": "updated_at", "type": "text"},
    ]
    return {"fields": fields}

# Export ALL rows/columns as CSV
@app.get("/api/export/csv")
def api_export_csv() -> Response:
    """
    Export ALL rows and ALL columns from the `records` table as CSV.
    Column order follows PRAGMA table_info(records) (cid order).
    """
    conn = db()
    cur = conn.cursor()

    cols = [r["name"] for r in cur.execute("PRAGMA table_info(records)").fetchall()]
    if not cols:
        conn.close()
        return Response(content="", media_type="text/csv")

    rows = cur.execute(f"SELECT {', '.join(cols)} FROM records ORDER BY id").fetchall()
    conn.close()

    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(cols)
    for row in rows:
        writer.writerow([row[c] if row[c] is not None else "" for c in cols])
    csv_bytes = sio.getvalue()

    ts = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())
    headers = {"Content-Disposition": f'attachment; filename="records_export_{ts}.csv"'}
    return Response(content=csv_bytes, media_type="text/csv; charset=utf-8", headers=headers)

# =============================================================================
# API: record detail/patch/delete
# =============================================================================

@app.get("/api/records/{rid}")
def api_get_record(rid: int) -> Dict[str, Any]:
    return db_get_record_or_404(rid)

@app.patch("/api/records/{rid}")
def api_patch_record(rid: int, payload: RecordPatch) -> Dict[str, Any]:
    data = {k: v for k, v in payload.dict().items() if v is not None}
    return db_patch_record(rid, data)

@app.delete("/api/records/{rid}", status_code=204)
def api_delete_record(rid: int) -> None:
    # Explicitly delete tracks (in addition to foreign key cascade, for safety)
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (rid,))
    cur.execute("DELETE FROM records WHERE id = ?", (rid,))
    if cur.rowcount == 0:
        conn.commit()
        conn.close()
        raise HTTPException(404, detail="Record not found")
    conn.commit()
    conn.close()
    return None

@app.post("/api/records/bulk/delete")
def api_bulk_delete_records(body: BulkDeleteIn) -> Dict[str, Any]:
    ids = list({int(i) for i in (body.ids or []) if isinstance(i, int)})
    if not ids:
        return {"ok": True, "deleted": 0}
    conn = db()
    cur = conn.cursor()
    # Remove tracks first for reliability (plus FKs)
    cur.executemany("DELETE FROM tracks WHERE record_id = ?", [(i,) for i in ids])
    cur.executemany("DELETE FROM records WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    remaining = cur.execute(
        f"SELECT COUNT(*) AS c FROM records WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    ).fetchone()["c"]
    conn.close()
    return {"ok": True, "deleted": len(ids) - int(remaining)}

# =============================================================================
# API: CSV Import (defaults country="US", coerces numeric fields)
# =============================================================================

@app.post("/api/import/csv")
async def api_import_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Import records from a CSV file.

    - Accepts a header row and any subset of allowed fields.
    - Defaults country to "US" when blank/missing.
    - Coerces numeric fields (year, discogs_id, discogs_release_id).
    - Treats empty strings as NULL (None).
    - Returns a summary of inserted rows and any per-row errors.
    """
    ALLOWED_INPUT_FIELDS = {
        "artist", "title", "year", "label", "format", "country",
        "catalog_number", "barcode",
        "discogs_id", "discogs_release_id",
        "discogs_thumb", "cover_url", "cover_local", "cover_url_auto",
        "album_notes", "personal_notes",
    }

    FIELD_ALIASES = {
        "artist": "artist",
        "title": "title",
        "year": "year",
        "label": "label",
        "format": "format",
        "country": "country",
        "catalog_number": "catalog_number",
        "catno": "catalog_number",
        "catalog #": "catalog_number",
        "catalog no": "catalog_number",
        "catalog no.": "catalog_number",
        "barcode": "barcode",
        "discogs_id": "discogs_id",
        "discogs id": "discogs_id",
        "discogsid": "discogs_id",
        "discogs_release_id": "discogs_release_id",
        "discogs release id": "discogs_release_id",
        "discogs_thumb": "discogs_thumb",
        "discogs thumb": "discogs_thumb",
        "cover_url": "cover_url",
        "cover url": "cover_url",
        "cover_local": "cover_local",
        "cover local": "cover_local",
        "cover_url_auto": "cover_url_auto",
        "cover url auto": "cover_url_auto",
        "album_notes": "album_notes",
        "album notes": "album_notes",
        "personal_notes": "personal_notes",
        "personal notes": "personal_notes",
    }

    def canon_key(k: str) -> Optional[str]:
        if not k:
            return None
        lk = k.strip().lower()
        return FIELD_ALIASES.get(lk)

    def to_int_or_none(v: Any) -> Optional[int]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                return None
            try:
                return int(s)
            except Exception:
                return None
        try:
            return int(v)
        except Exception:
            return None

    def nz(s: Any) -> Optional[str]:
        # normalize empty strings to None; trim strings
        if s is None:
            return None
        if isinstance(s, str):
            s2 = s.strip()
            return s2 if s2 != "" else None
        return s

    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")  # strip BOM if present
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(400, detail="CSV file has no header row")

    header_map: Dict[str, str] = {}
    for raw in reader.fieldnames:
        key = canon_key(raw)
        if key and key in ALLOWED_INPUT_FIELDS:
            header_map[raw] = key
        # unknown columns ignored

    if not header_map:
        raise HTTPException(400, detail="CSV header has no recognized columns")

    added = 0
    errors: List[Dict[str, Any]] = []
    row_idx = 1  # 1-based (excluding header)

    for raw_row in reader:
        row_idx += 1
        try:
            rec: Dict[str, Any] = {}
            for k_raw, v in raw_row.items():
                if k_raw in header_map:
                    key = header_map[k_raw]
                    rec[key] = nz(v)

            # Coerce numeric fields
            if "year" in rec:
                rec["year"] = to_int_or_none(rec.get("year"))
            if "discogs_id" in rec:
                rec["discogs_id"] = to_int_or_none(rec.get("discogs_id"))
            if "discogs_release_id" in rec:
                rec["discogs_release_id"] = to_int_or_none(rec.get("discogs_release_id"))

            # Default country to US if blank/missing
            if not rec.get("country"):
                rec["country"] = "US"

            # Ensure required keys exist
            rec.setdefault("artist", None)
            rec.setdefault("title", None)

            _ = db_insert_record(rec)
            added += 1

        except HTTPException as he:
            errors.append({
                "row": row_idx,
                "error": he.detail,
                "row_data": raw_row
            })
        except Exception as e:
            errors.append({
                "row": row_idx,
                "error": str(e),
                "row_data": raw_row
            })

    return {"ok": True, "added": added, "errors": errors}

# =============================================================================
# API: tracks
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

    detail = discogs_release_details(release_id)
    # Double-check constraints on the chosen detail:
    row = db_get_record_or_404(rid)
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

    # Optional: verify constraints again on detail before importing tracks
    row = db_get_record_or_404(rid)
    detail = discogs_release_details(release_id)
    if not candidate_allowed_release(detail, country_pref(row)):
        raise HTTPException(404, detail="Chosen release does not satisfy LP + country constraint")

    # Extract and store tracks
    tracks = discogs_fetch_tracklist_for_release(release_id, detail=detail)
    db_replace_tracks(rid, tracks)
    bump_record_updated(rid)
    return {"ok": True, "count": len(tracks)}

# =============================================================================
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