import Link from 'next/link';
import {
  ArrowRight,
  CalendarClock,
  Camera,
  Captions,
  Crop,
  Music2,
  Send,
  Sparkles,
  Video,
} from 'lucide-react';

const FEATURES = [
  {
    n: '01',
    icon: Video,
    title: 'Paste one link',
    body: 'Drop a YouTube URL and the worker pulls the source at up to 1080p. No uploads, no manual trimming.',
    preview: (
      <div className="space-y-2">
        <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-[#0E0E10] px-3 py-2">
          <Video className="h-4 w-4 shrink-0 text-brand" />
          <span className="truncate text-[11px] text-zinc-400">youtube.com/watch?v=8Kc2…</span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-brand/15 px-3 py-2">
          <span className="text-[11px] font-semibold text-brand">Generate 10 shorts</span>
          <ArrowRight className="h-3.5 w-3.5 text-brand" />
        </div>
      </div>
    ),
  },
  {
    n: '02',
    icon: Sparkles,
    title: 'Story beats, found',
    body: 'Whisper transcribes every word, then the viral detector scores 30–45s windows on hooks, questions and delivery spikes.',
    preview: (
      <div className="space-y-1.5">
        {[92, 64, 78, 46, 88].map((w, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="h-1.5 rounded-full bg-white/10" style={{ width: `${w}%` }}>
              <div
                className={`h-1.5 rounded-full ${i === 0 ? 'bg-brand' : 'bg-white/25'}`}
                style={{ width: i === 0 ? '100%' : '60%' }}
              />
            </div>
            <span className="text-[10px] tabular-nums text-zinc-600">{95 - i * 9}</span>
          </div>
        ))}
      </div>
    ),
  },
  {
    n: '03',
    icon: Crop,
    title: 'Vertical by default',
    body: 'Face-aware 9:16 reframing that follows the speaker. No face? A cinematic blurred bed keeps the frame alive.',
    preview: (
      <div className="relative h-[86px] overflow-hidden rounded-lg border border-white/10 bg-gradient-to-br from-[#1b2a52] to-[#0b0b10]">
        <div className="absolute inset-y-2 left-1/2 w-9 -translate-x-1/2 rounded border border-dashed border-brand/70 bg-brand/10" />
        <span className="absolute bottom-1.5 left-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[9px] font-semibold text-white">
          1080 × 1920
        </span>
      </div>
    ),
  },
  {
    n: '04',
    icon: Captions,
    title: 'Word-pop captions',
    body: 'Two-to-three word cards in bold yellow with a hook and outro baked in. Captions are burned, so they travel everywhere.',
    preview: (
      <div className="flex h-[86px] flex-col items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-[#0E0E10]">
        <div className="flex gap-1">
          <span className="rounded bg-[#FFD700] px-1.5 py-0.5 text-[10px] font-black text-black">SHE</span>
          <span className="rounded bg-[#FFD700] px-1.5 py-0.5 text-[10px] font-black text-black">WARNED</span>
        </div>
        <span className="rounded bg-white px-1.5 py-0.5 text-[10px] font-black text-black">HIM</span>
      </div>
    ),
  },
  {
    n: '05',
    icon: CalendarClock,
    title: 'Two posts a day',
    body: 'Clips land on a 19:00 and 21:00 EAT calendar. Drag a chip to another slot and the scheduler follows instantly.',
    preview: (
      <div className="rounded-lg border border-white/10 bg-[#0E0E10] p-2">
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: 14 }).map((_, i) => (
            <div
              key={i}
              className={`h-3 rounded-sm ${[8, 12].includes(i) ? 'bg-brand' : 'bg-white/10'}`}
            />
          ))}
        </div>
        <div className="mt-2 flex justify-between text-[9px] text-zinc-500">
          <span>19:00</span>
          <span>21:00</span>
        </div>
      </div>
    ),
  },
  {
    n: '06',
    icon: Send,
    title: 'Auto-post everywhere',
    body: 'Instagram Reels and TikTok publish on schedule. If a platform balks, the clip is pushed to Telegram for a manual drop.',
    preview: (
      <div className="flex items-center justify-between gap-2">
        {[
          { icon: Camera, label: 'Reels' },
          { icon: Music2, label: 'TikTok' },
          { icon: Send, label: 'Telegram' },
        ].map(({ icon: Icon, label }) => (
          <div
            key={label}
            className="flex flex-1 flex-col items-center gap-1 rounded-lg border border-white/10 bg-[#0E0E10] py-2"
          >
            <Icon className="h-4 w-4 text-brand" />
            <span className="text-[9px] uppercase tracking-wider text-zinc-500">{label}</span>
          </div>
        ))}
      </div>
    ),
  },
];

