# app/services/cover_best_match.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from .discogs_client import discogs_search, discogs_release

# ---------- Utilities & normalization ----------

def country_pref(record: Dict[str, Any]) -> str:
    """
    Country is mandatory. Use record['country'] if present, else 'US'.
    """
    c = (record.get("country") or "").strip()
    return c if c else "US"

def make_base_params(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Base Discogs search params. Enforce type, country, and LP-only filter.
    """
    return {
        "type": "release",
        "country": country_pref(record),
        "format": "LP",           # hard filter to LP in search
    }

def _nz(v: Any) -> str:
    return ("" if v is None else str(v)).strip()

def _fmt_list(item: Dict[str, Any]) -> List[str]:
    """
    Normalize Discogs format tokens to a lowercased list.
    Works with both /database/search (format: [..]) and /releases/{id} (formats: [{...}]).
    """
    fmt = item.get("format")
    if isinstance(fmt, list) and all(not isinstance(x, dict) for x in fmt):
        return [str(x).lower() for x in fmt]

    tokens: List[str] = []
    for f in (item.get("formats") or []):
        name = str(f.get("name") or "").lower()
        if name:
            tokens.append(name)
        for d in (f.get("descriptions") or []):
            tokens.append(str(d).lower())
    return tokens

def candidate_allowed(item: Dict[str, Any], required_country: str) -> bool:
    """
    Belt & suspenders: after search, keep only releases with the right country AND including 'LP' format.
    """
    c = _nz(item.get("country"))
    if c != required_country:
        return False
    tokens = set(_fmt_list(item))
    return "lp" in tokens

def discogs_query_plan(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Most precise → least precise queries; all inherit base(country, LP).
    """
    base = make_base_params(record)
    artist = _nz(record.get("artist"))
    title = _nz(record.get("title"))
    year = record.get("year") if str(record.get("year") or "").isdigit() else None
    label = _nz(record.get("label"))
    catno = _nz(record.get("catalog_number"))
    barcode = _nz(record.get("barcode"))

    q_struct = f"{artist} - {title}".strip(" -")
    plan: List[Dict[str, Any]] = []

    # Barcode
    if barcode:
        p = dict(base)
        p["barcode"] = barcode
        if year: p["year"] = year
        plan.append(p)

    # Catalog no (optionally narrow with label/artist/year)
    if catno:
        p = dict(base)
        p["catno"] = catno
        if label:  p["label"]  = label
        if artist: p["artist"] = artist
        if year:   p["year"]   = year
        plan.append(p)

    # Structured text
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

    # Deduplicate preserving order
    seen = set()
    dedup: List[Dict[str, Any]] = []
    for d in plan:
        key = tuple(sorted(d.items()))
        if key not in seen:
            seen.add(key)
            dedup.append(d)
    return dedup

# ---------- Scoring (simple but effective) ----------

def score_candidate(item: Dict[str, Any], record: Dict[str, Any]) -> int:
    """
    Heuristic score to pick the best among allowed candidates.
    """
    score = 0
    artist = _nz(record.get("artist")).lower()
    title  = _nz(record.get("title")).lower()
    year   = str(record.get("year") or "").strip()

    cand_artist = _nz(item.get("artist")).lower()
    cand_title  = _nz(item.get("title")).lower()
    cand_year   = _nz(item.get("year"))

    # Exact/near matches
    if cand_artist and artist and cand_artist == artist:
        score += 25
    elif cand_artist and artist and artist in cand_artist:
        score += 12

    if cand_title and title and cand_title == title:
        score += 25
    elif cand_title and title and title in cand_title:
        score += 12

    if cand_year and year and cand_year == year:
        score += 10

    # Prefer items with images
    imgs = item.get("images") or []
    if imgs:
        score += 8

    # Prefer items that look like Album vs single
    tokens = set(_fmt_list(item))
    if "album" in tokens:
        score += 4

    return score

def pick_best_image(rel: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    imgs = rel.get("images") or []
    if not imgs:
        return None, None
    primary = next((i for i in imgs if i.get("type") == "primary" or i.get("front")), None)
    best = primary or imgs[0]
    return best.get("uri"), best.get("uri150") or best.get("resource_url")

# ---------- Main flow ----------

async def fetch_best_cover_for_record(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Returns a full release JSON for the best match (LP + required country), or None.
    """
    required_country = country_pref(record)

    # Shortcut: explicit release id
    rel_id = record.get("discogs_id") or record.get("discogs_release_id")
    if rel_id:
        try:
            data = await discogs_release(int(rel_id))
            if candidate_allowed(data, required_country):
                return data
        except Exception:
            pass  # fall through to search

    # Search plan
    for params in discogs_query_plan(record):
        try:
            data = await discogs_search(params)
        except Exception:
            continue

        results = (data or {}).get("results") or []
        allowed = [it for it in results if candidate_allowed(it, required_country)]
        if not allowed:
            continue

        # If we can, resolve a few candidates to full releases to let scoring use images/formats better
        resolved: List[Dict[str, Any]] = []
        for it in allowed[:8]:  # cap to keep latency reasonable
            rid = it.get("id")
            try:
                rel = await discogs_release(int(rid))
                if candidate_allowed(rel, required_country):
                    resolved.append(rel)
            except Exception:
                # keep the search item as fallback
                resolved.append(it)

        # Score & choose best
        best = max(resolved, key=lambda x: score_candidate(x, record))
        return best

    return None