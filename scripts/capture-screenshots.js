#!/usr/bin/env node
/**
 * Capture README screenshots for Clipper Factory.
 *
 * Uses Playwright's chromium (already installed for the TikTok uploader).
 * If a dev server is not already answering on http://localhost:3000/api/health,
 * one is started with `npm run dev -p 3000`. Every page is visited under every
 * viewport + theme combination, and the screenshot is only taken after the
 * network is idle and a short settle delay has passed so React has finished
 * rendering.
 *
 * Usage:
 *   node scripts/capture-screenshots.js
 *
 * Output:
 *   screenshots/desktop/light/{page}.png
 *   screenshots/desktop/dark/{page}.png
 *   screenshots/phone/light/{page}.png
 *   screenshots/phone/dark/{page}.png
 */

import { spawn, execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const require = createRequire(import.meta.url);
const SCREENSHOT_ROOT = path.resolve(ROOT, 'screenshots');
const BASE_URL = 'http://localhost:3000';
const HEALTH_URL = 'http://localhost:3000/api/health';

const PAGES = [
  '/',
  '/dashboard',
  '/dashboard/queue',
  '/dashboard/generate',
  '/dashboard/settings',
  '/login',
];

const COMBINATIONS = [
  { mode: 'desktop', viewport: { width: 1440, height: 900 }, theme: 'light' },
  { mode: 'desktop', viewport: { width: 1440, height: 900 }, theme: 'dark' },
  { mode: 'phone', viewport: { width: 390, height: 844 }, theme: 'light' },
  { mode: 'phone', viewport: { width: 390, height: 844 }, theme: 'dark' },
];

// ---------------------------------------------------------------------------
// Dev server management
// ---------------------------------------------------------------------------

async function httpGet(url) {
  const res = await fetch(url);
  return res;
}

/** Poll /api/health until it returns a successful response. */
async function waitForHealth(timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await httpGet(HEALTH_URL);
      if (res.ok) return true;
    } catch {
      // not ready yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

/** Wait until something accepts TCP connections on the dev port. */
async function waitForPort(port = 3000, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const net = await import('node:net');
      const socket = new net.Socket();
      await new Promise((resolve, reject) => {
        socket.setTimeout(500);
        socket.connect(port, '127.0.0.1', resolve);
        socket.on('error', reject);
      });
      socket.end();
      return true;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }
  return false;
}

async function startDevServer() {
  console.log(`Starting the dev server (next dev -p 3000)...`);
  // Next.js dev listens on port 3000. `next dev` is the only command in the
  // `npm run dev` chain that needs a running server, and `npm run dev` also
  // runs `npm test` first, which fails when no server is up and kills the
  // whole chain. Start Next.js directly so the screenshot script is self-
  // contained. Resolve the next binary through Node's module resolution so
  // the absolute path is correct on every OS.
  const nextBin = require.resolve('next/dist/bin/next', { paths: [ROOT] });
  const child = spawn(process.execPath, [nextBin, 'dev', '-p', '3000'], {
    cwd: ROOT,
    stdio: ['ignore', 'ignore', 'ignore'],
    env: { ...process.env, FORCE_COLOR: '0' },
  });

  // Wait for the port to accept TCP connections, then confirm the /api/health
  // endpoint responds. The port can be open before the app fully boots, so
  // both checks are needed.
  const portReady = await waitForPort(3000, 30_000);
  if (!portReady) {
    child.kill('SIGTERM');
    throw new Error('Dev server did not open port 3000 within 30s.');
  }
  const healthy = await waitForHealth(120_000);
  if (!healthy) {
    child.kill('SIGTERM');
    throw new Error('Dev server did not become healthy within 120s.');
  }
  console.log('Dev server is up.');
  return child;
}

// ---------------------------------------------------------------------------
// Theme handling
// ---------------------------------------------------------------------------

/**
 * ThemeToggle stores the preference in `localStorage` under the key "theme" and
 * applies it by setting `data-theme` on the `<html>` element. Because the
 * component reads `document.documentElement.dataset.theme`, a single
 * `page.evaluate()` that sets both the localStorage entry and the DOM attribute
 * reproduces exactly what the toggle does, and it overrides the server-side
 * default before any layout/props render.
 */
async function setTheme(page, theme) {
  await page.evaluate(
    (theme) => {
      try {
        localStorage.setItem('theme', theme);
      } catch (err) {
        // Private browsing: the toggle simply does not persist, but the DOM
        // attribute is still authoritative for this session.
      }
      document.documentElement.dataset.theme = theme;
    },
    theme
  );
}

// ---------------------------------------------------------------------------
// Main flow
// ---------------------------------------------------------------------------

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu'],
  });

  let server;
  try {
    if (await waitForHealth()) {
      console.log('Dev server already running; reusing it.');
      server = null;
    } else {
      server = await startDevServer();
    }

    // Make sure the screenshots directory exists.
    for (const combo of COMBINATIONS) {
      const dir = path.join(
        SCREENSHOT_ROOT,
        combo.mode,
        combo.theme
      );
      fs.mkdirSync(dir, { recursive: true });
    }

    for (const page of PAGES) {
      console.log(`\n=== Capturing ${page} ===`);

      for (const combo of COMBINATIONS) {
        const view = combo.viewport;
        const context = await browser.newPage({
          viewport: { width: view.width, height: view.height },
        });
        try {
          await context.goto(BASE_URL + page, {
            waitUntil: 'load',
            timeout: 60_000,
          });

          // Let React/SPA fully render before screenshotting.
          await context.waitForLoadState('domcontentloaded');
          await context.waitForTimeout(400);

          await setTheme(context, combo.theme);

          const screenshotDir = path.join(
            SCREENSHOT_ROOT,
            combo.mode,
            combo.theme
          );
          const filename = path.basename(page) || 'index';
          const dest = path.join(screenshotDir, `${filename}.png`);

          await context.screenshot({ path: dest, fullPage: false });
          console.log(`  ✓ ${dest}`);
        } catch (err) {
          console.error(`  ✗ Failed: ${err.message}`);
        } finally {
          await context.close();
        }
      }
    }

    console.log('\nDone. Write the README embeds next.');
  } finally {
    if (server) {
      server.kill('SIGTERM');
      console.log('Stopped the dev server.');
    }
    await browser.close();
  }
}

main().catch((err) => {
  console.error('Screenshot script failed:', err);
  process.exit(1);
});