export default function LandingPage() {
  return (
    <div className="relative overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] bg-[radial-gradient(60%_60%_at_50%_0%,rgba(47,128,237,0.22),transparent_70%)]" />

      <header className="sticky top-0 z-40 border-b border-white/5 bg-ink/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-5">
          <Link href="/" aria-label="Clipper Factory" className="flex items-center">
            <img src="/assets/logos/icon-1024.png" alt="Clipper Factory" width={32} height={32} className="h-8 w-8" />
          </Link>

          <nav className="hidden items-center gap-7 text-sm text-muted md:flex">
            <a href="#features" className="transition hover:text-white">
              Features
            </a>
            <a href="#pipeline" className="transition hover:text-white">
              Pipeline
            </a>
            <Link href="/dashboard" className="transition hover:text-white">
              Dashboard
            </Link>
          </nav>

          <Link href="/dashboard" className="btn btn-primary btn-sm">
            Open dashboard
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </header>

      <main>
        <section className="mx-auto grid w-full max-w-6xl items-center gap-14 px-5 pb-20 pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:pt-24">
          <div>
            <span className="pill">
              <span className="h-1.5 w-1.5 rounded-full bg-brand" />
              Shorts autopilot · 19:00 &amp; 21:00 EAT
            </span>

            <h1 className="mt-6 text-balance text-4xl font-bold leading-[1.05] tracking-tight sm:text-5xl lg:text-6xl">
              One link in.
              <br />
              <span className="text-brand">Ten scroll-stopping shorts</span> out.
            </h1>

            <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-muted sm:text-base">
              Clipper Factory downloads a YouTube video, finds the moments worth clipping, reframes them
              for 9:16, burns word-pop captions on top, then posts two a day while you sleep.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link href="/dashboard" className="btn btn-primary">
                Start a clip run
                <ArrowRight className="h-4 w-4" />
              </Link>
              <a href="#features" className="btn btn-ghost">
                See the pipeline
              </a>
            </div>

            <dl className="mt-12 grid max-w-md grid-cols-3 gap-6 border-t border-white/5 pt-6">
              {[
                ['1080×1920', 'Vertical output'],
                ['2 / day', 'Scheduled slots'],
                ['0', 'Timelines opened'],
              ].map(([value, label]) => (
                <div key={label}>
                  <dt className="text-lg font-semibold tracking-tight">{value}</dt>
                  <dd className="mt-0.5 text-[11px] uppercase tracking-wider text-zinc-500">{label}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="relative mx-auto w-full max-w-[320px]">
            <div className="absolute -inset-6 -z-10 rounded-[3rem] bg-brand/10 blur-2xl" />
            <div className="rounded-[2.2rem] border border-white/10 bg-surface p-2 shadow-2xl">
              <div className="relative aspect-[9/16] overflow-hidden rounded-[1.7rem] bg-gradient-to-b from-[#1d316b] via-[#121a33] to-[#0a0a0b]">
                <div className="absolute inset-x-0 top-0 flex items-center justify-between p-3 text-[10px] font-medium">
                  <span className="rounded-full bg-black/50 px-2 py-1 text-white/90">9:16 · 34s</span>
                  <span className="rounded-full bg-black/50 px-2 py-1 text-[#FFD700]">🔥 92</span>
                </div>

                <div className="absolute inset-x-0 bottom-16 flex flex-col items-center gap-1.5 px-6">
                  <span className="rounded bg-white px-2 py-0.5 text-xs font-black text-black">THE VILLAGE</span>
                  <span className="rounded bg-[#FFD700] px-2 py-0.5 text-xs font-black text-black">WENT SILENT</span>
                </div>

                <div className="absolute inset-x-3 bottom-6 h-1 overflow-hidden rounded-full bg-white/20">
                  <div className="h-full w-2/3 rounded-full bg-white" />
                </div>

                <div className="absolute inset-x-3 bottom-2 flex justify-between text-[9px] text-white/50">
                  <span>0:23</span>
                  <span>0:34</span>
                </div>
              </div>
            </div>

            <div className="absolute -left-6 top-16 hidden rounded-lg border border-white/10 bg-surface/90 px-3 py-2 text-[11px] shadow-xl backdrop-blur sm:block">
              <span className="text-muted">Queued</span>
              <b className="ml-1.5 text-white">10 clips</b>
            </div>
            <div className="absolute -right-4 bottom-24 hidden rounded-lg border border-white/10 bg-surface/90 px-3 py-2 text-[11px] shadow-xl backdrop-blur sm:block">
              <span className="text-muted">Next post</span>
              <b className="ml-1.5 text-white">19:00</b>
            </div>
          </div>
        </section>

        <section id="features" className="border-t border-white/5 py-16 sm:py-20">
          <div className="mx-auto w-full max-w-6xl px-5">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="label text-brand">The factory floor</p>
                <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                  Six steps, zero editing.
                </h2>
              </div>
              <p className="max-w-sm text-sm text-muted">
                Swipe through the pipeline. Every stage runs on the same box that serves this page.
              </p>
            </div>
          </div>

          <div className="mt-10 flex snap-x snap-mandatory gap-4 overflow-x-auto px-5 pb-6 no-scrollbar sm:px-[max(1.25rem,calc((100vw-72rem)/2))]">
            {FEATURES.map(({ n, icon: Icon, title, body, preview }) => (
              <article
                key={n}
                className="card card-pad w-[280px] shrink-0 snap-start transition-transform duration-300 will-change-transform hover:scale-[1.02] sm:w-[320px]"
              >
                <div className="flex items-center justify-between">
                  <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-brand/15 text-brand">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="text-[11px] font-semibold tracking-[0.2em] text-zinc-600">{n}</span>
                </div>

                <h3 className="mt-5 text-base font-semibold tracking-tight">{title}</h3>
                <p className="mt-2 min-h-[62px] text-[13px] leading-relaxed text-muted">{body}</p>

                <div className="mt-4 rounded-lg bg-black/20 p-3">{preview}</div>
              </article>
            ))}
          </div>
        </section>

        <section id="pipeline" className="border-t border-white/5 py-16 sm:py-20">
          <div className="mx-auto grid w-full max-w-6xl gap-10 px-5 lg:grid-cols-[0.9fr_1.1fr]">
            <div>
              <p className="label text-brand">Under the hood</p>
              <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                A real pipeline, not a wrapper.
              </h2>
              <p className="mt-4 max-w-md text-sm leading-relaxed text-muted">
                yt-dlp pulls the source, faster-whisper transcribes it, the viral detector ranks the
                windows, ffmpeg reframes and burns captions, then the scheduler publishes. Everything is
                observable from the dashboard.
              </p>
              <Link href="/dashboard" className="btn btn-primary mt-8">
                Open the dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>

            <ol className="space-y-3">
              {[
                ['Download & transcribe', 'yt-dlp → faster-whisper tiny, word timestamps with VAD.'],
                ['Score & select', '30–45s windows ranked on hooks, questions and volume spikes.'],
                ['Reframe & caption', 'Face-centred 9:16 crop, drum bed, ASS word cards.'],
                ['Queue & publish', 'Two slots a day, Instagram Reels and TikTok with a Telegram fallback.'],
              ].map(([title, body], i) => (
                <li key={title} className="card flex gap-4 p-4">
                  <span className="mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white/[0.04] text-[11px] font-bold text-muted">
                    0{i + 1}
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold">{title}</h3>
                    <p className="mt-1 text-[13px] leading-relaxed text-muted">{body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="border-t border-white/5 py-16">
          <div className="mx-auto w-full max-w-6xl px-5">
            <div className="card relative overflow-hidden p-8 text-center sm:p-12">
              <div className="pointer-events-none absolute inset-x-0 -top-24 h-48 bg-[radial-gradient(50%_60%_at_50%_50%,rgba(47,128,237,0.28),transparent_70%)]" />
              <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Your next ten shorts are one paste away.</h2>
              <p className="mx-auto mt-3 max-w-md text-sm text-muted">
                Sign in with your dashboard credentials and drop a link. The first clips land in the queue
                in 5–15 minutes.
              </p>
              <Link href="/dashboard" className="btn btn-primary mt-7">
                Open dashboard
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/5 py-10">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-4 px-5 text-xs text-zinc-500 sm:flex-row">
          <p className="font-medium text-zinc-400">Clipper Factory</p>
          <div className="flex items-center gap-6">
            <Link href="/dashboard" className="transition hover:text-white">
              Dashboard
            </Link>
            <Link href="/dashboard/settings" className="transition hover:text-white">
              Settings
            </Link>
            <span>/api/health</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
