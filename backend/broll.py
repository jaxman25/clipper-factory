"""Free Pexels B-roll for clips where no face can be tracked."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

try:
    from . import common, paths
except ImportError:  # pragma: no cover
    import common  # type: ignore
    import paths  # type: ignore

PEXELS_SEARCH = "https://api.pexels.com/videos/search"
DEFAULT_QUERY = os.getenv("PEXELS_QUERY", "african village night")


def fetch(query: str = DEFAULT_QUERY, dest_dir: Path | None = None) -> Path | None:
    """Download a portrait stock clip and cache it. Returns None without a key."""
    api_key = os.getenv("PEXELS_API_KEY", "").strip()
    if not api_key:
        common.info("PEXELS_API_KEY missing - using gradient fallback")
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
        common.warn("requests not installed - skipping Pexels B-roll")
        return None

    try:
        response = requests.get(
            PEXELS_SEARCH,
            params={"query": query, "orientation": "portrait", "per_page": 10, "size": "medium"},
            headers={"Authorization": api_key},
            timeout=25,
        )
        response.raise_for_status()
        videos = response.json().get("videos", [])
    except Exception as exc:  # network/API failure must never abort a render
        common.warn(f"Pexels search failed: {exc}")
        return None

    for index, video in enumerate(videos):
        files = sorted(
            video.get("video_files", []),
            key=lambda f: (f.get("width") or 0),
            reverse=True,
        )
        for file_info in files:
            link = file_info.get("link")
            width = file_info.get("width") or 0
            if not link or width < 540 or width > 2200:
                continue
            target = dest_dir / f"{cache_key}-{index}.mp4"
            try:
                with requests.get(link, stream=True, timeout=60) as dl:
                    dl.raise_for_status()
                    with open(target, "wb") as fh:
                        for chunk in dl.iter_content(chunk_size=1 << 16):
                            fh.write(chunk)
                if target.stat().st_size > 50_000:
                    common.info(f"Pexels B-roll cached: {target.name} ({video.get('user', {}).get('name', 'pexels')})")
                    return target
                target.unlink(missing_ok=True)
            except Exception as exc:
                common.warn(f"Pexels download failed: {exc}")
                target.unlink(missing_ok=True)
    common.warn("No suitable Pexels clip found - using gradient fallback")
    return None
