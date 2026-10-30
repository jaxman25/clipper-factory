import { appendAnalyticsPoint, listPosted, listQueue, loadAnalytics } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const YOUTUBE_STATISTICS = 'https://www.googleapis.com/youtube/v3/videos';
const BATCH = 50; // the API accepts at most 50 ids per videos.list call

function todayKey() {
  return new Date().toISOString().slice(0, 10);
}

/** Sum the live view counts of every clip YouTube actually hosts. */
async function youtubeViews(ids, apiKey) {
  let total = 0;
  for (let i = 0; i < ids.length; i += BATCH) {
    const url = new URL(YOUTUBE_STATISTICS);
    url.searchParams.set('part', 'statistics');
    url.searchParams.set('id', ids.slice(i, i + BATCH).join(','));
    url.searchParams.set('key', apiKey);
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 200);
      throw new Error(`YouTube API ${response.status}: ${detail}`);
    }
    const payload = await response.json();
    for (const item of payload.items || []) {
      total += Number(item?.statistics?.viewCount) || 0;
    }
  }
  return total;
}

/**
 * POST /api/analytics/refresh
 *
 * Records the *increase* in total YouTube views since the last recorded
 * sample, so the chart keeps its "sum of points == total views" invariant
 * instead of double counting a cumulative counter. One unit of YouTube quota
 * per batch; no-op (200 + reason) when the key or the videos are missing.
 */
export async function POST() {
  const apiKey = String(process.env.YOUTUBE_API_KEY || '').trim();
  if (!apiKey) {
    return Response.json({ ok: false, reason: 'YOUTUBE_API_KEY is not set' });
  }

  const ids = [
    ...new Set(
      [...listQueue(), ...listPosted()]
        .map((clip) => String(clip.youtube_video_id || '').trim())
        .filter(Boolean)
    ),
  ];
  if (!ids.length) {
    return Response.json({ ok: true, added: 0, reason: 'no clip carries a YouTube video id yet' });
  }

  try {
    const views = await youtubeViews(ids, apiKey);
    const recorded = loadAnalytics();
    const added = views - (Number(recorded.total_views) || 0);
    if (added <= 0) {
      return Response.json({ ok: true, added: 0, views, total_views: recorded.total_views });
    }

    const date = todayKey();
    const today = recorded.points.find((point) => point.date === date);
    const next = appendAnalyticsPoint({
      date,
      label: (today && today.label) || date,
      views: (Number(today && today.views) || 0) + added,
    });
    return Response.json(
      { ok: true, added, views, total_views: next.total_views, points: next.points },
      { headers: { 'Cache-Control': 'no-store' } }
    );
  } catch (err) {
    return Response.json({ ok: false, reason: String(err.message || err) }, { status: 502 });
  }
}
