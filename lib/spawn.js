import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { ROOT, DIRS, childEnv, ensureDirs } from './store';

let cachedPython = null;

/** Resolve python3 (Linux/Render) with a python fallback for Windows dev. */
function pythonBin() {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  if (cachedPython) return cachedPython;
  for (const candidate of ['python3', 'python']) {
    try {
      execFileSync(candidate, ['--version'], { stdio: 'ignore', timeout: 5000 });
      cachedPython = candidate;
      return candidate;
    } catch (err) {
      /* try the next interpreter */
    }
  }
  cachedPython = 'python3';
  return cachedPython;
}

/** Fire-and-forget worker (generation can take 15 minutes). */
export function startPython(script, args, logName) {
  ensureDirs();
  const logFile = path.join(DIRS.state, `${logName}.log`);
  const fd = fs.openSync(logFile, 'a');
  const child = spawn(pythonBin(), [path.join(ROOT, script), ...args], {
    cwd: ROOT,
    env: childEnv({ PYTHONUNBUFFERED: '1' }),
    stdio: ['ignore', fd, fd],
    detached: true,
  });
  child.unref();
  return { pid: child.pid, log: logFile, child };
}

/** Run a worker and collect its output, with an optional timeout (ms). */
export function runPython(script, args, { timeoutMs = 0 } = {}) {
  return new Promise((resolve) => {
    const child = spawn(pythonBin(), [path.join(ROOT, script), ...args], {
      cwd: ROOT,
      env: childEnv({ PYTHONUNBUFFERED: '1' }),
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let timer = null;
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString();
      if (stdout.length > 200000) stdout = stdout.slice(-200000);
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
      if (stderr.length > 200000) stderr = stderr.slice(-200000);
    });
    if (timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        resolve({ code: null, stdout, stderr, timedOut });
      }, timeoutMs);
    }
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: `${stderr}\n${err.message}`, timedOut });
    });
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      if (!timedOut) resolve({ code, stdout, stderr, timedOut });
    });
  });
}

export function lastJsonLine(text) {
  for (const line of String(text || '').trim().split(/\r?\n/).reverse()) {
    const trimmed = line.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        return JSON.parse(trimmed);
      } catch (err) {
        /* keep looking */
      }
    }
  }
  return null;
}
