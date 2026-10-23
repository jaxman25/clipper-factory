#!/usr/bin/env node
// Starts Next.js on $PORT (Render injects it) or 3000, on every OS.
//
// The dashboard's polling endpoints (/api/generate, /api/logs) are short-
// polling HTTP requests that flood the terminal with request logs during
// video rendering. We spawn Next.js with piped stdio and filter those
// specific requests from the terminal output before printing anything.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const port = String(process.env.PORT || 3000);
const nextBin = require.resolve('next/dist/bin/next');

// Paths that the dashboard polls for live updates. These short-polling
// requests flood the terminal with request logs during rendering.
// The Next.js request log format is typically:
//   info  - GET /api/generate 200 271ms - 1.2kb
// or  GET /api/generate 200 271ms - 1.2kb
const POLLING_PATHS = ['/api/generate', '/api/logs'];

const child = spawn(process.execPath, [nextBin, 'start', '-p', port], {
  stdio: ['ignore', 'pipe', 'pipe'],
  env: process.env,
});

let buffer = '';
child.stdout.on('data', (chunk) => {
  buffer += chunk.toString('utf8');
  const lines = buffer.split(/\r?\n/);
  buffer = lines.pop() || '';

  for (const line of lines) {
    if (line.trim()) {
      // Suppress terminal noise from polling endpoints.
      if (!POLLING_PATHS.some((p) => line.includes(p))) {
        process.stdout.write(line + '\n');
      }
    }
  }
});

child.stderr.on('data', (chunk) => {
  const text = chunk.toString('utf8');
  for (const line of text.split(/\r?\n/)) {
    if (line.trim()) {
      // Suppress terminal noise from polling endpoints on stderr too.
      if (!POLLING_PATHS.some((p) => line.includes(p))) {
        process.stderr.write(line + '\n');
      }
    }
  }
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}
child.on('exit', (code) => process.exit(code ?? 0));
