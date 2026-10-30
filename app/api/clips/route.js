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

// Legacy wrapper: callers that still POST to /api/clips (e.g. the old
// edit wiring in ClipCard.js) are forwarded to the dedicated edit endpoint.
// The real editor lives at /api/clips/edit and expects { clip_id, new_start, new_end }.
export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }
  if (body && (body.clip_id != null || body.new_start != null || body.new_end != null)) {
    const editReq = new Request(new URL('/api/clips/edit', request.url), {
      method: 'POST',
      headers: { 'Content-Type': request.headers.get('Content-Type') || 'application/json' },
      body: JSON.stringify(body),
    });
    return POST_edit(editReq);
  }
  return Response.json({ error: 'POST /api/clips is not supported; use /api/clips/edit for clip edits' }, { status: 404 });
}

// Keep the name out of the module export surface so it can be called internally.
async function POST_edit(request) {
  // Re-export the real handler by calling the route module directly is not
  // possible in Next.js route handlers — forward with a server-side fetch
  // to the same origin so the edit logic runs in-process.
  const internal = new URL('/api/clips/edit', request.url);
  const response = await fetch(internal, {
    method: request.method,
    headers: { 'Content-Type': request.headers.get('Content-Type') || 'application/json' },
    body: request.body,
  });
  return Response.json(await response.json(), { status: response.status, headers: response.headers });
}
