#!/usr/bin/env bash
# Clipper Factory - one-shot local setup.
# Works on Debian/Ubuntu (incl. the Render Docker image) and macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

log() { printf '\033[1;33m[setup]\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- node + python
if ! have node; then
  log "Node.js not found. Installing Node 18..."
  if have apt-get; then
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
    apt-get install -y nodejs
  elif have brew; then
    brew install node@18
  else
    echo "Install Node.js 18+ manually: https://nodejs.org" >&2
    exit 1
  fi
fi

if ! have python3; then
  log "Installing Python 3..."
  if have apt-get; then apt-get update && apt-get install -y python3 python3-pip python3-venv
  elif have brew; then brew install python
  else echo "Install Python 3.9+ manually." >&2; exit 1; fi
fi

# ---------------------------------------------------------------- ffmpeg
if ! have ffmpeg; then
  log "Installing ffmpeg..."
  if have apt-get; then apt-get update && apt-get install -y ffmpeg fonts-dejavu-core
  elif have brew; then brew install ffmpeg
  else echo "Install ffmpeg manually." >&2; exit 1; fi
else
  log "ffmpeg already installed: $(ffmpeg -version | head -1)"
fi

# ---------------------------------------------------------------- folders
log "Creating workspace folders..."
mkdir -p downloads exports queue posted assets assets/broll state logs

# ---------------------------------------------------------------- python deps
PIP_ARGS=()
if python3 -m pip --version >/dev/null 2>&1; then
  # Debian bookworm+ marks the system interpreter as externally managed.
  if python3 -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
    PIP_ARGS+=(--break-system-packages)
  fi
  log "Installing Python dependencies..."
  python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
  python3 -m pip install "${PIP_ARGS[@]}" -r requirements.txt
  # tiktok_auto.py drives Playwright from Python (requirements.txt stays exact).
  python3 -m pip install "${PIP_ARGS[@]}" playwright
else
  log "pip missing - creating a virtualenv at .venv"
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt playwright
fi

# ---------------------------------------------------------------- node deps
log "Installing Node dependencies..."
npm install

# ---------------------------------------------------------------- playwright
log "Installing Playwright Chromium (used by TikTok auto-posting)..."
npx playwright install --with-deps chromium || npx playwright install chromium
python3 -m playwright install chromium || true

# ---------------------------------------------------------------- free assets
log "Generating royalty-free drum loop, night ambience and gradient card..."
python3 scripts/make_assets.py || log "Asset generation failed - renderer will synthesize fallbacks."

# ---------------------------------------------------------------- config files
if [ ! -f .env ]; then
  cp .env.example .env
  log "Created .env from .env.example - add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and PIXABAY_API_KEY."
else
  log ".env already exists - left untouched."
fi
if [ ! -f config.json ]; then
  log "config.json missing!" >&2
  exit 1
fi

mkdir -p downloads exports queue posted
log "Done."
log "Next: edit .env, then run: npm run dev  (dashboard) and python3 telegram_bot/bot.py (bot)."
log "Local generation test: python3 backend/main.py --url 'https://youtu.be/VIDEO_ID' --num-shorts 10"
