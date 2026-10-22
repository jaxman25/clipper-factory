import fs from 'node:fs';
import { findClip, getSecret, sanitizeId } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 120;

export async function POST(request) {
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }
  const id = sanitizeId(body.id);
  const clip = findClip(id);
  if (!clip) return Response.json({ error: 'clip not found' }, { status: 404 });

  const token = getSecret('TELEGRAM_BOT_TOKEN');
  const chat = getSecret('TELEGRAM_CHAT_ID');
  if (!token || !chat) {
    return Response.json(
      { error: 'Telegram is not configured. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Settings.' },
      { status: 400 }
    );
  }

  const { size } = fs.statSync(clip.video);
  const caption = String(clip.meta.caption || clip.meta.title || id).slice(0, 900);
  const buffer = fs.readFileSync(clip.video);
  const endpoint = size > 45 * 1024 * 1024 ? 'sendDocument' : 'sendVideo';
  const field = endpoint === 'sendVideo' ? 'video' : 'document';

  const form = new FormData();
  form.append('chat_id', chat);
  form.append('caption', caption);
  if (endpoint === 'sendVideo') form.append('supports_streaming', 'true');
  form.append(field, new Blob([buffer], { type: 'video/mp4' }), `${id}.mp4`);

  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/${endpoint}`, {
      method: 'POST',
      body: form,
      signal: AbortSignal.timeout(110000),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      return Response.json(
        { error: data.description || 'Telegram rejected the upload' },
        { status: 502 }
      );
    }
    return Response.json({ ok: true, message_id: data.result?.message_id });
  } catch (err) {
    return Response.json({ error: `Telegram upload failed: ${err.message}` }, { status: 502 });
  }
}
