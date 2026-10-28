#!/usr/bin/env python3
"""One-time OAuth2 consent flow: prints the YouTube refresh token.

Save as scripts/get_youtube_refresh_token.py and run:
    python3 scripts/get_youtube_refresh_token.py

The script reads YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET from .env
(python-dotenv), opens a browser, and prints the refresh token. Copy the
printed token into .env as YOUTUBE_REFRESH_TOKEN.

The OAuth client in Google Cloud Console should be a Desktop app; the
run_local_server flow opens a temporary http://localhost server on a random
port (port=0) so the desktop client can receive the callback.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Load .env first so YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET are available.
here = Path(__file__).resolve().parent
if str(here.parent) not in sys.path:
    sys.path.insert(0, str(here.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=here.parent / ".env", override=False)

CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CLIENT_CONFIG = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    }
}


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first.")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri="http://localhost",
    )

    # Desktop (installed) flow: run a temporary local server the browser
    # redirects to. port=0 picks a random available port.
    credentials = flow.run_local_server(port=0, prompt="consent")

    print("Refresh token:")
    print(credentials.refresh_token)


if __name__ == "__main__":
    main()
