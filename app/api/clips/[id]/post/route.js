import { findClip, sanitizeId } from '@/lib/store';
import { lastJsonLine, runPython } from '@/lib/spawn';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300;

export async function POST(request, { params }) {
  const id = sanitizeId(params.id);
  if (!id) return Response.json({ error: 'invalid clip id' }, { status: 400 });
  const clip = findClip(id);
  if (!clip) return Response.json({ error: 'clip not found' }, { status: 404 });

  const run = await runPython(
    'scheduler/scheduler.py',
    ['--run-once', '--force', '--clip-id', id, '--quiet', '--time', 'manual'],
    { timeoutMs: 110000 }
  );

  const result = lastJsonLine(run.stdout);
  if (run.timedOut) {
    return Response.json(
      {
        ok: false,
        pending: true,
        message: 'Posting is still running in the background. Refresh the queue in a minute.',
        stderr: run.stderr.slice(-1200),
      },
      { status: 202 }
    );
  }
  if (!result) {
    return Response.json(
      { error: 'posting produced no result', stderr: run.stderr.slice(-1200) || run.stdout.slice(-1200) },
      { status: 502 }
    );
  }
  return Response.json(
    { ok: Boolean(result.posted), result },
    { status: result.posted ? 200 : 502 }
  );
}
