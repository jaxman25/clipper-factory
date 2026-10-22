#!/usr/bin/env python3
"""TikTok uploader driven by Playwright.

    python3 auto-post/tiktok_auto.py --file /tmp/queue/clip.mp4 --caption "text"
    python3 auto-post/tiktok_auto.py --login      # one-time interactive login

The session is stored in ``auth.json`` locally. On Render (no display) paste a
base64 of that file into ``TIKTOK_AUTH_B64``; it is materialised under
``/tmp/state/tiktok_auth.json`` at post time. Without a session the script skips
cleanly so the scheduler can carry on with Instagram.

Only the final JSON line goes to stdout; every diagnostic goes to stderr.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("ACF_DATA_ROOT", "/tmp"))
STATE = DATA_ROOT / "state"
AUTH_FILE = Path(os.getenv("TIKTOK_AUTH_FILE", str(STATE / "tiktok_auth.json")))
LOCAL_AUTH = ROOT / "auth.json"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?lang=en"

CAPTION_SELECTORS = [
    "[contenteditable='true']",
    ".public-DraftEditor-content",
    "[data-e2e='caption-input']",
    "div[role='textbox']",
]
POST_SELECTORS = [
    "button[data-e2e='post_video_button']",
    "button[data-e2e='post_video']",
    "button:has-text('Post')",
]


def log(message: str) -> None:
    print(f"[tiktok] {message}", file=sys.stderr, flush=True)


def emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


def resolve_auth() -> Path | None:
    """Prefer an explicit file, then TIKTOK_AUTH_B64, then the local auth.json."""
    encoded = os.getenv("TIKTOK_AUTH_B64", "").strip()
    if encoded:
        try:
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTH_FILE.write_bytes(base64.b64decode(encoded))
            return AUTH_FILE
        except Exception as exc:
            log(f"TIKTOK_AUTH_B64 is not valid base64: {exc}")
    if AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 20:
        return AUTH_FILE
    if LOCAL_AUTH.exists() and LOCAL_AUTH.stat().st_size > 20:
        return LOCAL_AUTH
    return None


def has_session_cookie(context) -> bool:
    return any(cookie.get("name") in ("sessionid", "sessionid_ss") for cookie in context.cookies())


def do_login() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        emit({"ok": False, "platform": "tiktok", "error": "playwright not installed (pip install playwright)"})
        return 1

    target = paths_auth_for_write()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
        log("Log into TikTok in the opened browser window (up to 5 minutes)...")
        deadline = time.time() + 300
        while time.time() < deadline:
            if has_session_cookie(context):
                break
            page.wait_for_timeout(2000)
        if not has_session_cookie(context):
            emit({"ok": False, "platform": "tiktok", "error": "login timed out - no sessionid cookie"})
            browser.close()
            return 1
        context.storage_state(path=str(target))
        browser.close()
    log(f"session saved to {target}")
    emit({"ok": True, "platform": "tiktok", "auth_file": str(target)})
    return 0


def paths_auth_for_write() -> Path:
    # On a laptop write auth.json next to the project; inside a container use /tmp.
    if os.getenv("RENDER") or os.getenv("ACF_DATA_ROOT"):
        target = AUTH_FILE
    else:
        target = LOCAL_AUTH
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def upload(file: Path, caption: str, headless: bool) -> int:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        emit({"ok": False, "platform": "tiktok", "error": "playwright not installed (pip install playwright)"})
        return 1

    auth = resolve_auth()
    if auth is None:
        log("no TikTok session found - skipping")
        emit({
            "ok": False,
            "skipped": True,
            "platform": "tiktok",
            "reason": "no TikTok session; run `python3 auto-post/tiktok_auto.py --login` "
                      "and set TIKTOK_AUTH_B64 on Render",
        })
        return 0

    shot_dir = STATE / "screenshots"
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot = shot_dir / f"tiktok-{int(time.time())}.png"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            storage_state=str(auth),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id=os.getenv("TZ", "Africa/Nairobi"),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            log("opening TikTok upload studio")
            page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)

            if "/login" in page.url:
                raise RuntimeError("TikTok session expired - run the --login flow again")

            log("attaching video file")
            file_input = page.wait_for_selector("input[type='file']", state="attached", timeout=90000)
            file_input.set_input_files(str(file))

            # Upload progress: the Post button stays disabled until processing ends.
            caption_box = None
            deadline = time.time() + 240
            while time.time() < deadline and caption_box is None:
                for selector in CAPTION_SELECTORS:
                    locator = page.locator(selector).first
                    if locator.count() and locator.is_visible():
                        caption_box = locator
                        break
                if caption_box is None:
                    page.wait_for_timeout(2500)
            if caption_box is None:
                raise RuntimeError("caption editor never appeared (upload may have failed)")

            caption_box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.keyboard.type(caption[:2200], delay=8)
            log("caption added")

            post_button = None
            deadline = time.time() + 300
            while time.time() < deadline:
                for selector in POST_SELECTORS:
                    locator = page.locator(selector).first
                    if locator.count() and locator.is_visible() and locator.is_enabled():
                        post_button = locator
                        break
                if post_button is not None:
                    break
                page.wait_for_timeout(3000)
            if post_button is None:
                raise RuntimeError("Post button never became enabled")

            log("clicking Post")
            post_button.click()
            page.wait_for_timeout(8000)
            try:
                page.wait_for_url("**/tiktokstudio/content**", timeout=120000)
            except PlaywrightTimeout:
                # Some accounts stay on the studio page with a success toast.
                body = page.inner_text("body")[:4000].lower()
                if "being uploaded" not in body and "manage your posts" not in body:
                    page.screenshot(path=str(shot), full_page=True)
                    raise RuntimeError(
                        "upload not confirmed by TikTok; screenshot saved to " + str(shot)
                    )
            log("upload confirmed")
            emit({"ok": True, "platform": "tiktok", "file": str(file)})
            return 0
        except Exception as exc:
            try:
                page.screenshot(path=str(shot), full_page=True)
                log(f"screenshot saved to {shot}")
            except Exception:
                pass
            log(str(exc))
            emit({"ok": False, "platform": "tiktok", "error": str(exc)})
            return 1
        finally:
            context.close()
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a short to TikTok with Playwright")
    parser.add_argument("--file", help="Path to the vertical mp4")
    parser.add_argument("--caption", default="", help="TikTok caption")
    parser.add_argument("--login", action="store_true", help="Open a browser and save auth.json")
    parser.add_argument("--headed", action="store_true", help="Show the browser while posting")
    args = parser.parse_args()

    if args.login:
        return do_login()

    if not args.file:
        emit({"ok": False, "platform": "tiktok", "error": "--file is required"})
        return 1
    video = Path(args.file)
    if not video.exists():
        emit({"ok": False, "platform": "tiktok", "error": f"video not found: {video}"})
        return 1

    headless = not args.headed and os.getenv("TIKTOK_HEADLESS", "1") != "0"
    return upload(video, args.caption, headless)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
