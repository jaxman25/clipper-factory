'use client';

import { useMemo, useState } from 'react';
import { nextDays, dayKeyInTZ, timeInTZ, zonedToIso } from '@/lib/time';
import { useStudio } from '@/components/studio/StudioProvider';
import { cn } from '@/lib/cn';

export default function ScheduleBoard() {
  const { clips, timeZone, postingTimes, reschedule, notify, job } = useStudio();
  const days = useMemo(() => nextDays(7, timeZone), [timeZone]);
  const slots = useMemo(() => [...(postingTimes || ['19:00', '21:00'])].sort(), [postingTimes]);
  const [dragId, setDragId] = useState(null);
  const [hover, setHover] = useState(null);
  const busy = job?.status === 'running';

  const { map, outside } = useMemo(() => {
    const cells = {};
    let missed = 0;
    for (const clip of clips) {
      if (!clip.scheduled_for) {
        missed += 1;
        continue;
      }
      const day = dayKeyInTZ(clip.scheduled_for, timeZone);
      const slot = timeInTZ(clip.scheduled_for, timeZone);
      if (!days.some((entry) => entry.key === day) || !slots.includes(slot)) {
        missed += 1;
        continue;
      }
      const key = `${day}|${slot}`;
      (cells[key] ||= []).push(clip);
    }
    return { map: cells, outside: missed };
  }, [clips, days, slots, timeZone]);

  async function drop(day, slot) {
    const id = dragId;
    setDragId(null);
    setHover(null);
    if (!id) return;
    try {
      await reschedule(id, zonedToIso(day.key, slot, timeZone));
      notify('Clip rescheduled');
    } catch (err) {
      notify(err.message);
    }
  }

  return (
    <div>
      <div className="overflow-x-auto pb-1">
        <div className="min-w-[760px]">
          <div className="grid grid-cols-[68px_repeat(7,minmax(0,1fr))] gap-2">
            <div className="pb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-subtle/80">
              Slot · {timeZone.split('/').pop()}
            </div>
            {days.map((day) => (
              <div
                key={day.key}
                className={cn(
                  'pb-2 text-center text-[11px] font-semibold',
                  day.isToday ? 'text-fg' : 'text-subtle'
                )}
              >
                {day.label}
                {day.isToday && <span className="ml-1 inline-block h-1 w-1 rounded-full bg-brand align-middle" />}
              </div>
            ))}

            {slots.map((slot) => (
              <div key={slot} className="contents">
                <div className="flex items-center pr-2 text-xs font-semibold tabular-nums text-muted">
                  {slot}
                </div>
                {days.map((day) => {
                  const key = `${day.key}|${slot}`;
                  const cellClips = map[key] || [];
                  const isHover = hover === key;
                  return (
                    <div
                      key={key}
                      onDragOver={(event) => {
                        if (busy) return;
                        event.preventDefault();
                        setHover(key);
                      }}
                      onDragLeave={() => setHover(null)}
                      onDrop={(event) => {
                        event.preventDefault();
                        if (!busy) drop(day, slot);
                      }}
                      className={cn(
                        'min-h-[76px] rounded-lg border border-dashed p-1.5 transition',
                        isHover
                          ? 'border-brand bg-brand/10'
                          : 'border-line bg-wash hover:border-line'
                      )}
                    >
                      {cellClips.length === 0 ? (
                        <span className="flex h-full items-center justify-center text-[10px] text-subtle/70">
                          empty
                        </span>
                      ) : (
                        <div className="space-y-1">
                          {cellClips.map((clip) => (
                            <div
                              key={clip.id}
                              draggable={!busy && clip.state !== 'posted'}
                              onDragStart={() => setDragId(clip.id)}
                              onDragEnd={() => {
                                setDragId(null);
                                setHover(null);
                              }}
                              title={clip.hook || clip.title || clip.id}
                              className={cn(
                                'cursor-grab rounded-md border-l-2 bg-wash px-1.5 py-1 text-[10px] leading-tight transition active:cursor-grabbing',
                                clip.state === 'posted'
                                  ? 'border-l-emerald-400/70 opacity-70'
                                  : 'border-l-brand hover:bg-wash-strong'
                              )}
                            >
                              <p className="line-clamp-2 font-medium text-fg/90">
                                {clip.hook || clip.title || clip.id}
                              </p>
                              <p className="mt-0.5 tabular-nums text-subtle">
                                🔥 {Math.round(clip.viral_score || 0)}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-subtle">
        <span>Drag a clip onto another cell to move its slot.</span>
        {outside > 0 && (
          <span>
            {outside} clip{outside === 1 ? '' : 's'} outside this 7-day window
          </span>
        )}
      </div>
    </div>
  );
}
