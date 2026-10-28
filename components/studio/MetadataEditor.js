'use client';

import { useState } from 'react';
import { Check, Hash, PenLine, MessageSquare } from 'lucide-react';
import { cn } from '@/lib/cn';

export default function MetadataEditor({ clip, selected, onSelect }) {
  const meta = clip.metadata_variants;
  const hasMeta = Array.isArray(meta?.titles) && meta.titles.length;

  if (!hasMeta) {
    return (
      <div className="rounded-lg border border-line/60 bg-wash/40 p-3">
        <p className="text-[11px] text-subtle">No AI metadata generated for this clip.</p>
      </div>
    );
  }

  const pickText = (setIndex) => {
    const title = meta.titles[setIndex] || '';
    const description = meta.descriptions[setIndex] || '';
    const hashtags = Array.isArray(meta.hashtags[setIndex]) ? meta.hashtags[setIndex].join(' ') : '';
    onSelect?.({ title, description, hashtags, setIndex });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        <PenLine className="h-3.5 w-3.5 text-brand" />
        AI titles
      </div>
      <div className="grid gap-2">
        {meta.titles.map((title, idx) => {
          const selectedThis = selected?.setIndex === idx;
          return (
            <button
              key={idx}
              type="button"
              onClick={() => pickText(idx)}
              className={cn(
                'group w-full rounded-lg border text-left transition',
                selectedThis ? 'border-brand bg-brand/10' : 'border-line/80 bg-wash/40 hover:border-line'
              )}
            >
              <div className="flex items-start gap-2 p-3">
                <PenLine className={cn('h-3.5 w-3.5 shrink-0 mt-0.5', selectedThis ? 'text-brand' : 'text-subtle')} />
                <div className="min-w-0 flex-1">
                  <p className={cn('text-sm font-medium leading-snug line-clamp-2', selectedThis && 'text-brand')}>
                    {title}
                  </p>
                  {selectedThis && (
                    <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-brand/15 px-2 py-0.5 text-[9px] font-semibold uppercase text-brand">
                      <Check className="h-3 w-3" />
                      Using this
                    </span>
                  )}
                </div>
                {selectedThis && <Check className="h-3.5 w-3.5 text-brand" />}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        <MessageSquare className="h-3.5 w-3.5 text-brand" />
        AI descriptions
      </div>
      <div className="grid gap-2">
        {meta.descriptions.map((description, idx) => {
          const selectedThis = selected?.setIndex === idx;
          return (
            <button
              key={idx}
              type="button"
              onClick={() => pickText(idx)}
              className={cn(
                'group w-full rounded-lg border text-left transition',
                selectedThis ? 'border-brand bg-brand/10' : 'border-line/80 bg-wash/40 hover:border-line'
              )}
            >
              <div className="flex items-start gap-2 p-3">
                <MessageSquare className={cn('h-3.5 w-3.5 shrink-0 mt-0.5', selectedThis ? 'text-brand' : 'text-subtle')} />
                <div className="min-w-0 flex-1">
                  <p className={cn('text-sm leading-snug line-clamp-2', selectedThis && 'text-brand')}>
                    {description}
                  </p>
                  {selectedThis && (
                    <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-brand/15 px-2 py-0.5 text-[9px] font-semibold uppercase text-brand">
                      <Check className="h-3 w-3" />
                      Using this
                    </span>
                  )}
                </div>
                {selectedThis && <Check className="h-3.5 w-3.5 text-brand" />}
              </div>
            </button>
          );
        })}
      </div>

      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
        <Hash className="h-3.5 w-3.5 text-brand" />
        AI hashtag sets
      </div>
      <div className="grid gap-2">
        {meta.hashtags.map((tags, idx) => {
          const selectedThis = selected?.setIndex === idx;
          return (
            <button
              key={idx}
              type="button"
              onClick={() => pickText(idx)}
              className={cn(
                'group w-full rounded-lg border text-left transition',
                selectedThis ? 'border-brand bg-brand/10' : 'border-line/80 bg-wash/40 hover:border-line'
              )}
            >
              <div className="flex items-start gap-2 p-3">
                <Hash className={cn('h-3.5 w-3.5 shrink-0 mt-0.5', selectedThis ? 'text-brand' : 'text-subtle')} />
                <div className="min-w-0 flex-1">
                  <p className={cn('text-sm leading-snug', selectedThis && 'text-brand')}>
                    {Array.isArray(tags) ? tags.join(' ') : String(tags)}
                  </p>
                  {selectedThis && (
                    <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-brand/15 px-2 py-0.5 text-[9px] font-semibold uppercase text-brand">
                      <Check className="h-3 w-3" />
                      Using this
                    </span>
                  )}
                </div>
                {selectedThis && <Check className="h-3.5 w-3.5 text-brand" />}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
