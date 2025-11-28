from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import csv
import io
import json
import math

from fastapi import Body, FastAPI, HTTPException, Query, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path

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
# App
# =============================================================================

app = FastAPI(title="Vinyl API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/")
def root() -> Dict[str, Any]:
    return {"status": "ok", "ts": int(time.time())}


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
          location TEXT,
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
          sort_mode TEXT,
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
    base = os.path.dirname(DB_PATH) or "."
    os.makedirs(base, exist_ok=True)
    init_db()


# =============================================================================
# Basic DB utilities
# =============================================================================

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
    location: Optional[str] = None
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
    sort_mode: Optional[str] = None


class RecordPatch(BaseModel):
    artist: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    label: Optional[str] = None
    format: Optional[str] = None
    country: Optional[str] = None
    location: Optional[str] = None
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
    sort_mode: Optional[str] = None


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


def _nz(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()


# =============================================================================
# Meta
# =============================================================================

@app.get("/api/meta/schema")
def meta_schema() -> Dict[str, Any]:
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


@app.get("/api/meta/records/schema")
def meta_records_schema() -> Dict[str, Any]:
    return meta_schema()


# =============================================================================
# Records listing + CRUD
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
            "(artist LIKE ? OR title LIKE ? OR label LIKE ? OR country LIKE ? OR location LIKE ? OR catalog_number LIKE ? OR barcode LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    allowed_sort = {"artist", "title", "year", "label", "country", "location", "created_at", "updated_at"}
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
        year_str = str(released).strip()[:4]
    try:
        return int(year_str)
    except Exception:
        return None


def derive_year_from_discogs_release(release_id: Optional[int]) -> Optional[int]:
    if not release_id:
        return None
    try:
        detail = discogs_release_details(int(release_id))
    except HTTPException:
        return None
    except Exception:
        return None
    return derive_year_from_release_detail(detail)


@app.post("/api/records")
def create_record(payload: RecordIn = Body(...)) -> Dict[str, Any]:
    # Default country + format for new manual records
    if not (payload.country or "").strip():
        payload.country = "US"
    if not (payload.format or "").strip():
        payload.format = "LP"

    data = payload.dict()
    # If no year but we have a Discogs release/record id, try to derive a year
    if not data.get("year"):
        release_id = data.get("discogs_release_id") or data.get("discogs_id")
        year = derive_year_from_discogs_release(release_id)
        if year is not None:
            data["year"] = year

    return db_insert_record(data)


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
# CSV import/export
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
        "location",
        "sort_mode",
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


@app.get("/api/records-export")
def export_records() -> Response:
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT * FROM records ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE, id"
    ).fetchall()

    headers = [
        "id",
        "artist",
        "title",
        "year",
        "label",
        "format",
        "country",
        "location",
        "sort_mode",
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
        "created_at",
        "updated_at",
    ]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for r in rows:
        row = [r["id"]]
        for col in headers[1:]:
            row.append(r[col])
        writer.writerow(row)

    csv_bytes = buf.getvalue().encode("utf-8")
    conn.close()
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="vinyl_records_export.csv"'},
    )


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Import CSV rows into the records table.

    Defaults:
      - country -> "US" if missing/blank
      - format  -> "LP" if missing/blank
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
        return str(s).strip()

    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except Exception:
        raise HTTPException(400, detail="Could not decode CSV as UTF-8")

    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(400, detail="CSV file is empty")

    header_map: Dict[str, str] = {}
    for col in header:
        key = (col or "").strip().lower()
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
            val = row[idx] if idx < len(row) else ""

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
                rec["country"] = nz(val)
            elif key == "location":
                rec["location"] = nz(val)
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
            elif key == "sort_mode":
                rec["sort_mode"] = nz(val)

        artist = nz(rec.get("artist"))
        title = nz(rec.get("title"))
        if not artist or not title:
            continue

        if "country" not in rec or not nz(rec["country"]):
            rec["country"] = "US"
        if "format" not in rec or not nz(rec["format"]):
            rec["format"] = "LP"

        # Derive year from Discogs if missing
        if not rec.get("year"):
            release_id = rec.get("discogs_release_id") or rec.get("discogs_id")
            if release_id is not None:
                yr = derive_year_from_discogs_release(release_id)
                if yr is not None:
                    rec["year"] = yr

        db_insert_record(rec)
        rows_imported += 1

    return {"imported": rows_imported}


# =============================================================================
# Tracks APIs
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
    bump_record_updated(rid)
    return {"ok": True, "count": len(items)}


# =============================================================================
# Discogs HTTP helpers
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


