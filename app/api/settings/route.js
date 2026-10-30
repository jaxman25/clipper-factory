import { DIRS, listPosted, listQueue, loadConfig, tokenStatus } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * GET returns the effective (read-only) configuration plus a redacted map of
 * which credential environment variables the process can actually see.
 *
 * There is no PUT any more: state/settings.json is gone because Render's disk
 * is ephemeral, so credentials and settings come from the environment and from
 * the committed config.json.
 */
export async function GET() {
  return Response.json(
    {
      config: loadConfig(),
      tokens: tokenStatus(),
      queue: listQueue().length,
      posted: listPosted().length,
      runtime: {
        data_root: DIRS.root,
        whisper_model: process.env.WHISPER_MODEL || 'tiny',
        scheduler_in_bot: ['1', 'true', 'yes'].includes(
          String(process.env.ACF_ENABLE_SCHEDULER || '').toLowerCase()
        ),
        public_base_url: Boolean(process.env.PUBLIC_BASE_URL || process.env.RENDER_EXTERNAL_URL),
      },
    },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

export async function PUT() {
  return Response.json(
    { error: 'Settings are managed via environment variables on this deployment.' },
    { status: 403 }
  );
}
