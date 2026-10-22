'use client';

import { useMemo, useState } from 'react';
import { nextDays, dayKeyInTZ, timeInTZ, zonedToIso } from '@/lib/time';

export default function CalendarBoard({ clips, timeZone, postingTimes, onReschedule, busy }) {
  const days = useMemo(() => nextDays(7, timeZone), [timeZone]);
  const slots = useMemo(() => {
    const list = Array.isArray(postingTimes) && postingTimes.length ? postingTimes : ['19:00', '21:00'];
    return [...list].sort();
  }, [postingTimes]);
  const [dragId, setDragId] = useState(null);
  const [hoverCell, setHoverCell] = useState(null);

  const cells = useMemo(() => {
    const map = {};
    let outside = 0;
    for (const clip of clips) {
      if (!clip.scheduled_for) {
        outside += 1;
        continue;
      }
      const day = dayKeyInTZ(clip.scheduled_for, timeZone);
      const slot = timeInTZ(clip.scheduled_for, timeZone);
      if (!days.some((entry) => entry.key === day) || !slots.includes(slot)) {
        outside += 1;
        continue;
      }
      const key = `${day}|${slot}`;
      if (!map[key]) map[key] = [];
      map[key].push(clip);
    }
    return { map, outside };
  }, [clips, days, slots, timeZone]);

  async function drop(day, slot) {
    const id = dragId;
    setDragId(null);
    setHoverCell(null);
    if (!id) return;
    const iso = zonedToIso(day.key, slot, timeZone);
    await onReschedule(id, iso);
  }

  return (
    <div>
      <div className="calendar">
        <div className="cal-corner">Slot ({timeZone.split('/').pop()})</div>
        {days.map((day) => (
          <div key={day.key} className={`cal-day-head ${day.isToday ? 'today' : ''}`}>
            {day.label}
          </div>
        ))}

        {slots.map((slot) => (
          <FragmentRow
            key={slot}
            slot={slot}
            days={days}
            cells={cells.map}
            dragId={dragId}
            hoverCell={hoverCell}
            busy={busy}
            onDragStart={setDragId}
            onDragEnd={() => {
              setDragId(null);
              setHoverCell(null);
            }}
            onHover={setHoverCell}
            onDrop={drop}
          />
        ))}
      </div>
      {cells.outside > 0 && (
        <p className="note" style={{ marginTop: 10 }}>
          {cells.outside} clip(s) scheduled outside this 7-day window — use the clip card date field to
          pull them in.
        </p>
      )}
    </div>
  );
}

function FragmentRow({
  slot,
  days,
  cells,
  dragId,
  hoverCell,
  busy,
  onDragStart,
  onDragEnd,
  onHover,
  onDrop,
}) {
  return (
    <>
      <div className="cal-slot-label">{slot}</div>
      {days.map((day) => {
        const key = `${day.key}|${slot}`;
        const cellClips = cells[key] || [];
        const isHover = hoverCell === key;
        return (
          <div
            key={key}
            className={`cal-cell ${isHover ? 'drop-active' : ''}`}
            onDragOver={(event) => {
              if (busy) return;
              event.preventDefault();
              onHover(key);
            }}
            onDragLeave={() => onHover(null)}
            onDrop={(event) => {
              event.preventDefault();
              if (!busy) onDrop(day, slot);
            }}
          >
            {cellClips.length === 0 ? (
              <span className="cal-empty">drop clip</span>
            ) : (
              cellClips.map((clip) => (
                <div
                  key={clip.id}
                  className={`cal-chip ${clip.state === 'posted' ? 'posted' : ''}`}
                  draggable={!busy && clip.state !== 'posted'}
                  onDragStart={() => onDragStart(clip.id)}
                  onDragEnd={onDragEnd}
                  title={clip.title || clip.id}
                >
                  <b>{clip.title || clip.id}</b>
                  <span>🔥 {Math.round(clip.viral_score || 0)}</span>
                </div>
              ))
            )}
          </div>
        );
      })}
    </>
  );
}
