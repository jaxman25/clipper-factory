#!/usr/bin/env node
// Runs a Python script with whichever interpreter exists (python3, python, py -3).
import { spawn, spawnSync } from 'node:child_process';

const [script, ...args] = process.argv.slice(2);
if (!script) {
  console.error('Usage: node scripts/run-python.mjs <script.py> [args...]');
  process.exit(2);
}

const candidates = [process.env.PYTHON_BIN, 'python3', 'python', 'py'].filter(Boolean);
let bin = null;
let prefix = [];
for (const candidate of candidates) {
  const probe = spawnSync(candidate, ['-c', 'import sys'], { stdio: 'ignore' });
  if (probe.status === 0) {
    bin = candidate;
    prefix = candidate === 'py' ? ['-3'] : [];
    break;
  }
}
if (!bin) {
  console.error('No Python 3 interpreter found. Install Python 3.9+ or set PYTHON_BIN.');
  process.exit(1);
}

const child = spawn(bin, [...prefix, script, ...args], { stdio: 'inherit', env: process.env });
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}
child.on('exit', (code) => process.exit(code ?? 1));
