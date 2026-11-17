# AGENTS.md

## Commands
- `npm run dev` → `npm test` then `next dev -p 3000` (tests must pass first)
- `npm test` → `node --test "tests/*.test.mjs"`
- `python -m unittest discover -s tests` (Python tests)
- single Python test: `python -m unittest tests.test_job_state`
- `npm run lint` → `next lint` (no typecheck script)
- `npm run smoke` → offline render smoke test (needs Python deps)
- Bot: `python3 telegram_bot/bot.py`

## Architecture
- Frontend: Next.js 14 App Router; backend: Python 3.14
- `app/api/generate/route.js` spawns worker via `lib/spawn.js` (`startPython`)
- Worker `backend/main.py` writes job state to `state/jobs/<id>.json`, queue items to `state/queue/<id>.json`
- `lib/store.js` (Node) and `backend/paths.py` (Python) both read `ACF_DATA_ROOT` for the state dir

## Tests
- `tests/logs-api.test.mjs`, `tests/settings-sync.test.mjs` skip unless a dev server runs on :3000

## API quirks
- `PUT /api/settings` returns 403 (env-only migration); settings page uses localStorage for UI overrides

## Env quirks
- `ACF_DATA_ROOT` defaults to `/tmp` on Render (ephemeral)
- `ACF_USERS_FILE` is independent — setting only `ACF_DATA_ROOT` leaves credits in the wiped working dir; set both to `/data/...` on Render with a persistent disk

## Mode dispatch
- `--mode viral` → `viral.find_candidates` + `select_top`
- `--mode equal` → `viral.equal_slices`
- `--mode transform` → `_render_transform` (LLM + edge-tts + 3 platform variants: 21/30/59s)

## Gotchas
- `npm run dev` kills port 3000 first via kill-port
- One generation job at a time (lock at `/tmp/state/generate.lock`)
- `config.json` is the only file-based override; settings come from env vars
- Media route `/api/media/[id]` is public by design (needed for Instagram)
- Assets: use `npm run logos`, never hand-edit raster files