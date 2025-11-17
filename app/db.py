# app/db.py
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional

# Expected env: DATABASE_URL=sqlite:////data/records.db
RAW_URL = os.getenv("DATABASE_URL", "sqlite:////data/records.db")
DB_PATH = RAW_URL.replace("sqlite:///", "", 1)

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def connect():
    cx = sqlite3.connect(DB_PATH, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    return cx

@contextmanager
def conn():
    cx = connect()
    try:
        yield cx
        cx.commit()
    finally:
        cx.close()

def init():
    with conn() as cx:
        cx.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            artist          TEXT,
            title           TEXT,
            year            INTEGER,
            label           TEXT,
            format          TEXT,
            catalog_number  TEXT,
            barcode         TEXT,
            cover_url       TEXT,
            cover_local     TEXT,
            updated_at      INTEGER DEFAULT (strftime('%s','now'))
        )
        """)
        # Add missing columns for Discogs integration
        _ensure_column(cx, "records", "discogs_id", "INTEGER")
        _ensure_column(cx, "records", "discogs_master_id", "INTEGER")
        _ensure_column(cx, "records", "discogs_thumb", "TEXT")

        # Speed up lookups by artist/title; ignore if already exists
        try:
            cx.execute("CREATE INDEX IF NOT EXISTS idx_records_artist_title ON records(lower(artist), lower(title))")
        except Exception:
            pass

def _ensure_column(cx: sqlite3.Connection, table: str, col: str, sqltype: str):
    cur = cx.execute(f"PRAGMA table_info({table})")
    have = {r["name"] for r in cur.fetchall()}
    if col not in have:
        cx.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sqltype}")

# ---------- CRUD ----------

def list_records(q: Optional[str] = None):
    with conn() as cx:
        if q:
            ql = f"%{q.lower()}%"
            cur = cx.execute("""
                SELECT * FROM records
                WHERE lower(artist) LIKE ? OR lower(title) LIKE ?
                ORDER BY artist, year, title
            """, (ql, ql))
        else:
            cur = cx.execute("SELECT * FROM records ORDER BY artist, year, title")
        return [dict(row) for row in cur.fetchall()]

def get_record(rid: int) -> Optional[Dict[str, Any]]:
    with conn() as cx:
        cur = cx.execute("SELECT * FROM records WHERE id = ?", (rid,))
        row = cur.fetchone()
        return dict(row) if row else None

def insert_records(rows: Iterable[Dict[str, Any]]):
    rows = list(rows)
    if not rows:
        return 0
    with conn() as cx:
        for r in rows:
            cx.execute("""
                INSERT INTO records
                (artist,title,year,label,format,catalog_number,barcode,cover_url,cover_local,discogs_id,discogs_master_id,discogs_thumb)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r.get("artist"), r.get("title"), r.get("year"),
                r.get("label"), r.get("format"), r.get("catalog_number"),
                r.get("barcode"), r.get("cover_url"), r.get("cover_local"),
                r.get("discogs_id"), r.get("discogs_master_id"), r.get("discogs_thumb"),
            ))
        return len(rows)

def replace_all(rows: Iterable[Dict[str, Any]]):
    with conn() as cx:
        cx.execute("DELETE FROM records")
    return insert_records(rows)

def update_record(rid: int, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not patch:
        return get_record(rid)
    keys = sorted(patch.keys())
    sets = ", ".join(f"{k} = ?" for k in keys)
    vals = [patch[k] for k in keys]
    with conn() as cx:
        cx.execute(f"UPDATE records SET {sets}, updated_at = strftime('%s','now') WHERE id = ?", (*vals, rid))
        cur = cx.execute("SELECT * FROM records WHERE id = ?", (rid,))
        row = cur.fetchone()
        return dict(row) if row else None

def delete_record(rid: int) -> bool:
    with conn() as cx:
        cur = cx.execute("DELETE FROM records WHERE id = ?", (rid,))
        return cur.rowcount > 0
