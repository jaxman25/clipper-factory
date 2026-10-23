import { listQueue, listPosted, loadConfig, sanitizeId, updateClip } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const config = loadConfig();
  return Response.json(
    {
      clips: listQueue(),
      posted: listPosted(),
      config: {
        timezone: config.timezone,
        posting_times: config.posting_times,
        platforms: config.platforms,
        youtube_auto_post: config.youtube_auto_post,
        hashtags: config.hashtags,
        outro_text: config.outro_text,
      },
    },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}

export async function PATCH(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }
  const id = sanitizeId(body.id);
  if (!id) return Response.json({ error: 'id is required' }, { status: 400 });

  const patch = {};
  if (typeof body.title === 'string') patch.title = body.title.slice(0, 160);
  if (typeof body.caption === 'string') patch.caption = body.caption.slice(0, 2200);
  if (typeof body.hook === 'string') patch.hook = body.hook.slice(0, 120);
  if (body.scheduled_for !== undefined) {
    const when = new Date(body.scheduled_for);
    if (Number.isNaN(when.getTime())) {
      return Response.json({ error: 'scheduled_for must be an ISO date' }, { status: 400 });
    }
    patch.scheduled_for = when.toISOString();
  }
  if (!Object.keys(patch).length) {
    return Response.json({ error: 'nothing to update' }, { status: 400 });
  }

  const updated = updateClip(id, patch);
  if (!updated) return Response.json({ error: 'clip not found in queue' }, { status: 404 });
  return Response.json({ ok: true, state: updated.state, clip: updated.item });
}
