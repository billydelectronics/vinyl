from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import csv, io
import json
import math
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
    allow_origins=["*"],   # tighten for prod if needed
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
    as_dict = dict(row)
    conn.close()
    return as_dict


# =============================================================================
# Models
# =============================================================================

class TrackIn(BaseModel):
    side: Optional[str] = None
    position: Optional[str] = None
    title: str
    duration: Optional[str] = None


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


# =============================================================================
# Records listing / CRUD
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
    conn = db()
    cur = conn.cursor()
    fields = [
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
    values = [getattr(payload, f) for f in fields]
    placeholders = ",".join("?" for _ in fields)
    cur.execute(
        f"""
        INSERT INTO records ({",".join(fields)})
        VALUES ({placeholders})
        """,
        values,
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return db_get_record_or_404(rid)


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
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM records WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/records/bulk/delete")
def bulk_delete_records(ids: List[int] = Body(...)) -> Dict[str, Any]:
    if not ids:
        return {"deleted": 0}
    conn = db()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cur.execute(f"DELETE FROM records WHERE id IN ({placeholders})", ids)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
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

    def to_int(v: Any) -> Optional[int]:
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

    def nz(s: Any) -> Optional[str]:
        if s is None:
            return None
        if isinstance(s, str):
            s2 = s.strip()
            return s2 if s2 != "" else None
        return s

    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    buf = io.StringIO(text)
    reader = csv.DictReader(buf)
    rows = list(reader)

    required_cols = {"artist", "title"}
    missing = [c for c in required_cols if c not in (reader.fieldnames or [])]
    if missing:
        raise HTTPException(400, detail=f"Missing required column(s): {', '.join(missing)}")

    conn = db()
    cur = conn.cursor()

    inserted = 0
    for row in rows:
        artist = nz(row.get("artist"))
        title = nz(row.get("title"))
        if not artist or not title:
            continue

        year = to_int(row.get("year"))
        discogs_id = to_int(row.get("discogs_id"))
        discogs_release_id = to_int(row.get("discogs_release_id"))

        label = nz(row.get("label"))
        fmt = nz(row.get("format"))
        country = nz(row.get("country"))
        catalog_number = nz(row.get("catalog_number"))
        barcode = nz(row.get("barcode"))
        discogs_thumb = nz(row.get("discogs_thumb"))
        cover_url = nz(row.get("cover_url"))
        cover_local = nz(row.get("cover_local"))
        cover_url_auto = nz(row.get("cover_url_auto"))
        album_notes = nz(row.get("album_notes"))
        personal_notes = nz(row.get("personal_notes"))

        cur.execute(
            """
            INSERT INTO records (
              artist, title, year, label, format, country,
              catalog_number, barcode,
              discogs_id, discogs_release_id,
              discogs_thumb, cover_url, cover_local, cover_url_auto,
              album_notes, personal_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artist,
                title,
                year,
                label,
                fmt,
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
    return {"inserted": inserted}


# =============================================================================
# Tracks
# =============================================================================

@app.get("/api/records/{rid}/tracks")
def get_tracks(rid: int) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    row = fetch_record(conn, rid)
    tracks = cur.execute(
        "SELECT * FROM tracks WHERE record_id = ? ORDER BY id",
        (row["id"],),
    ).fetchall()
    conn.close()
    return {"record": dict(row), "tracks": [dict(t) for t in tracks]}


@app.post("/api/records/{rid}/tracks/replace")
def replace_tracks(rid: int, tracks: List[TrackIn] = Body(...)) -> Dict[str, Any]:
    conn = db()
    cur = conn.cursor()
    row = fetch_record(conn, rid)
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (row["id"],))
    for t in tracks:
        cur.execute(
            """
            INSERT INTO tracks (record_id, side, position, title, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["id"], t.side, t.position, t.title, t.duration),
        )
    conn.commit()
    conn.close()
    return {"ok": True}


# =============================================================================
# Discogs integration
# =============================================================================

def discogs_headers() -> Dict[str, str]:
    h = {"User-Agent": USER_AGENT}
    if DISCOGS_TOKEN:
        h["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"
    return h


def _http_get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        import requests  # type: ignore
    except Exception as e:
        raise HTTPException(500, detail=f"'requests' not installed: {e}")

    p = dict(params or {})
    if DISCOGS_TOKEN and "token" not in p:
        p["token"] = DISCOGS_TOKEN

    try:
        resp = requests.get(url, headers=discogs_headers(), params=p, timeout=REQUEST_TIMEOUT)
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


def _fmt_tokens_from_search_item(item: Dict[str, Any]) -> List[str]:
    fmt = item.get("format")
    if isinstance(fmt, list):
        return [str(x).lower() for x in fmt]
    return []


def _fmt_tokens_from_release_detail(detail: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    for f in (detail.get("formats") or []):
        name = _nz(f.get("name")).lower()
        desc = [str(x).lower() for x in (f.get("descriptions") or [])]
        tokens.extend([name, *desc])
    return tokens


def make_search_base(row: Dict[str, Any]) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "type": "release",
        "format": "LP",
        "per_page": 50,
        "page": 1,
    }
    country = _nz(row.get("country"))
    if country:
        base["country"] = country
    return base


def candidate_allowed_release(detail: Dict[str, Any], required_country: Optional[str]) -> bool:
    tokens = set(_fmt_tokens_from_release_detail(detail))
    if "lp" not in tokens:
        return False
    if required_country:
        if _nz(detail.get("country")).upper() != required_country.upper():
            return False
    return True


def candidate_allowed_search(item: Dict[str, Any], required_country: Optional[str]) -> bool:
    if required_country and _nz(item.get("country")).upper() != required_country.upper():
        return False
    tokens = set(_fmt_tokens_from_search_item(item))
    return "lp" in tokens


def discogs_query_plan_for_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Construct search params from most precise -> least precise, all inheriting base(country, LP).
    """
    base = make_search_base(row)
    artist = _nz(row.get("artist"))
    title = _nz(row.get("title"))
    year_str = _nz(row.get("year"))
    year = int(year_str) if year_str.isdigit() else None
    label = _nz(row.get("label"))
    catno = _nz(row.get("catalog_number"))
    barcode = _nz(row.get("barcode"))

    plan: List[Dict[str, Any]] = []

    # Barcode
    if barcode:
        p = dict(base)
        p["barcode"] = barcode
        if artist:
            p["artist"] = artist
        if title:
            p["release_title"] = title
        if year:
            p["year"] = year
        plan.append(p)

    # Catalog number (+ narrowing fields)
    if catno:
        p = dict(base)
        p["catno"] = catno
        if label:
            p["label"] = label
        if artist:
            p["artist"] = artist
        if title:
            p["release_title"] = title
        if year:
            p["year"] = year
        plan.append(p)

    # Structured artist/title (+ year)
    if artist or title:
        p = dict(base)
        if artist:
            p["artist"] = artist
        if title:
            p["release_title"] = title
        if year:
            p["year"] = year
        plan.append(p)

    # Loose q fallback
    if artist or title:
        p = dict(base)
        p["q"] = " ".join([artist, title]).strip()
        if year:
            p["year"] = year
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
    Simple heuristic scoring on search items.
    """
    score = 0
    artist = _nz(row.get("artist")).lower()
    title = _nz(row.get("title")).lower()
    year = _nz(row.get("year"))

    cand_artist = _nz(item.get("artist")).lower()
    cand_title = _nz(item.get("title")).lower()
    cand_year = _nz(item.get("year"))

    if cand_artist and artist:
        score += 25 if cand_artist == artist else (12 if artist in cand_artist else 0)
    if cand_title and title:
        score += 25 if cand_title == title else (12 if title in cand_title else 0)
    if cand_year and year and cand_year == year:
        score += 8

    # Exact catno match gets a big boost
    row_cat = _nz(row.get("catalog_number")).lower()
    cand_cat = _nz(item.get("catno")).lower()
    if row_cat and cand_cat and row_cat == cand_cat:
        score += 40

    return score


def country_pref(row: Dict[str, Any]) -> Optional[str]:
    c = _nz(row.get("country")).upper()
    return c or None


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


@app.get("/api/records/{rid}/discogs/search")
def api_discogs_search_for_record(
    rid: int,
    per_page: int = Query(20, ge=1, le=50),
    page: int = Query(1, ge=1),
) -> Dict[str, Any]:
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
                    "label": ", ".join(r.get("label") or []),
                    "format": ", ".join(r.get("format") or []),
                    "thumb": r.get("thumb"),
                    "score": score_candidate_search_item(r, row),
                }
            )

    out.sort(key=lambda x: x["score"], reverse=True)
    return {"results": out}


@app.get("/api/discogs/release/{release_id}")
def api_discogs_release_preview(release_id: int) -> Dict[str, Any]:
    return discogs_release_details(release_id)


@app.post("/api/records/{rid}/cover/fetch")
def fetch_cover_for_record(rid: int, release_id: int = Body(..., embed=True)) -> Dict[str, Any]:
    detail = discogs_release_details(release_id)

    row = db_get_record_or_404(rid)
    if not candidate_allowed_release(detail, country_pref(row)):
        raise HTTPException(400, detail="Chosen release does not satisfy LP + country constraint")

    cover_url_auto, discogs_thumb = pick_best_image(detail)
    if not cover_url_auto and not discogs_thumb:
        raise HTTPException(404, detail="Matching release has no images")

    payload: Dict[str, Any] = {
        "discogs_release_id": int(detail.get("id") or release_id),
        "cover_url_auto": cover_url_auto,
    }
    if discogs_thumb:
        payload["discogs_thumb"] = discogs_thumb

    conn = db()
    cur = conn.cursor()
    cols = []
    params = []
    for k, v in payload.items():
        cols.append(f"{k} = ?")
        params.append(v)
    cols.append("updated_at = CURRENT_TIMESTAMP")
    sql = f"UPDATE records SET {', '.join(cols)} WHERE id = ?"
    params.append(rid)
    cur.execute(sql, params)
    conn.commit()
    conn.close()

    return db_get_record_or_404(rid)


@app.post("/api/records/{rid}/tracks/save")
def save_tracks_for_record(rid: int, release_id: int = Body(..., embed=True)) -> Dict[str, Any]:
    detail = discogs_release_details(release_id)
    tracks = discogs_fetch_tracklist_for_release(release_id, detail)

    conn = db()
    cur = conn.cursor()
    row = fetch_record(conn, rid)
    cur.execute("DELETE FROM tracks WHERE record_id = ?", (row["id"],))
    for t in tracks:
        cur.execute(
            """
            INSERT INTO tracks (record_id, side, position, title, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["id"], t["side"], t["position"], t["title"], t["duration"]),
        )
    conn.commit()
    conn.close()
    return {"ok": True, "tracks": tracks}


# =============================================================================
# Cover image embeddings & matching (CLIP-based)
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


def save_cover_embedding(conn: sqlite3.Connection, record_id: int, vec: List[float]) -> None:
    """
    Persist a cover embedding vector for a record into the cover_embeddings table.
    """
    conn.execute(
        "INSERT OR REPLACE INTO cover_embeddings(record_id, vec, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (record_id, json.dumps(vec)),
    )


def get_all_cover_embeddings(conn: sqlite3.Connection) -> List[Tuple[int, List[float]]]:
    """
    Return all stored cover embeddings as (record_id, vector) pairs.
    """
    rows = conn.execute("SELECT record_id, vec FROM cover_embeddings").fetchall()
    out: List[Tuple[int, List[float]]] = []
    for r in rows:
        try:
            vec = json.loads(r["vec"])
            if isinstance(vec, list):
                out.append((int(r["record_id"]), [float(x) for x in vec]))
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
            pass  # fall through to remote

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

    Uses both an absolute score threshold and a gap between best and second-best
    to decide whether to auto-match or just return candidates.
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
        for rid, vec in candidates:
            score = cosine_similarity(query_vec, vec)
            scored.append((rid, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        best_id, best_score = scored[0]
        second_best_score = scored[1][1] if len(scored) > 1 else 0.0
        gap = best_score - second_best_score

        # Look up metadata for top-k candidates
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

        # Thresholds for auto-match; tune via env if desired
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

    Optional query param:
      - limit: max number of records to process in this call
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

            vec = compute_image_embedding(img_bytes)
            save_cover_embedding(conn, rid, vec)
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


# =============================================================================
# Tracklist extraction (reused)
# =============================================================================

def discogs_fetch_tracklist_for_release(
    release_id: int, detail: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
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
        if pos and pos[0].isalpha():
            side = pos[0].upper()
        out.append({"position": pos, "title": title, "duration": duration, "side": side})
    return out