import { loadAnalytics, appendAnalyticsPoint } from '@/lib/store';

export async function GET() {
  try {
    const analytics = loadAnalytics();
    return Response.json(analytics, { headers: { 'Cache-Control': 'no-store' } });
  } catch (err) {
    return Response.json({ error: 'Could not load analytics' }, { status: 500 });
  }
}

export async function POST(request) {
  try {
    const body = await request.json();
    const point = {
      date: body.date || new Date().toISOString().slice(0, 10),
      label: body.label || new Date().toISOString().slice(0, 10),
      views: Number(body.views) || 0,
    };
    const analytics = appendAnalyticsPoint(point);
    return Response.json(analytics, { headers: { 'Cache-Control': 'no-store' } });
  } catch (err) {
    return Response.json({ error: 'Could not record analytics point' }, { status: 500 });
  }
}
