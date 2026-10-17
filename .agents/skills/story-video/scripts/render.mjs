#!/usr/bin/env node
// Compose the video: step the stage frame by frame, pipe the frames to ffmpeg,
// lay the voice under it. The final build also writes what YouTube needs
// beside the video: subtitles, a description, a thumbnail.
//
//   node render.mjs PROJECT --draft            540p, 15 fps, plus check/sheet-*.png
//   node render.mjs PROJECT --draft --at 3.9,41  only those moments, to check/at.png
//   node render.mjs PROJECT --final [--out FILE] [--no-open]
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { parseArgs, loadProject, readJson, writeJson, dep, ffmpegPath, run, die, SKILL, keepAwake } from './lib/common.mjs';
import { buildTimeline, checkpoints, srt, description } from './lib/timeline.mjs';
import { mixTrack, writeWav } from './lib/audio.mjs';
keepAwake();

const { pos, flags } = parseArgs(process.argv.slice(2));
if (!pos[0] || (!flags.draft && !flags.final)) die('usage: render.mjs PROJECT --draft [--at T,T] | --final [--out FILE] [--no-open]');
const { root, story } = loadProject(pos[0]);
const draft = !!flags.draft;
const fps = draft ? 15 : Number(flags.fps || story.fps || 30);
const scale = draft ? 0.5 : 1;
const check = path.join(root, 'check');
fs.mkdirSync(check, { recursive: true });

const timings = readJson(path.join(root, 'audio', 'timings.json'));
const tl = buildTimeline({ root, story, timings, fps });

// Footage is stepped like everything else: one still per frame. Cut each clip
// beat's stretch into stills (cached until the clip or its timing changes).
for (const b of tl.beats) {
  if (b.shot.type !== 'clip') continue;
  const dir = path.join(check, 'clips', b.id);
  const need = (b.t1 - b.t0 + 1.2) * b.shot.speed;
  const key = JSON.stringify([b.shot.clip.path, fs.statSync(b.shot.clip.path).mtimeMs, b.shot.start, +need.toFixed(2)]);
  const keyFile = path.join(dir, 'key.json');
  if (!fs.existsSync(keyFile) || fs.readFileSync(keyFile, 'utf8') !== key) {
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    await run(ffmpegPath(), ['-y', '-ss', String(b.shot.start), '-t', need.toFixed(2), '-i', b.shot.clip.path,
      '-vf', 'fps=30,scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080', '-q:v', '3', path.join(dir, '%05d.jpg')]);
    fs.writeFileSync(keyFile, key);
  }
  const count = fs.readdirSync(dir).filter((f) => f.endsWith('.jpg')).length;
  if (!count) die(`beat "${b.id}": no frames could be read from ${b.shot.clip.path} at ${b.shot.start}s`);
  b.shot.frames = { base: pathToFileURL(dir).href + '/', count };
  const have = count / 30 / b.shot.speed;
  if (have < b.t1 - b.t0 - 0.2) console.log(`  note: beat "${b.id}" lasts ${(b.t1 - b.t0).toFixed(1)}s but its clip covers ${have.toFixed(1)}s: the last frame will hold. Use a longer cut, "speed" below 1, or shorter narration.`);
}

