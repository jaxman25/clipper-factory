'use client';

import { useState } from 'react';
import { cn } from '@/lib/cn';

const PLATFORM_LABELS = { tiktok: 'TikTok', reels: 'Reels', shorts: 'Shorts' };

function mediaUrl(id) {
  return `/api/media/${encodeURIComponent(id)}`;
}

/**
 * Clip preview with the multi-platform tabs from the transform pipeline:
 * transform jobs render three sibling files (21 s TikTok / 30 s Reels /
 * 59 s Shorts) listed in `clip.variants`, and picking a tab swaps the
 * played file. Non-transform clips get a single plain player.
 */
export default function MultiPlatformPlayer({ clip, className }) {
  const duration = Number(clip.duration_render || clip.duration || 0);
  const thumbnailUrl =
    clip.thumbnail_url || clip.thumbnail || clip.rendered_thumbnail || clip.thumb_url || '';

  const playables =
    Array.isArray(clip.variants) && clip.variants.length
      ? clip.variants.map((variant) => ({
          id: variant.id,
          platform: variant.platform || '',
          label: PLATFORM_LABELS[variant.platform] || variant.label || 'Version',
          duration: Number(variant.seconds) || 0,
          src: mediaUrl(variant.id),
        }))
      : [
          {
            id: clip.id,
            platform: '',
            label: 'Play',
            duration: duration ? Math.round(duration) : 0,
            src: clip.media_url || mediaUrl(clip.id),
          },
        ];

  const [activeId, setActiveId] = useState(() =>
    playables.some((p) => p.id === clip.id) ? clip.id : playables[0].id
  );
  const active = playables.find((p) => p.id === activeId) || playables[0];
  const showTabs = playables.length > 1;

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <div className="relative overflow-hidden rounded-xl bg-black shadow-xl">
        <video
          key={active.id}
          className="mx-auto aspect-[9/16] max-h-[420px] w-full bg-black object-contain"
          src={active.src}
          poster={thumbnailUrl || undefined}
          controls
          playsInline
          preload="metadata"
        />
      </div>

      {showTabs && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          {playables.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setActiveId(p.id)}
              aria-pressed={p.id === active.id}
              className={cn(
                'rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition',
                p.id === active.id
                  ? 'border-brand bg-brand/15 text-brand'
                  : 'border-line/60 bg-wash text-muted hover:border-line hover:text-fg'
              )}
            >
              {p.label}
              {p.duration ? ` ${p.duration}s` : ''}
            </button>
          ))}
        </div>
      )}

      {!showTabs && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        {playables.map((p) => (
          <span
            key={p.id}
            className={cn(
              'rounded-full border px-2 py-0.5',
              p.id === active.id
                ? 'border-brand/60 bg-brand/10 text-brand'
                : 'border-line/60 bg-wash'
            )}
          >
            {p.label}
            {p.duration ? ` · ${p.duration}s` : ''}
          </span>
        ))}
        </div>
      )}
    </div>
  );
}