def candidate_allowed_search(item: Dict[str, Any], required_country: Optional[str]) -> bool:
    fmt = " ".join((item.get("format") or [])).lower()
    if "lp" not in fmt and "vinyl" not in fmt:
        return False
    if required_country:
        c = _nz(item.get("country")).upper()
        if c and c != required_country.upper():
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

    winner = primary or secondary
    if not winner:
        return None, None

    return winner.get("uri"), winner.get("uri150")


# -----------------------------------------------------------------------------
# Extra debug endpoint: /api/discogs/search (used in your curl test)
# -----------------------------------------------------------------------------
@app.get("/api/discogs/search")
def api_discogs_search(
    artist: Optional[str] = Query(None),
    release_title: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    type: str = Query("release"),
    per_page: int = Query(50, ge=1, le=100),
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"type": type, "per_page": per_page}

    if artist:
        params["artist"] = artist
    if release_title:
        params["release_title"] = release_title
    if q:
        params["q"] = q

    js = _http_get(f"{DISCOGS_API}/database/search", params)
    return js


# =============================================================================
# Discogs search + cover/track logic (used by the UI)
# =============================================================================

def discogs_query_plan_for_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    artist = _nz(row.get("artist"))
    title = _nz(row.get("title"))
    year = _nz(row.get("year"))
    cat = _nz(row.get("catalog_number"))
    bc = _nz(row.get("barcode"))

    base_q = f"{artist} {title}".strip()
    plans: List[Dict[str, Any]] = []

    if base_q:
        plans.append(
            {
                "q": base_q,
                "type": "release",
                "format": "LP",
                "per_page": 50,
            }
        )
        if year:
            plans.append(
                {
                    "q": f"{base_q} {year}",
                    "type": "release",
                    "format": "LP",
                    "per_page": 50,
                }
            )

    if cat:
        plans.append(
            {
                "catno": cat,
                "type": "release",
                "per_page": 50,
            }
        )

    if bc:
        plans.append(
            {
                "barcode": bc,
                "type": "release",
                "per_page": 50,
            }
        )

    return plans


def discogs_fetch_and_score_candidates(row: Dict[str, Any]) -> List[Tuple[int, int]]:
    artist = _nz(row.get("artist")).lower()
    title = _nz(row.get("title")).lower()
    country = country_pref(row)
    year = row.get("year")

    def score_candidate(detail: Dict[str, Any]) -> int:
        s = 0
        artists_detail = ", ".join([_nz(a.get("name")) for a in (detail.get("artists") or [])]).lower()
        if artist and artist in artists_detail:
            s += 30
        title_detail = _nz(detail.get("title")).lower()
        if title and title in title_detail:
            s += 30

        if country and _nz(detail.get("country")).upper() == country.upper():
            s += 10

        rel_year = detail.get("year")
        try:
            y_rec = int(year) if year is not None else None
        except Exception:
            y_rec = None
        try:
            y_rel = int(rel_year) if rel_year is not None else None
        except Exception:
            y_rel = None
        if y_rec is not None and y_rel is not None and abs(y_rec - y_rel) <= 1:
            s += 10
        return s

    best: List[Tuple[int, int]] = []

    for params in discogs_query_plan_for_row(row):
        js = _http_get(f"{DISCOGS_API}/database/search", params)
        for item in js.get("results", []) or []:
            if not candidate_allowed_search(item, country):
                continue
            rel_id = item.get("id")
            if not rel_id:
                continue
            try:
                detail = discogs_release_details(int(rel_id))
            except HTTPException:
                continue
            except Exception:
                continue

            if not candidate_allowed_release(detail, country):
                continue

            s = score_candidate(detail)
            best.append((int(rel_id), s))

        if best:
            break

    best.sort(key=lambda x: x[1], reverse=True)
    return best


def derive_best_release_id_for_record(rid: int) -> Optional[int]:
    row = db_get_record_or_404(rid)
    candidates = discogs_fetch_and_score_candidates(row)
    if not candidates:
        return None
    return candidates[0][0]


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
            out.append(
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "year": r.get("year"),
                    "country": r.get("country"),
                    "label": r.get("label"),
                    "format": r.get("format"),
                    "thumb": r.get("thumb"),
                }
            )
        if out:
            break
    return {"results": out}


@app.get("/api/discogs/release/{release_id}")
def api_discogs_release_preview(release_id: int) -> Dict[str, Any]:
    return discogs_release_details(release_id)


