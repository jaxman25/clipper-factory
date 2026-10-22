export function dayKeyInTZ(dateInput, timeZone) {
  const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date);
}

export function timeInTZ(dateInput, timeZone) {
  const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

export function formatInTZ(dateInput, timeZone) {
  const date = dateInput instanceof Date ? dateInput : new Date(dateInput);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('en-GB', {
    timeZone,
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

export function tzOffsetMs(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date);
  const map = {};
  for (const part of parts) map[part.type] = part.value;
  const asUTC = Date.UTC(
    Number(map.year),
    Number(map.month) - 1,
    Number(map.day),
    Number(map.hour) % 24,
    Number(map.minute),
    Number(map.second)
  );
  return asUTC - date.getTime();
}

/** Convert "2026-10-22" + "19:00" in `timeZone` into a UTC ISO string. */
export function zonedToIso(dayKey, time, timeZone) {
  const [year, month, day] = dayKey.split('-').map(Number);
  const [hour, minute] = time.split(':').map(Number);
  const base = Date.UTC(year, month - 1, day, hour, minute, 0);
  let utc = base;
  for (let i = 0; i < 2; i += 1) {
    utc = base - tzOffsetMs(new Date(utc), timeZone);
  }
  return new Date(utc).toISOString();
}

export function nextDays(count, timeZone) {
  const days = [];
  const now = new Date();
  for (let i = 0; i < count; i += 1) {
    const probe = new Date(now.getTime() + i * 24 * 3600 * 1000);
    const key = dayKeyInTZ(probe, timeZone);
    if (days.some((entry) => entry.key === key)) continue;
    days.push({
      key,
      label: new Intl.DateTimeFormat('en-GB', {
        timeZone,
        weekday: 'short',
        day: '2-digit',
        month: 'short',
      }).format(probe),
      isToday: i === 0,
    });
  }
  return days;
}
