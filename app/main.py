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

# =============================================================================
# FastAPI app
# =============================================================================

app = FastAPI(title="Vinyl API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# Simple health endpoints
# =============================================================================

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
    # Enable WAL mode for better concurrency; fall back silently if unsupported
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass

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

# =============================================================================
# Basic DB utilities: records + tracks
# =============================================================================

def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

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

# =============================================================================
# Pydantic models
# =============================================================================

class RecordIn(BaseModel):
    artist: str = Field(..., description="Artist / performer")
    title: str = Field(..., description="Album / release title")
    year: Optional[int] = Field(None, description="Release year (if known)")
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
    release_id: Optional[int] = Field(None, description="Discogs release id to force")

# =============================================================================
# Utility helpers
# =============================================================================

def to_int_or_none(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def parse_bool_param(s: Optional[str], default: bool = False) -> bool:
    if s is None:
        return default
    s = s.strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default

def like_pattern(s: str) -> str:
    return f"%{s.replace('%', '%%')}%"

def country_pref(row: sqlite3.Row) -> Optional[str]:
    c = (row["country"] or "").strip()
    if not c:
        return None
    return c.upper()

# =============================================================================
# API: metadata
# =============================================================================

@app.get("/api/meta/schema")
def meta_schema() -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute("PRAGMA table_info(records)").fetchall()
    cols: List[Dict[str, Any]] = []
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
        "id",
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
    outf = io.StringIO()
    writer = csv.writer(outf)
    writer.writerow(headers)
    data = outf.getvalue().encode("utf-8")
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="import_template.csv"'},
    )

@app.get("/api/records/export")
def export_records() -> Response:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM records ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE, id").fetchall()

    headers = [
        "id",
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

    outf = io.StringIO()
    writer = csv.writer(outf)
    writer.writerow(headers)
    for r in rows:
        row = [r["id"]]
        for col in headers[1:]:
            row.append(r[col])
        writer.writerow(row)

    data = outf.getvalue().encode("utf-8")
    conn.close()
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="records_export.csv"'},
    )

@app.post("/api/records/import")
def import_records(file: UploadFile = File(...)) -> Dict[str, Any]:
    content = file.file.read()
    file.file.close()
    try:
        text = content.decode("utf-8")
    except Exception:
        raise HTTPException(400, detail="Expected UTF-8 CSV")

    reader = csv.DictReader(io.StringIO(text))
    required_columns = {"artist", "title"}
    for col in required_columns:
        if col not in reader.fieldnames:
            raise HTTPException(400, detail=f"Missing required column: {col}")

    conn = db()
    cur = conn.cursor()

    rows_imported = 0
    for row in reader:
        artist = (row.get("artist") or "").strip()
        title = (row.get("title") or "").strip()
        if not artist or not title:
            continue

        rec: Dict[str, Any] = {
            "artist": artist,
            "title": title,
            "year": to_int_or_none(row.get("year")),
            "label": (row.get("label") or "").strip() or None,
            "format": (row.get("format") or "").strip() or None,
            "country": (row.get("country") or "").strip() or None,
            "catalog_number": (row.get("catalog_number") or "").strip() or None,
            "barcode": (row.get("barcode") or "").strip() or None,
            "discogs_id": to_int_or_none(row.get("discogs_id")),
            "discogs_release_id": to_int_or_none(row.get("discogs_release_id")),
            "discogs_thumb": (row.get("discogs_thumb") or "").strip() or None,
            "cover_url": (row.get("cover_url") or "").strip() or None,
            "cover_local": (row.get("cover_local") or "").strip() or None,
            "cover_url_auto": (row.get("cover_url_auto") or "").strip() or None,
            "album_notes": (row.get("album_notes") or "").strip() or None,
            "personal_notes": (row.get("personal_notes") or "").strip() or None,
        }

        cur.execute(
            """
            INSERT INTO records (
              artist, title, year, label, format, country,
              catalog_number, barcode, discogs_id, discogs_release_id,
              discogs_thumb, cover_url, cover_local, cover_url_auto,
              album_notes, personal_notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec["artist"],
                rec["title"],
                rec["year"],
                rec["label"],
                rec["format"],
                rec["country"],
                rec["catalog_number"],
                rec["barcode"],
                rec["discogs_id"],
                rec["discogs_release_id"],
                rec["discogs_thumb"],
                rec["cover_url"],
                rec["cover_local"],
                rec["cover_url_auto"],
                rec["album_notes"],
                rec["personal_notes"],
            ),
        )
        rows_imported += 1

    conn.commit()
    conn.close()
    return {"imported": rows_imported}

# =============================================================================
# Tracks: simple APIs
# =============================================================================

@app.get("/api/records/{rid}/tracks")
def api_get_tracks(rid: int) -> List[Dict[str, Any]]:
    _ = db_get_record_or_404(rid)
    return db_get_tracks(rid)

@app.post("/api/records/{rid}/tracks/replace")
def api_tracks_replace(rid: int, body: TracksReplaceIn) -> Dict[str, Any]:
    _ = db_get_record_or_404(rid)
    items = [{"side": t.side, "position": t.position, "title": t.title, "duration": t.duration} for t in body.tracks]
    db_replace_tracks(rid, items)
    return {"ok": True, "count": len(items)}

# =============================================================================
# API: listing / filtering records for read UI
# =============================================================================

class ListRecordsResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int

@app.get("/api/records")
def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    folder: Optional[str] = Query(None),
    sort_key: str = Query("artist"),
    sort_dir: str = Query("asc"),
) -> ListRecordsResponse:
    offset = (page - 1) * page_size
    conn = db()
    cur = conn.cursor()

    where_clauses = []
    params: List[Any] = []

    if search:
        like = like_pattern(search)
        where_clauses.append(
            "(artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)"
        )
        params.extend([like, like, like, like, like])

    if folder:
        where_clauses.append("country = ?")
        params.append(folder)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sort_col = "artist"
    if sort_key in ("artist", "title", "year", "label", "country"):
        sort_col = sort_key

    sort_dir_sql = "ASC"
    if sort_dir.lower() == "desc":
        sort_dir_sql = "DESC"

    total = cur.execute(f"SELECT COUNT(*) AS c FROM records {where_sql}", params).fetchone()["c"]

    rows = cur.execute(
        f"""
        SELECT *
        FROM records
        {where_sql}
        ORDER BY {sort_col} COLLATE NOCASE {sort_dir_sql}, id
        LIMIT ? OFFSET ?
        """,
        params + [page_size, offset],
    ).fetchall()

    items = [dict(r) for r in rows]
    conn.close()
    return ListRecordsResponse(items=items, total=total)

# =============================================================================
# API: create / patch records
# =============================================================================

def db_insert_record(rec: Dict[str, Any]) -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO records (
          artist, title, year, label, format, country,
          catalog_number, barcode, discogs_id, discogs_release_id,
          discogs_thumb, cover_url, cover_local, cover_url_auto,
          album_notes, personal_notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rec.get("artist"),
            rec.get("title"),
            rec.get("year"),
            rec.get("label"),
            rec.get("format"),
            rec.get("country"),
            rec.get("catalog_number"),
            rec.get("barcode"),
            rec.get("discogs_id"),
            rec.get("discogs_release_id"),
            rec.get("discogs_thumb"),
            rec.get("cover_url"),
            rec.get("cover_local"),
            rec.get("cover_url_auto"),
            rec.get("album_notes"),
            rec.get("personal_notes"),
        ),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id

def db_patch_record(rid: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not payload:
        return db_get_record_or_404(rid)

    columns = []
    values: List[Any] = []
    for key, val in payload.items():
        columns.append(f"{key} = ?")
        values.append(val)

    values.append(rid)

    conn = db()
    cur = conn.cursor()
    sql = f"UPDATE records SET {', '.join(columns)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    cur.execute(sql, values)
    conn.commit()
    conn.close()
    return db_get_record_or_404(rid)

@app.post("/api/records")
def create_record(body: RecordIn) -> Dict[str, Any]:
    rec = body.dict()
    new_id = db_insert_record(rec)
    return db_get_record_or_404(new_id)

@app.patch("/api/records/{rid}")
def patch_record(rid: int, body: RecordPatch) -> Dict[str, Any]:
    rec = db_get_record_or_404(rid)
    payload: Dict[str, Any] = {}
    for field_name, value in body.dict(exclude_unset=True).items():
        payload[field_name] = value
    updated = db_patch_record(rid, payload)
    return updated

# =============================================================================
# Discogs + HTTP helpers
# =============================================================================

def _discogs_headers() -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if DISCOGS_TOKEN:
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
    for fmt in detail.get("formats") or []:
        name = _nz(fmt.get("name"))
        if name:
            tokens.append(name.lower())
        for d in fmt.get("descriptions") or []:
            d = _nz(d)
            if d:
                tokens.append(d.lower())
    return tokens

def _is_lp_format(detail: Dict[str, Any]) -> bool:
    tokens = _fmt_tokens_from_release_detail(detail)
    if "lp" in tokens or "album" in tokens:
        return True
    if "vinyl" in tokens and "12\"" in tokens:
        return True
    return False

def _country_from_release_detail(detail: Dict[str, Any]) -> Optional[str]:
    c = _nz(detail.get("country"))
    if not c:
        return None
    return c.upper()

def _year_from_release_detail(detail: Dict[str, Any]) -> Optional[int]:
    y = to_int_or_none(_nz(detail.get("year")))
    return y

def _score_candidate(row: sqlite3.Row, detail: Dict[str, Any]) -> int:
    score = 0

    artist = _nz(row["artist"]).lower()
    title = _nz(row["title"]).lower()
    country_pref_val = country_pref(row)
    year_pref = row["year"]

    artists = ", ".join([_nz(a.get("name")) for a in detail.get("artists", []) or []]).lower()
    if artist and artist in artists:
        score += 30

    title_detail = _nz(detail.get("title")).lower()
    if title and title in title_detail:
        score += 30

    if country_pref_val and _country_from_release_detail(detail) == country_pref_val:
        score += 20

    y = _year_from_release_detail(detail)
    if y and year_pref and abs(y - year_pref) <= 1:
        score += 10

    if _is_lp_format(detail):
        score += 10

    return score

def discogs_query_plan_for_row(row: sqlite3.Row) -> List[Dict[str, Any]]:
    artist = _nz(row["artist"])
    title = _nz(row["title"])
    country = country_pref(row)

    base_q = f"{artist} {title}".strip()

    plans: List[Dict[str, Any]] = []

    plans.append(
        {
            "q": base_q,
            "type": "release",
            "format": "LP",
            "per_page": 50,
        }
    )

    if country:
        plans.append(
            {
                "q": base_q,
                "type": "release",
                "format": "LP",
                "country": country,
                "per_page": 50,
            }
        )

    if row["catalog_number"]:
        plans.append(
            {
                "catno": row["catalog_number"],
                "type": "release",
                "per_page": 50,
            }
        )

    if row["barcode"]:
        plans.append(
            {
                "barcode": row["barcode"],
                "type": "release",
                "per_page": 50,
            }
        )

    return plans

def candidate_allowed_search(result_row: Dict[str, Any], required_country: Optional[str]) -> bool:
    fmts = [(_nz(f)).lower() for f in (result_row.get("format") or [])]
    if fmts:
        if not any("lp" in f or "album" in f for f in fmts):
            return False

    if required_country:
        c = _nz(result_row.get("country")).upper()
        if c and c != required_country:
            return False

    return True

def derive_best_release_id_for_record(rid: int) -> Optional[int]:
    row = db_get_record_or_404(rid)
    required_country = country_pref(row)

    best_id: Optional[int] = None
    best_score = -1

    for params in discogs_query_plan_for_row(row):
        js = _http_get(f"{DISCOGS_API}/database/search", params)
        for r in js.get("results") or []:
            release_id = r.get("id")
            if not release_id:
                continue

            try:
                detail = discogs_release_details(int(release_id))
            except HTTPException:
                continue

            if not _is_lp_format(detail):
                continue

            if required_country and _country_from_release_detail(detail) != required_country:
                continue

            score = _score_candidate(row, detail)
            if score > best_score:
                best_score = score
                best_id = int(release_id)

        if best_id is not None and best_score >= 40:
            break

    return best_id

# Discogs search helpers used by the picker UI
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
            break
    return {"results": out}

@app.get("/api/discogs/release/{release_id}")
def api_discogs_release_preview(release_id: int) -> Dict[str, Any]:
    return discogs_release_details(release_id)

# =============================================================================
# API: Discogs cover + tracks  (LP-only + required country)
# =============================================================================

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

    winner = primary or secondary
    if not winner:
        return None, None

    return winner.get("uri"), winner.get("uri150")

@app.post("/api/records/{rid}/discogs/apply")
def api_discogs_apply(rid: int, body: Optional[DiscogsApplyIn] = Body(None)) -> Dict[str, Any]:
    row = db_get_record_or_404(rid)
    if body and body.release_id:
        release_id = int(body.release_id)
    else:
        release_id = derive_best_release_id_for_record(rid)
        if not release_id:
            raise HTTPException(404, detail="No suitable Discogs LP release found")

    detail = discogs_release_details(release_id)
    cover_url_auto, discogs_thumb = pick_best_image(detail)
    if not cover_url_auto and not discogs_thumb:
        raise HTTPException(404, detail="No cover image found for Discogs release")

    payload: Dict[str, Any] = {
        "discogs_id": int(detail.get("id") or release_id),
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

    detail = discogs_release_details(release_id)
    tracks = discogs_fetch_tracklist_for_release(release_id, detail)
    items = [{"side": t["side"], "position": t["position"], "title": t["title"], "duration": t["duration"]} for t in tracks]
    db_replace_tracks(rid, items)
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
        side = "A"
        if pos:
            first = pos[0].upper()
            if first.isalpha():
                side = first
        out.append(
            {
                "side": side,
                "position": pos or None,
                "title": title or "Untitled",
                "duration": duration or None,
            }
        )
    return out

# =============================================================================
# Cover image proxy + embedding storage
# =============================================================================

CLIP_ENABLED = bool(os.environ.get("CLIP_ENABLED", "").strip())
CLIP_MODEL_NAME = os.environ.get("CLIP_MODEL_NAME", "ViT-B/32")

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

    # Device selection: CUDA > MPS (Apple Silicon) > CPU
    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"   # Uses Apple GPU via Metal Performance Shaders (not Neural Engine)
    else:
        device = "cpu"

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

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img_t = preprocess(img).unsqueeze(0).to(device)

    with torch.no_grad():
        emb = model.encode_image(img_t)
        emb = emb / emb.norm(dim=-1, keepdim=True)
        vec = emb[0].cpu().numpy().astype("float32")

    return vec.tolist()

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
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)

@app.get("/api/records/{rid}/cover/proxy")
def cover_proxy(rid: int) -> Response:
    conn = db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail="Record not found")

    url = row["cover_url"] or row["cover_url_auto"] or row["discogs_thumb"]
    if not url:
        conn.close()
        raise HTTPException(404, detail="No cover URL available")

    try:
        import requests
    except Exception as e:
        conn.close()
        raise HTTPException(500, detail=f"'requests' not installed: {e}")

    headers = _discogs_headers()
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        conn.close()
        raise HTTPException(502, detail=f"Error fetching cover: {e}")

    content_type = resp.headers.get("Content-Type", "image/jpeg")
    data = resp.content
    conn.close()
    return Response(content=data, media_type=content_type)

@app.post("/api/records/{rid}/cover/embedding")
def compute_cover_embedding(rid: int) -> Dict[str, Any]:
    if not CLIP_ENABLED:
        raise HTTPException(400, detail="CLIP embedding disabled (set CLIP_ENABLED=1 to enable)")

    conn = db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail="Record not found")

    url = row["cover_url"] or row["cover_url_auto"] or row["discogs_thumb"]
    if not url:
        conn.close()
        raise HTTPException(404, detail="No cover URL for record")

    try:
        import requests
    except Exception as e:
        conn.close()
        raise HTTPException(500, detail=f"'requests' not installed: {e}")

    try:
        resp = requests.get(url, headers=_discogs_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        conn.close()
        raise HTTPException(502, detail=f"Error fetching cover for embedding: {e}")

    emb = compute_image_embedding(resp.content)
    vec_json = json.dumps(emb)

    cur.execute(
        """
        INSERT INTO cover_embeddings (record_id, vec, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(record_id) DO UPDATE SET
          vec = excluded.vec,
          updated_at = excluded.updated_at
        """,
        (rid, vec_json),
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.post("/api/records/cover/search")
def search_by_cover(file: UploadFile = File(...), limit: int = Body(10, embed=True)) -> Dict[str, Any]:
    if not CLIP_ENABLED:
        raise HTTPException(400, detail="CLIP embedding disabled (set CLIP_ENABLED=1 to enable)")

    image_bytes = file.file.read()
    file.file.close()

    query_vec = compute_image_embedding(image_bytes)

    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT e.record_id, e.vec, r.artist, r.title
        FROM cover_embeddings e
        JOIN records r ON r.id = e.record_id
        """
    ).fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        rid = r["record_id"]
        vec = json.loads(r["vec"])
        score = cosine_similarity(query_vec, vec)
        results.append(
            {
                "record_id": rid,
                "artist": r["artist"],
                "title": r["title"],
                "score": score,
            }
        )

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[: max(1, min(limit, 100))]

    conn.close()
    return {"results": results}