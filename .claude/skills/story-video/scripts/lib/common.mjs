// Shared helpers: the tool cache, loading its packages, ffmpeg, the project folder.
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export const HOME = process.env.VIDEO_TOOLS_HOME || process.env.DEMO_VIDEO_HOME || path.join(os.homedir(), '.cache', 'product-demo-video');
export const SKILL = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const require = createRequire(path.join(HOME, 'package.json'));

export async function dep(name) {
  let resolved;
  try {
    resolved = require.resolve(name);
  } catch {
    die(`${name} is not installed. Run ${path.join(SKILL, 'scripts', 'setup.sh')}`);
  }
  const mod = await import(pathToFileURL(resolved).href);
  return mod.default && typeof mod.default === 'object' ? { ...mod.default, ...mod } : mod;
}

export function ffmpegPath() {
  const sys = spawnSync('which', ['ffmpeg'], { encoding: 'utf8' });
  if (sys.status === 0 && sys.stdout.trim()) return sys.stdout.trim();
  try {
    return require('ffmpeg-static');
  } catch {
    die('ffmpeg not found. Run scripts/setup.sh');
  }
}

export function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, { stdio: ['ignore', 'ignore', 'pipe'], ...opts });
    let err = '';
    p.stderr?.on('data', (d) => (err = (err + d).slice(-4000)));
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`${path.basename(cmd)} exited ${code}\n${err}`))));
  });
}

export function die(msg) {
  console.error(`\nerror: ${msg}\n`);
  process.exit(1);
}

export function parseArgs(argv) {
  const pos = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const [k, v] = a.slice(2).split('=');
      if (v !== undefined) flags[k] = v;
      else if (argv[i + 1] && !argv[i + 1].startsWith('--')) flags[k] = argv[++i];
      else flags[k] = true;
    } else pos.push(a);
  }
  return { pos, flags };
}

export const SHOTS = ['title', 'chapter', 'image', 'clip', 'quote', 'stat', 'text', 'list', 'chart', 'timeline', 'compare', 'outro'];

// story.json -> { root, demo }. "demo.scenes" aliases the beats so the narration
// script, which is shared with the demo skill, reads them unchanged.
export function loadProject(dir) {
  const root = path.resolve(dir || '.');
  const file = path.join(root, 'story.json');
  if (!fs.existsSync(file)) die(`no story.json in ${root}`);
  let story;
  try {
    story = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    die(`story.json does not parse: ${e.message}`);
  }
  if (!Array.isArray(story.beats) || !story.beats.length) die('story.json needs a non-empty "beats" list');
  story.beats.forEach((b, i) => {
    b.id = b.id || `b${String(i + 1).padStart(2, '0')}`;
    if (!b.shot || !b.shot.type) die(`beat "${b.id}" needs a "shot" with a "type"`);
    if (!SHOTS.includes(b.shot.type)) die(`beat "${b.id}": unknown shot type "${b.shot.type}" (${SHOTS.join(', ')})`);
    b.say = normaliseSay(b.say);
  });
  const ids = story.beats.map((b) => b.id);
  const dup = ids.find((id, i) => ids.indexOf(id) !== i);
  if (dup) die(`two beats share the id "${dup}"`);
  story.scenes = story.beats;
  return { root, demo: story, story };
}

export function normaliseSay(say) {
  if (!say) return [];
  const list = Array.isArray(say) ? say : [say];
  return list.map((s) => (typeof s === 'string' ? { text: s, speak: s } : { text: s.text, speak: s.speak || s.text }));
}

export function readJson(file, fallback) {
  if (!fs.existsSync(file)) {
    if (fallback !== undefined) return fallback;
    die(`missing ${file}`);
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

export function writeJson(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(data, null, 1));
}

// A render stalls for as long as the machine naps. On macOS, hold it awake.
export function keepAwake() {
  if (process.platform !== 'darwin') return;
  try {
    spawn('caffeinate', ['-is', '-w', String(process.pid)], { stdio: 'ignore', detached: true }).unref();
  } catch {}
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
