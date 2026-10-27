import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const STORE_URL = pathToFileURL(path.join(ROOT, 'lib', 'store.js')).href;

// ACF_DATA_ROOT must be set before lib/store.js is imported, so the store is
// loaded dynamically inside the hooks below.
let tmpRoot;
let store;

before(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'acf-jsonwrites-'));
  process.env.ACF_DATA_ROOT = tmpRoot;
});

after(() => {
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

async function loadStore() {
  if (!store) store = await import('../lib/store.js');
  return store;
}

const tempsIn = (dir) =>
  fs.existsSync(dir)
    ? fs.readdirSync(dir).filter((name) => name.endsWith('.tmp'))
    : [];

describe('writeJSON', () => {
  it('repeated writes keep JSON valid and leave no temp files', async () => {
    const { writeJSON } = await loadStore();
    const file = path.join(tmpRoot, 'state', 'jobs', 'job-repeat.json');
    const dir = path.dirname(file);
    for (let i = 0; i < 30; i += 1) {
      writeJSON(file, { i, text: 'héllo wörld ✓ 故事' });
      const data = JSON.parse(fs.readFileSync(file, 'utf8'));
      assert.equal(data.i, i);
      assert.equal(data.text, 'héllo wörld ✓ 故事');
    }
    assert.deepEqual(tempsIn(dir), []);
  });

  it('concurrent cross-process writers never share a temp file', async () => {
    const file = path.join(tmpRoot, 'state', 'jobs', 'job-race.json');
    const dir = path.dirname(file);
    const script = [
      "const { writeJSON } = await import(process.env.STORE_URL);",
      'for (let i = 0; i < 15; i += 1) {',
      '  writeJSON(process.env.TARGET, { w: process.env.W, i });',
      '}',
      // Each child verifies its OWN temp file is gone before exiting, so a
      // writer that leaks its temp file fails loudly instead of being noticed
      // (or masked) later by the parent.
      "const fs = await import('node:fs');",
      "const path = await import('node:path');",
      "const mine = fs.readdirSync(path.dirname(process.env.TARGET))",
      "  .filter((n) => n.startsWith(\`job-race.json.\${process.pid}.\`) && n.endsWith('.tmp'));",
      "if (mine.length) { console.error('CHILD_LEAKED ' + mine.join(',')); process.exit(4); }",
    ].join('\n');

    // Five independent Node processes hammering one destination - the same
    // pattern as the Python worker, the bot and the dashboard writing a job
    // document at the same time. The old fixed ".node.tmp" name made these
    // collide (rename failures / partially written JSON on Windows).
    const runs = [];
    for (let w = 0; w < 5; w += 1) {
      runs.push(
        execFileAsync(
          process.execPath,
          ['--input-type=module', '-e', script],
          {
            env: {
              ...process.env,
              STORE_URL,
              TARGET: file,
              W: String(w),
            },
          }
        )
      );
    }
    await Promise.all(runs); // rejects if any child failed or leaked a temp file

    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.ok('w' in data && 'i' in data);
    // On Windows a just-deleted file can still be listed for a brief moment
    // while an indexer/antivirus holds a handle (delete-pending). Poll for a
    // bounded window instead of a single readdir snapshot; temp files that
    // genuinely persist still fail the assertion.
    let leftovers = tempsIn(dir);
    for (let attempt = 0; attempt < 25 && leftovers.length > 0; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      leftovers = tempsIn(dir);
    }
    assert.deepEqual(leftovers, []);
  });

  it('failed serialization cleans up and keeps the old content', async () => {
    const { writeJSON } = await loadStore();
    const file = path.join(tmpRoot, 'state', 'jobs', 'job-fail.json');
    const dir = path.dirname(file);
    writeJSON(file, { i: 1 });
    assert.throws(() => writeJSON(file, { big: 1n })); // BigInt -> TypeError
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.deepEqual(data, { i: 1 });
    assert.deepEqual(tempsIn(dir), []);
  });
});

describe('job initialisation ordering', () => {
  it('writeJSONIfAbsent never clobbers worker progress', async () => {
    const { writeJSON, writeJSONIfAbsent } = await loadStore();
    const file = path.join(tmpRoot, 'state', 'jobs', 'job-init.json');

    // API initialisation runs before the spawn, but the guard must also
    // protect against any ordering slip: an existing document wins.
    writeJSON(file, {
      id: 'job-init',
      status: 'running',
      stage: 'download',
      progress: 42,
      pid: 4321,
    });

    const created = writeJSONIfAbsent(file, {
      id: 'job-init',
      status: 'running',
      stage: 'queued',
      progress: 0,
      pid: null,
    });

    assert.equal(created, false);
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert.equal(data.progress, 42);
    assert.equal(data.stage, 'download');
    assert.equal(data.pid, 4321);

    // When nothing exists yet the API's initial record is created.
    const fresh = path.join(tmpRoot, 'state', 'jobs', 'job-fresh.json');
    assert.equal(writeJSONIfAbsent(fresh, { id: 'job-fresh', status: 'running' }), true);
    assert.equal(JSON.parse(fs.readFileSync(fresh, 'utf8')).status, 'running');
  });

  it('updateJSON merges pid without losing worker fields', async () => {
    const { updateJSON, writeJSON } = await loadStore();
    const file = path.join(tmpRoot, 'state', 'jobs', 'job-merge.json');
    writeJSON(file, {
      id: 'job-merge',
      status: 'running',
      stage: 'download',
      progress: 42,
      pid: null,
    });

    const merged = updateJSON(file, { pid: 9876 });
    assert.equal(merged.pid, 9876);
    assert.equal(merged.progress, 42);
    assert.equal(merged.stage, 'download');

    // A missing document is never created by a merge.
    assert.equal(
      updateJSON(path.join(tmpRoot, 'state', 'jobs', 'nope.json'), { pid: 1 }),
      null
    );
    assert.equal(
      fs.existsSync(path.join(tmpRoot, 'state', 'jobs', 'nope.json')),
      false
    );
  });
});