const { chromium } = await dep('playwright');
const browser = await chromium.launch({ args: ['--allow-file-access-from-files', '--hide-scrollbars'] });
const page = await browser.newPage({ viewport: { width: 1920 * scale, height: 1080 * scale }, deviceScaleFactor: 1 });
page.on('pageerror', (e) => die(`stage error: ${e.message}`));
await page.goto(pathToFileURL(path.join(SKILL, 'stage', 'story.html')).href);
await page.evaluate(([t, s]) => window.init(t, s), [tl, scale]);
writeJson(path.join(check, 'timeline.json'), tl);
const cdp = await page.context().newCDPSession(page);
const clampT = (t) => Math.max(0, Math.min(tl.duration - 0.01, t));
const grab = async (t, quality, format = 'jpeg') => {
  await page.evaluate((x) => window.renderAt(x), t);
  const r = await cdp.send('Page.captureScreenshot', format === 'png' ? { format } : { format, quality, optimizeForSpeed: draft });
  return Buffer.from(r.data, 'base64');
};
const sheetOf = async (cells, file, labelOf) => {
  const rows = Math.ceil(cells.length / 3);
  const sheet = await browser.newPage({ viewport: { width: 1980, height: 15 + rows * 437 }, deviceScaleFactor: 1 });
  await sheet.setContent(`<body style="margin:0;background:#15161c;font:20px -apple-system,sans-serif;color:#e9eaf0"><div style="display:grid;grid-template-columns:repeat(3,640px);gap:15px;padding:15px">${cells.map((c, j) =>
    `<div><img src="data:image/jpeg;base64,${c.img}" style="width:640px;height:360px;display:block;border-radius:6px"><div style="padding:8px 2px 4px;height:54px;overflow:hidden">${labelOf(c, j)}</div></div>`).join('')}</div></body>`);
  await sheet.screenshot({ path: file });
  await sheet.close();
};

if (flags.at) {
  const cells = [];
  for (const t of String(flags.at).split(',').map(Number).filter((n) => !Number.isNaN(n))) cells.push({ t, img: (await grab(clampT(t), 85)).toString('base64') });
  await sheetOf(cells, path.join(check, 'at.png'), (c) => `<b style="color:#9aa4ff">${c.t.toFixed(2)}s</b>`);
  await browser.close();
  console.log(`  ${cells.length} frame(s): ${path.join(check, 'at.png')}`);
  process.exit(0);
}

const wav = path.join(check, 'audio.wav');
writeWav(wav, mixTrack({ duration: tl.duration, sentences: tl.sentences, sfx: tl.sfx, sfxGain: story.sfxGain ?? 0.8 }));

let outFile;
if (draft) outFile = path.join(check, 'draft.mp4');
else if (flags.out) outFile = path.resolve(flags.out);
else {
  const dirs = [path.join(os.homedir(), 'Downloads'), path.join(os.homedir(), 'Desktop'), root];
  const dir = dirs.find((d) => {
    try {
      fs.accessSync(d, fs.constants.W_OK);
      return true;
    } catch {
      return false;
    }
  });
  outFile = path.join(dir, `${tl.name}.mp4`);
}

const music = story.music ? path.resolve(root, typeof story.music === 'string' ? story.music : story.music.file) : null;
if (music && !fs.existsSync(music)) die(`music file not found: ${music}`);
const musicGain = (typeof story.music === 'object' && story.music.gain) || 0.2;
const args = ['-y', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(fps), '-i', '-', '-i', wav];
if (music) {
  args.push('-stream_loop', '-1', '-i', music, '-filter_complex',
    `[2:a]volume=${musicGain},afade=t=in:d=1.5,afade=t=out:st=${Math.max(0, tl.duration - 2.5).toFixed(2)}:d=2.5[m];` +
    `[1:a]asplit=2[v1][v2];[m][v1]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=600[duck];` +
    `[v2][duck]amix=inputs=2:normalize=0:duration=first[a]`, '-map', '0:v', '-map', '[a]');
}
args.push('-t', tl.duration.toFixed(3), '-c:v', 'libx264', '-preset', draft ? 'veryfast' : 'slow', '-crf', draft ? '26' : '19',
  '-pix_fmt', 'yuv420p', '-r', String(fps), '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', outFile);
const ff = spawn(ffmpegPath(), args, { stdio: ['pipe', 'ignore', 'pipe'] });
let fferr = '';
ff.stderr.on('data', (d) => (fferr = (fferr + d).slice(-3000)));
const ffDone = new Promise((resolve, reject) => ff.on('close', (c) => (c === 0 ? resolve() : reject(new Error(`ffmpeg exited ${c}\n${fferr}`)))));

