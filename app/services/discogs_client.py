# app/services/discogs_client.py
from __future__ import annotations
import os
from typing import Any, Dict, Optional
import httpx

DISCOGS_API_BASE = "https://api.discogs.com"

def _token() -> str:
    t = os.getenv("DISCOGS_TOKEN", "").strip()
    if not t:
        raise RuntimeError("DISCOGS_TOKEN is not configured in the environment")
    return t

async def discogs_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calls /database/search with sane defaults. Returns the JSON response.
    """
    query = {
        "type": "release",
        "per_page": params.pop("per_page", 50),
        "page": params.pop("page", 1),
        **params,
        "token": _token(),
    }
    async with httpx.AsyncClient(timeout=20) as cx:
        r = await cx.get(f"{DISCOGS_API_BASE}/database/search", params=query)
        r.raise_for_status()
        return r.json()

async def discogs_release(release_id: int) -> Dict[str, Any]:
    """
    Calls /releases/{id}. Returns the JSON response.
    """
    async with httpx.AsyncClient(timeout=20) as cx:
        r = await cx.get(f"{DISCOGS_API_BASE}/releases/{release_id}", params={"token": _token()})
        r.raise_for_status()
        return r.json()