import fs from 'node:fs';
import { findClip, sanitizeId } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request, { params }) {
  const id = sanitizeId(params.id);
  const clip = findClip(id);
  if (!clip || !clip.thumb || !fs.existsSync(clip.thumb)) {
    return new Response(null, { status: 404 });
  }
  const image = fs.readFileSync(clip.thumb);
  return new Response(image, {
    status: 200,
    headers: {
      'Content-Type': 'image/jpeg',
      'Cache-Control': 'public, max-age=3600',
      'Content-Length': String(image.length),
    },
  });
}