const total = Math.ceil(tl.duration * fps);
const started = Date.now();
for (let i = 0; i < total; i++) {
  const buf = await grab(i / fps, draft ? 80 : 96);
  if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
  if (i % (fps * 10) === 0) console.log(`  rendering ${Math.round((i / total) * 100)}%`);
}
ff.stdin.end();
await ffDone;
console.log(`  rendered ${total} frames in ${((Date.now() - started) / 1000).toFixed(0)}s`);

if (draft) {
  for (const f of fs.readdirSync(check)) if (/^sheet-\d+\.png$/.test(f)) fs.rmSync(path.join(check, f));
  const cells = [];
  for (const p of checkpoints(tl)) cells.push({ ...p, img: (await grab(clampT(p.t), 82)).toString('base64') });
  const per = 9;
  for (let i = 0; i < cells.length; i += per) {
    await sheetOf(cells.slice(i, i + per), path.join(check, `sheet-${String(i / per + 1).padStart(2, '0')}.png`),
      (c, j) => `<b style="color:#9aa4ff">#${i + j + 1} · ${c.t.toFixed(1)}s</b> ${c.label.replace(/</g, '&lt;')}`);
  }
  // one settled frame per beat, for a storyboard view
  const thumbs = path.join(check, 'beats');
  fs.rmSync(thumbs, { recursive: true, force: true });
  fs.mkdirSync(thumbs, { recursive: true });
  for (const b of tl.beats) fs.writeFileSync(path.join(thumbs, `${b.id}.jpg`), await grab(clampT(b.t1 - 0.15), 80));
  console.log(`  draft: ${outFile}\n  read every sheet before the final render: ${Math.ceil(cells.length / per)} sheet(s) in ${check}/sheet-*.png (${cells.length} frames)`);
}

const words = tl.sentences.reduce((n, s) => n + s.text.split(/\s+/).length, 0);
console.log(`\n${draft ? 'draft' : 'final'}: ${Math.floor(tl.duration / 60)}:${String(Math.round(tl.duration % 60)).padStart(2, '0')}, ${tl.beats.length} beats, ${words} words, ${tl.used.length} image(s) and clip(s), one new picture every ${(tl.duration / tl.beats.length).toFixed(1)}s`);
const long = tl.beats.filter((b) => b.t1 - b.t0 > 9).map((b) => `${b.id} (${(b.t1 - b.t0).toFixed(0)}s)`);
if (long.length) console.log(`  beats that hold one picture for over 9s, consider splitting: ${long.join(', ')}`);

if (!draft) {
  const base = outFile.replace(/\.mp4$/, '');
  fs.writeFileSync(base + '.srt', srt(tl));
  fs.writeFileSync(base + '-description.txt', description(tl, story));
  // the thumbnail: the moment named in story.json, else the title card once it has settled
  const card = tl.beats.find((b) => b.shot.type === 'title') || tl.beats[0];
  const at = story.thumbnail?.at ?? Math.min(card.t1 - 0.3, card.t0 + 2.6);
  fs.writeFileSync(base + '-thumbnail.png', await grab(clampT(at), 100, 'png'));
  for (const [i, f] of [0.12, 0.5, 0.88].entries()) {
    await run(ffmpegPath(), ['-y', '-ss', (tl.duration * f).toFixed(2), '-i', outFile, '-frames:v', '1', '-vf', 'scale=1280:-1', path.join(check, `final-${i + 1}.jpg`)]);
  }
  console.log(`\nsaved ${outFile}\n      ${base}.srt\n      ${base}-description.txt\n      ${base}-thumbnail.png\nlast look: ${check}/final-1.jpg, final-2.jpg, final-3.jpg`);
  if (!flags['no-open'] && process.platform === 'darwin') spawn('open', [outFile], { detached: true, stdio: 'ignore' }).unref();
}
await browser.close();
