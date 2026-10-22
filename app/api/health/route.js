import { listQueue, listPosted, listJobs, loadConfig } from '@/lib/store';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const queue = listQueue();
  const posted = listPosted();
  const running = listJobs(10).find((job) => job.status === 'running');
  const config = loadConfig();
  return Response.json(
    {
      status: 'ok',
      queue: queue.length,
      posted: posted.length,
      running_job: running ? running.id : null,
      posting_times: config.posting_times,
      timezone: config.timezone,
      time: new Date().toISOString(),
      uptime_seconds: Math.round(process.uptime()),
    },
    { headers: { 'Cache-Control': 'no-store' } }
  );
}
