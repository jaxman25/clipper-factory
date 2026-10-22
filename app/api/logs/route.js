import { readLogs } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.max(10, Math.min(500, Number(searchParams.get('limit')) || 120));
  return Response.json(
    { logs: readLogs(limit) },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}
