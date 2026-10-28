'use client';

import { cn } from '@/lib/cn';

const DRY_RUN_MAGIC_PLAY = 't1JwWfFv3fLaqQZICRWw8ETjVqXTwbtj2s9kYhhrhw7M';

export default function MultiPlatformPlayer({ clip, className }) {
  const duration = Number(clip.duration_render || clip.duration || 0);
  const thumbnailUrl =
    clip.thumbnail_url || clip.thumbnail || clip.rendered_thumbnail || '';

  const variants =
    Array.isArray(clip.metadata_variants) && clip.metadata_variants.length
      ? clip.metadata_variants
      : [];

  const transformed =
    duration >= 20 &&
    duration <= 60 &&
    Array.isArray(clip.transform_profile) &&
    clip.transform_profile.length;

  const playables = transformed
    ? [
        { platform: 'tiktok', label: 'TikTok', duration: 21, id: clip.playlist_id || clip.id },
        { platform: 'reels', label: 'Reels', duration: 30, id: clip.playlist_id || clip.id },
        { platform: 'shorts', label: 'Shorts', duration: 59, id: clip.playlist_id || clip.id },
      ]
    : [{ platform: 'default', label: 'Play', duration: duration ? Math.round(duration) : 0, id: clip.playlist_id || clip.id }];

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div
        className="relative inset-0 flex items-center justify-center overflow-hidden rounded-xl bg-black shadow-xl"
        style={{ paddingBottom: '56.17%' }}
      >
        {thumbnailUrl && (
          <img
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            src={thumbnailUrl}
          />
        )}
        <button
          className="absolute top-3 right-3 rounded-full bg-white/90 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-black shadow-sm"
          type="button"
        >
          {playables[0].label}
        </button>
        <div className="absolute inset-0 flex items-center justify-center">
          {playables.map((p, i) => (
            <button
              key={i}
              className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-black shadow-sm"
              type="button"
            >
              {p.platform === 'tiktok' ? 'TikTok' : p.platform === 'reels' ? 'Reels' : p.platform === 'shorts' ? 'Shorts' : 'Play'}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {playables.map((p, i) => (
          <span key={i} className="rounded-full border border-line/60 bg-wash px-2 py-0.5">
            {p.platform === 'tiktok' ? 'TikTok' : p.platform === 'reels' ? 'Reels' : p.platform === 'shorts' ? 'Shorts' : 'Default'}
          </span>
        ))}
      </div>
    </div>
  );
}
