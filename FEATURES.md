# Features

Clipper Factory turns one YouTube link into ten scheduled, captioned, vertical clips and publishes them two at a time without opening an editor.

1. **Paste one link, generate ten shorts**
   Drop a YouTube URL into the dashboard and the server downloads the source, transcribes it, scores the best moments, reframes them to 9:16, burns captions, and queues the results. No uploads, no manual trimming.

2. **Transcription and viral scoring pipeline**
   Faster-whisper transcribes the source with word timestamps. The viral detector ranks 30–45 second windows on hooks, questions, and delivery spikes, then the scheduler picks the strongest moments for the queue.

3. **Face-aware vertical reframing**
   Clips are reframed to 1080×1920 by tracking the speaker. When no face is detected, a cinematic blurred background keeps the frame alive. The output is vertical by default, not a crop you have to fix later.

4. **Word-pop captions baked into every clip**
   Captions are burned onto the video as two-to-three word cards in bold yellow with a hook and outro baked in. Because the text is part of the video, captions travel to every platform instead of relying on each one to render them.

5. **Two-posts-a-day scheduling calendar**
   Clips land on a 19:00 and 21:00 EAT calendar by default, and the schedule is fully editable. Drag a chip to another slot from the posting calendar or clip card, and the scheduler follows it immediately.

6. **Auto-post to Instagram Reels and TikTok**
   On schedule, the platform integrations publish queued clips to Instagram Reels and TikTok. If a platform rejects a post, the clip is pushed to Telegram as a manual fallback so nothing disappears silently.

7. **Telegram bot and manual posting fallback**
   A Telegram bot can monitor the queue and forward clips that need a human touch. Individual clips can also be sent to Telegram directly from the queue when a platform post fails or manual review is required.

8. **Clip editing and caption management**
   Queued clips can be edited without leaving the dashboard. Authors can save captions, reschedule slots, and open the clip editor to adjust start and end times and request a re-render of the same clip.

9. **Viral moments, equal slices, and transform clip modes**
   Clip runs support three modes: viral moments for the strongest windows, equal slices for evenly divided clips, and a transform mode that produces platform-shaped outputs with rewritten metadata and multiple duration variants.

10. **AI metadata variants for titles, descriptions, and hashtags**
   When the pipeline generates metadata variants, the queue shows AI-suggested titles, descriptions, and hashtag sets. Editors can pick a variant, apply it to the caption, and save the selected set back to the clip.

11. **Multi-platform preview on each clip**
   Every queued clip gets a preview that shows how it is expected to appear across platforms. Supported platform labels include TikTok, Reels, Shorts, and a default play state, with the current platform badges visible on the card itself.

12. **Anti-flag safety badge for transformed clips**
   Transformed clips that meet the safe-to-post criteria are marked with a clear “Transformed: Safe to Post” badge. Standard clips show a simpler badge so the queue makes the transform status obvious at a glance.

13. **Queue, posted, and analytics history**
   The dashboard keeps separate views for queued and posted clips, with recent activity, runtime health, and an analytics view of total views and estimated earnings over time.

14. **Health, jobs, and observability**
   A health endpoint exposes queue size, posting times, timezone, running jobs, and uptime. The dashboard also surfaces active generation jobs, cancel controls, and a log tail so progress and failures are visible without SSH access.

15. **Settings, tokens, and per-platform integrations**
   Settings cover posting times, timezone, clip length, playback speed, caption color, outro text, hashtags, platform toggles, and YouTube auto-post. Token fields for Telegram, Instagram, TikTok, YouTube, and B-roll keep each integration visible as connected, incomplete, or not set.

16. **Credits and access control**
   Generation is gated by credits on non-localhost traffic. Localhost bypasses sign-in for local testing, admins get unlimited generation, and public users must sign in and have credits to start a job.

17. **Downloads, exports, and media endpoints**
   Finished clips are available through media and thumbnail endpoints, with downloads exposed for offline use. Exports can also act as a source of truth when a clip lives outside the active queue and posted folders.

18. **Job abort and worker failure handling**
   Running jobs can be cancelled from the dashboard. The server also marks jobs as errored when the worker dies before reporting, so the UI does not poll a phantom running job forever.
