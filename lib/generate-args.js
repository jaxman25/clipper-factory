/**
 * Pure worker-argument builder shared by /api/generate and its tests.
 *
 * Keeping this out of the route means the count/mode hand-off can be tested
 * without booting Next.js or touching the filesystem.
 */
export function buildWorkerArgs({
  url,
  jobId,
  numShorts,
  mode,
  language = '',
  maxClipSeconds = null,
  originalChannel = '',
  youtubeAutoPost = null,
  transformSpeed = null,
  overrides = {},
}) {
  const userConfig = overrides.user_config;
  return [
    '--url', url,
    '--job-id', jobId,
    '--num-shorts', String(numShorts),
    '--mode', mode,
    ...(language ? ['--language', String(language)] : []),
    ...(userConfig && typeof userConfig === 'object'
      ? ['--user-config-json', JSON.stringify(userConfig)]
      : []),
    ...(originalChannel ? ['--original-channel', originalChannel] : []),
    ...(youtubeAutoPost !== null ? ['--youtube-auto-post', String(youtubeAutoPost)] : []),
    ...(transformSpeed >= 1.1 && transformSpeed <= 1.2
      ? ['--transform-speed', String(transformSpeed)]
      : []),
    // Only an explicit request is forwarded. Forwarding a default here (the
    // old code always sent 25) overrode config.json's 45, made min 30 > max 25
    // and produced zero viral candidates.
    ...(maxClipSeconds != null ? ['--clip-max-seconds', String(maxClipSeconds)] : []),
    ...(overrides.timezone != null ? ['--user-timezone', String(overrides.timezone)] : []),
    ...(Array.isArray(overrides.posting_times) && overrides.posting_times.length
      ? ['--user-posting-times', JSON.stringify(overrides.posting_times)]
      : []),
    ...(overrides.shorts_per_video != null ? ['--user-shorts-per-video', String(overrides.shorts_per_video)] : []),
    ...(overrides.timezone != null ? ['--timezone', String(overrides.timezone)] : []),
    ...(Array.isArray(overrides.posting_times) && overrides.posting_times.length
      ? ['--posting-times', JSON.stringify(overrides.posting_times)]
      : []),
    ...(overrides.shorts_per_video != null ? ['--shorts-per-video', String(overrides.shorts_per_video)] : []),
    ...(overrides.clip_min_seconds != null ? ['--clip-min-seconds', String(overrides.clip_min_seconds)] : []),
    ...(overrides.playback_speed != null ? ['--playback-speed', String(overrides.playback_speed)] : []),
    ...(overrides.drum_volume_db != null ? ['--drum-volume-db', String(overrides.drum_volume_db)] : []),
    ...(overrides.caption_words_per_card != null ? ['--caption-words-per-card', String(overrides.caption_words_per_card)] : []),
    ...(overrides.outro_text != null ? ['--user-outro-text', overrides.outro_text] : []),
    ...(overrides.hashtags != null ? ['--user-hashtags', overrides.hashtags] : []),
    ...(overrides.caption_color != null ? ['--user-caption-color', overrides.caption_color] : []),
    ...(overrides.hook_seconds != null ? ['--hook-seconds', String(overrides.hook_seconds)] : []),
    ...(overrides.outro_seconds != null ? ['--outro-seconds', String(overrides.outro_seconds)] : []),
    ...(overrides.instagram === true ? ['--user-instagram', 'true'] : overrides.instagram === false ? ['--user-instagram', 'false'] : []),
    ...(overrides.tiktok === true ? ['--user-tiktok', 'true'] : overrides.tiktok === false ? ['--user-tiktok', 'false'] : []),
  ];
}
