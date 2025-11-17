cat > app/discogs.py <<'PY'
# app/discogs.py
import os
import requests

BASE = "https://api.discogs.com/database/search"
TOKEN = os.getenv("DISCOGS_TOKEN", "")
UA    = os.getenv("DISCOGS_UA", "VinylApp/0.1 (+http://localhost)")

def _headers():
    if not TOKEN:
        raise RuntimeError("DISCOGS_TOKEN env var is not set in the container")
    return {
        "Authorization": f"Discogs token={TOKEN}",
        "User-Agent": UA
    }

def search(artist: str | None = None, title: str | None = None, barcode: str | None = None):
    params = {"type": "release"}
    if artist:  params["artist"] = artist
    if title:   params["release_title"] = title
    if barcode: params["barcode"] = barcode

    r = requests.get(BASE, params=params, headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()
PY
