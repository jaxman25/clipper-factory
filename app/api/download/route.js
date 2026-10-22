import archiver from 'archiver';
import fs from 'node:fs';
import path from 'node:path';
import { Readable } from 'node:stream';
import { DIRS, listQueue, listPosted, findClip } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300;

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const single = searchParams.get('id');
  const archive = archiver('zip', { zlib: { level: 6 } });
  archive.on('error', (err) => {
    console.error('[download] archiver error', err);
  });

  if (single) {
    const clip = findClip(single);
    if (!clip) return Response.json({ error: 'clip not found' }, { status: 404 });
    archive.file(clip.video, { name: `${clip.id}.mp4` });
    if (clip.thumb && fs.existsSync(clip.thumb)) {
      archive.file(clip.thumb, { name: `${clip.id}.jpg` });
    }
    archive.append(JSON.stringify(clip.meta || {}, null, 2), { name: `${clip.id}.json` });
    archive.finalize();
    return new Response(Readable.toWeb(archive), {
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': `attachment; filename="${clip.id}.zip"`,
        'Cache-Control': 'no-store',
      },
    });
  }

  const clips = [...listQueue(), ...listPosted()];
  if (!clips.length) return Response.json({ error: 'queue is empty' }, { status: 404 });

  for (const clip of clips) {
    const dir = clip.state === 'posted' ? DIRS.posted : DIRS.queue;
    const video = path.join(dir, `${clip.id}.mp4`);
    if (fs.existsSync(video)) archive.file(video, { name: `clips/${clip.id}.mp4` });
    const thumb = path.join(dir, `${clip.id}.jpg`);
    if (fs.existsSync(thumb)) archive.file(thumb, { name: `clips/${clip.id}.jpg` });
    archive.append(JSON.stringify(clip, null, 2), { name: `clips/${clip.id}.json` });
  }

  const stamp = new Date().toISOString().slice(0, 10);
  archive.finalize();
  return new Response(Readable.toWeb(archive), {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="african-clips-${stamp}.zip"`,
      'Cache-Control': 'no-store',
    },
  });
}