@app.post("/api/records/{rid}/cover/fetch")
def api_cover_fetch(rid: int, body: Optional[DiscogsApplyIn] = Body(None)) -> Dict[str, Any]:
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

    # If the record doesn't have a year yet, derive it from this release
    if not row.get("year"):
        yr = derive_year_from_release_detail(detail)
        if yr is not None:
            db_patch_record(rid, {"year": yr})

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

    # If the record doesn't have a year yet, derive it from this release
    if not row.get("year"):
        yr = derive_year_from_release_detail(detail)
        if yr is not None:
            db_patch_record(rid, {"year": yr})

    tracks = discogs_fetch_tracklist_for_release(release_id, detail)
    items = [
        {"side": t["side"], "position": t["position"], "title": t["title"], "duration": t["duration"]}
        for t in tracks
    ]
    db_replace_tracks(rid, items)
    bump_record_updated(rid)
    return {"ok": True, "count": len(tracks)}


def discogs_fetch_tracklist_for_release(release_id: int, detail: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rel = detail or discogs_release_details(release_id)
    out: List[Dict[str, Any]] = []
    for t in rel.get("tracklist", []) or []:
        pos = (t.get("position") or "").strip()
        title = (t.get("title") or "").strip()
        duration = (t.get("duration") or "").strip()
        side = "A"
        if pos and pos[0].isalpha():
            side = pos[0].upper()
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

    if torch.cuda.is_available():
        device = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
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
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


# =============================================================================
# Cover proxy + cover-match + embeddings rebuild
# =============================================================================

def get_cover_bytes_for_record(row: sqlite3.Row) -> Optional[bytes]:
    """
    Try local cover_local (file path under DB folder) then URLs.
    """
    # Local file path
    path = (row["cover_local"] or "").strip()
    if path:
        try:
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
        import requests
    except Exception as e:
        raise HTTPException(500, detail=f"'requests' not installed: {e}")

    try:
        resp = requests.get(url, headers=_discogs_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return None


@app.get("/api/records/{rid}/cover/proxy")
def cover_proxy(rid: int) -> Response:
    conn = db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM records WHERE id = ?", (rid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail="Record not found")

    data = get_cover_bytes_for_record(row)
    conn.close()
    if not data:
        raise HTTPException(404, detail="No cover data available")

    return Response(content=data, media_type="image/jpeg")


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
                for item in raw:
                    if isinstance(item, list):
                        vecs.append([float(x) for x in item])
            out.append((int(r["record_id"]), vecs))
        except Exception:
            continue
    return out


@app.post("/api/cover-match")
async def api_cover_match(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Accept an uploaded cover photo, compute a CLIP embedding, and find the closest
    matching record in the existing cover_embeddings table.

    Adds a 'confident' flag when the best match is clearly ahead of the rest:
      - best.score >= 0.80
      - (best.score - second_best.score) >= 0.10
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
            # each record may have multiple vectors; take the best similarity
            best_for_record = max(cosine_similarity(query_vec, v) for v in vecs)
            scored.append((rid, best_for_record))

        if not scored:
            raise HTTPException(404, detail="No valid embeddings to compare against.")

        scored.sort(key=lambda x: x[1], reverse=True)
        best_id, best_score = scored[0]
        second_best_score = scored[1][1] if len(scored) > 1 else 0.0
        gap = best_score - second_best_score

        # Heuristic confidence rule
        confident = (best_score >= 0.80) and (gap >= 0.10)

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

        return {
            "best": {
                "id": int(best_id),
                "score": float(best_score),
                "gap_to_second": float(gap),
            },
            "candidates": candidates_out,
            "confident": confident,
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
        data = get_cover_bytes_for_record(row)
        if not data:
            skipped_no_image += 1
            continue

        try:
            vec = compute_image_embedding(data)

            vec_json = json.dumps([vec])  # store as list-of-vectors for future augmentation
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


@app.post("/api/cover-embeddings/build-missing")
def api_build_missing_cover_embeddings(limit: Optional[int] = Query(None)) -> Dict[str, Any]:
    """
    Build cover embeddings **only** for records that don't already have an entry
    in the cover_embeddings table.
    """
    conn = db()
    cur = conn.cursor()

    # Only select records that currently have NO embedding row
    rows = cur.execute(
        """
        SELECT r.*
        FROM records AS r
        LEFT JOIN cover_embeddings AS ce
          ON ce.record_id = r.id
        WHERE ce.record_id IS NULL
        ORDER BY r.id
        """
    ).fetchall()

    processed = 0
    skipped_no_image = 0
    errors = 0

    for row in rows:
        # respect optional ?limit= query param, same as rebuild endpoint
        if limit is not None and processed >= limit:
            break

        rid = int(row["id"])
        data = get_cover_bytes_for_record(row)
        if not data:
            skipped_no_image += 1
            continue

        try:
            vec = compute_image_embedding(data)

            vec_json = json.dumps([vec])  # store as list-of-vectors for future augmentation
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
            processed += 1
        except HTTPException:
            # preserve the original behavior and let FastAPI handle this
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