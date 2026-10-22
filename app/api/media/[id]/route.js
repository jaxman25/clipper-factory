import fs from 'node:fs';
import { Readable } from 'node:stream';
import { findClip, sanitizeId } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function headersFor(size, filename, download) {
  return {
    'Content-Type': 'video/mp4',
    'Accept-Ranges': 'bytes',
    'Content-Length': String(size),
    'Cache-Control': 'public, max-age=3600',
    'Content-Disposition': `${download ? 'attachment' : 'inline'}; filename="${filename}"`,
  };
}

export async function GET(request, { params }) {
  const id = sanitizeId(params.id);
  const clip = findClip(id);
  if (!clip) return Response.json({ error: 'clip not found' }, { status: 404 });

  const { size } = fs.statSync(clip.video);
  const download = new URL(request.url).searchParams.get('download') === '1';
  const filename = `${id}.mp4`;
  const range = request.headers.get('range');

  if (range) {
    const match = /bytes=(\d*)-(\d*)/.exec(range);
    if (match) {
      const start = match[1] ? Number(match[1]) : 0;
      const end = match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
      if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= size) {
        return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      }
      const stream = fs.createReadStream(clip.video, { start, end });
      return new Response(Readable.toWeb(stream), {
        status: 206,
        headers: {
          ...headersFor(end - start + 1, filename, download),
          'Content-Range': `bytes ${start}-${end}/${size}`,
        },
      });
    }
  }

  return new Response(Readable.toWeb(fs.createReadStream(clip.video)), {
    status: 200,
    headers: headersFor(size, filename, download),
  });
}

export async function HEAD(request, { params }) {
  const id = sanitizeId(params.id);
  const clip = findClip(id);
  if (!clip) return new Response(null, { status: 404 });
  const { size } = fs.statSync(clip.video);
  return new Response(null, {
    status: 200,
    headers: {
      'Content-Type': 'video/mp4',
      'Accept-Ranges': 'bytes',
      'Content-Length': String(size),
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
