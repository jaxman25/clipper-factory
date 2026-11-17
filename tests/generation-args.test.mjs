import test from 'node:test';
import assert from 'node:assert/strict';

import { buildWorkerArgs } from '../lib/generate-args.js';

const BASE = {
  url: 'https://youtu.be/example',
  jobId: 'job-test',
  numShorts: 10,
  mode: 'viral',
};

function valueAfter(args, flag) {
  const index = args.indexOf(flag);
  return index >= 0 ? args[index + 1] : undefined;
}

function countOf(args, flag) {
  return args.filter((entry) => entry === flag).length;
}

test('mode and requested count reach the worker unchanged', () => {
  const args = buildWorkerArgs({ ...BASE, numShorts: 15, mode: 'transform' });
  assert.equal(valueAfter(args, '--num-shorts'), '15');
  assert.equal(valueAfter(args, '--mode'), 'transform');
});

test('every supported mode is forwarded verbatim', () => {
  for (const mode of ['viral', 'equal', 'transform']) {
    const args = buildWorkerArgs({ ...BASE, mode });
    assert.equal(valueAfter(args, '--mode'), mode);
  }
});

test('an explicit language is forwarded and auto-detection is the default', () => {
  const explicit = buildWorkerArgs({ ...BASE, language: 'en' });
  assert.equal(countOf(explicit, '--language'), 1);
  assert.equal(valueAfter(explicit, '--language'), 'en');

  const automatic = buildWorkerArgs({ ...BASE });
  assert.equal(countOf(automatic, '--language'), 0);
});

test('clip length override is opt-in so config.json can apply', () => {
  const args = buildWorkerArgs({ ...BASE });
  assert.equal(countOf(args, '--clip-max-seconds'), 0);
});

test('an explicit per-job clip length is forwarded exactly once', () => {
  const args = buildWorkerArgs({ ...BASE, maxClipSeconds: 40 });
  assert.equal(countOf(args, '--clip-max-seconds'), 1);
  assert.equal(valueAfter(args, '--clip-max-seconds'), '40');
});

test('explicit clip length beats a saved preference, which is still forwarded', () => {
  const userConfig = { clip_max_seconds: 55, playback_speed: 1.2 };
  const args = buildWorkerArgs({
    ...BASE,
    maxClipSeconds: 40,
    overrides: { ...userConfig, user_config: userConfig },
  });

  assert.equal(countOf(args, '--clip-max-seconds'), 1);
  assert.equal(valueAfter(args, '--clip-max-seconds'), '40');

  const forwarded = JSON.parse(valueAfter(args, '--user-config-json'));
  assert.equal(forwarded.clip_max_seconds, 55);
  assert.equal(forwarded.playback_speed, 1.2);
});

test('user preferences are omitted when none were saved', () => {
  const args = buildWorkerArgs({ ...BASE, overrides: {} });
  assert.equal(valueAfter(args, '--user-config-json'), undefined);
});
