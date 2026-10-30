"""YouTube Shorts uploader.

Uses google-api-python-client + google-auth-oauthlib with a offline
refresh token (or service account) to upload a video to YouTube as a Short.

Config (environment variables only - no file is written or read):

    YOUTUBE_CLIENT_ID     - OAuth2 client ID (or Service Account JSON string)
    YOUTUBE_CLIENT_SECRET - OAuth2 client secret
    YOUTUBE_REFRESH_TOKEN - OAuth2 refresh token (for installed-app flow)

The uploader falls back to a service-account file if the client secret is
missing, or logs an error if no credentials are available.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Allow running directly: python3 backend/youtube_uploader.py
HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

try:
    from backend import common, paths
except ImportError:  # pragma: no cover
    import common  # type: ignore
    import paths  # type: ignore

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.oauth2 import service_account
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    # Dependencies are optional at import time; the worker checks
    # for them at the call site so the rest of the pipeline still works.
    build = None  # type: ignore
    MediaFileUpload = None  # type: ignore
    service_account = None  # type: ignore
    InstalledAppFlow = None  # type: ignore

# OAuth scopes: https://www.googleapis.com/auth/youtube.upload
# This lets us read metadata AND upload. For a read-only use case you
# could use https://www.googleapis.com/auth/youtube.incomeonly but that
# is not enough to upload.
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"

def load_youtube_config() -> dict[str, str]:
    """Load YouTube credentials from the environment (nothing is stored on disk)."""
    return {
        "client_id": os.getenv("YOUTUBE_CLIENT_ID", ""),
        "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN", ""),
        "service_account": os.getenv("YOUTUBE_SERVICE_ACCOUNT", ""),
    }


def _build_credentials(config: dict[str, str]):
    """Build Google OAuth2 credentials from a dict of config values.

    Supports two flows:
    * Installed app (client secret + refresh token) via InstalledAppFlow
    * Service account via service_account.Credentials.from_service_account_info

    Returns either a google.auth.Credentials object or ``None``.
    """
    client_id = (config.get("client_id") or "").strip()
    client_secret = (config.get("client_secret") or "").strip()
    refresh_token = (config.get("refresh_token") or "").strip()
    service_account_info = (config.get("service_account") or "").strip()

    if service_account_info:
        try:
            if service_account is None:
                return None
            return service_account.Credentials.from_service_account_info(
                {"type": "service_account", **service_account_info},
                scopes=[YOUTUBE_UPLOAD_SCOPE],
            )
        except Exception:
            return None

    if not (client_id and client_secret and refresh_token):
        return None

    if InstalledAppFlow is None:
        return None

    try:
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                }
            },
            scopes=[YOUTUBE_UPLOAD_SCOPE],
            redirect_uri="http://localhost",
        )
        # Use the refresh token directly; no need to hit the auth server.
        # This is the cleanest way to reuse a saved refresh token.
        flow._refresh_token = refresh_token  # type: ignore[attr-defined]
        return flow
    except Exception:
        return None


def _build_service(credentials) -> any:
    """Build the YouTube API service object, or None if unavailable."""
    if build is None or credentials is None:
        return None
    try:
        return build("youtube", "v3", credentials=credentials)
    except Exception:
        return None


def upload_short(video_path: str, title: str, description: str = "") -> dict[str, Any]:
    """Upload a video file to YouTube as a Short.

    Arguments
    ---------
    video_path : str
        Path to the MP4 file to upload.
    title : str
        Title shown on YouTube (max 100 characters).
    description : str
        Description (max 5000 characters).

    Returns
    -------
    dict
        ``{"ok": True, "video_id": "..."}`` on success, or
        ``{"ok": False, "error": "..."}`` on failure.
    """
    config = load_youtube_config()

    # Fail fast with a clear message if no credentials were supplied.
    if not config.get("client_id") and not config.get("service_account"):
        return {
            "ok": False,
            "error": "No YouTube credentials configured. Set YOUTUBE_CLIENT_ID, "
                     "YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN (or a Service "
                     "Account JSON) before enabling auto-posting.",
        }

    credentials = _build_credentials(config)
    service = _build_service(credentials)
    if service is None:
        return {
            "ok": False,
            "error": "Could not build YouTube API client. Check your credentials "
                     "and that google-api-python-client is installed.",
        }

    path = Path(video_path)
    if not path.exists():
        return {"ok": False, "error": f"Video file not found: {video_path}"}

    # YouTube short clips are 6–60 seconds. We keep the original file; the
    # duration check below is a courtesy check only.
    try:
        duration = float(subprocess_get_duration(video_path))
    except Exception:
        duration = 0.0

    if duration > 60:
        return {"ok": False, "error": f"Video is {duration:.1f}s — YouTube Shorts are 6–60s. "
                                     "Render a shorter clip or trim before uploading."}

    body = {
        "status": "private",  # private until you decide to share; can be set public later
        "recordable": True,  # YouTube Shorts use the video.recordable flag
        "file": {
            "title": _truncate_title(title, 100),
            "description": _truncate_description(description, 5000),
            "defaultLanguage": os.getenv("YOUTUBE_DEFAULT_LANGUAGE", "en"),
        },
    }

    media = MediaFileUpload(str(path), mimetype="video/mp4", resumable=True)

    try:
        response = (
            service.videos()
            .insert(
                part="status,snippet,recordable",
                body=body,
                media_body=media,
                # Hard limit: 60s for Shorts. Also 256MB for resumable uploads.
            )
        )

        # The insertion can take a while; use an explicit timeout on the
        # underlying http object. MediaFileUpload is resumable so we get
        # progress notifications if we implement them. We keep the default
        # of "no retry" here for simplicity and let the caller handle it.
        returned = response.execute()
        video_id = returned.get("id")
        if not video_id:
            return {"ok": False, "error": "No video ID returned from YouTube API"}

        return {"ok": True, "video_id": video_id, "status": returned.get("status", {}).get("uploadStatus")}
    except Exception as exc:
        # google-auth-oauthlib raises GoogleAuthError for auth failures;
        # googleapiclient.errors.HttpError for API errors (403, 400, 413...).
        return {"ok": False, "error": str(exc)}


def subprocess_get_duration(video_path: str) -> float:
    """Return the duration of a video file in seconds using ffprobe."""
    try:
        import subprocess
        ffprobe = common.which_ffprobe()
        cmd = [
            ffprobe, "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return float(result.stdout.strip())
        return 0.0
    except Exception:
        return 0.0


def _truncate_title(title: str, max_chars: int) -> str:
    title = title.strip()[:max_chars].rstrip()
    return title or "African Tales"


def _truncate_description(description: str, max_chars: int) -> str:
    description = description.strip()[:max_chars].rstrip()
    return description or "" if description else ""
