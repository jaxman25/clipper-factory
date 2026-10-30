"""Free Pixabay B-roll for clips where no face can be tracked."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

try:
    from backend import common, paths
except ImportError:  # pragma: no cover
    import common  # type: ignore
    import paths  # type: ignore

PIXABAY_SEARCH = "https://pixabay.com/api/videos/"
DEFAULT_QUERY = os.getenv("PIXABAY_QUERY", "african village night")

# "medium" is the rendition Pixabay guarantees for every video; small/large are
# fallbacks. The video endpoint has no orientation filter, so portrait hits are
# preferred client-side - landscape hits still work because the renderer crops.
RENDITIONS = ("medium", "small", "large")


def _stream(hit: dict) -> tuple[str, int] | None:
    """Best downloadable rendition for a hit: (url, width)."""
    renditions = hit.get("videos") or {}
    for name in RENDITIONS:
        stream = renditions.get(name) or {}
        url = str(stream.get("url") or "").strip()
        width = int(stream.get("width") or 0)
        if not url or width < 480 or width > 2200:
            continue
        return url, width
    return None


def _is_portrait(hit: dict) -> bool:
    renditions = hit.get("videos") or {}
    for name in RENDITIONS:
        stream = renditions.get(name) or {}
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if width and height:
            return height > width
    return False


def fetch(query: str = DEFAULT_QUERY, dest_dir: Path | None = None) -> Path | None:
    """Download a portrait stock clip and cache it. Returns None without a key."""
    api_key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not api_key:
        common.info("PIXABAY_API_KEY missing - using gradient fallback")
        return None

    dest_dir = dest_dir or paths.BROLL_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    cached = sorted(dest_dir.glob(f"{cache_key}-*.mp4"))
    if cached:
        return cached[0]

    try:
        import requests
    except ImportError:
        common.warn("requests not installed - skipping Pixabay B-roll")
        return None

    try:
        response = requests.get(
            PIXABAY_SEARCH,
            params={
                "key": api_key,
                "q": query,
                "video_type": "film",
                "min_height": 1080,
                "safesearch": "true",
                "order": "popular",
                "per_page": 20,
            },
            timeout=25,
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])
    except Exception as exc:  # network/API failure must never abort a render
        common.warn(f"Pixabay search failed: {exc}")
        return None

    # Portrait first; anything else is still usable as a cropped fallback.
    hits.sort(key=lambda hit: 0 if _is_portrait(hit) else 1)

    for index, hit in enumerate(hits):
        picked = _stream(hit)
        if not picked:
            continue
        link = picked[0]
        target = dest_dir / f"{cache_key}-{index}.mp4"
        try:
            with requests.get(link, stream=True, timeout=60) as dl:
                dl.raise_for_status()
                with open(target, "wb") as fh:
                    for chunk in dl.iter_content(chunk_size=1 << 16):
                        fh.write(chunk)
            if target.stat().st_size > 50_000:
                common.info(f"Pixabay B-roll cached: {target.name} ({hit.get('user', 'pixabay')})")
                return target
            target.unlink(missing_ok=True)
        except Exception as exc:
            common.warn(f"Pixabay download failed: {exc}")
            target.unlink(missing_ok=True)
    common.warn("No suitable Pixabay clip found - using gradient fallback")
    return None
