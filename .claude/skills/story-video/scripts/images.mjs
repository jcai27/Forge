#!/usr/bin/env node
// Find and fetch photographs and video clips that may legally be used, from Wikimedia Commons.
// Every image kept is recorded in assets/credits.json with its author,
// licence and source page, so the video can credit it.
//
//   node images.mjs search PROJECT "container ship 1956" [--n 12]
//       -> assets/_search/<slug>/sheet.png (numbered candidates: READ IT) + list
//   node images.mjs get PROJECT "container ship 1956" 3 --as ideal-x
//       -> assets/ideal-x.jpg, and a row in assets/credits.json
//   node images.mjs search PROJECT "container ship" --video
//   node images.mjs get PROJECT "container ship" 2 --as ship-clip --start 12 --dur 8
//       -> assets/ship-clip.mp4: those 8 seconds, silent, 1080p, with its credit
//   node images.mjs add PROJECT FILE --as name --author "..." --license "CC BY 4.0" --source URL
//       -> registers an image the user supplied
//   node images.mjs credits PROJECT
//       -> prints the credit lines for every image the story uses
import fs from 'node:fs';
import path from 'node:path';
import { parseArgs, loadProject, readJson, writeJson, dep, die, keepAwake, ffmpegPath, run } from './lib/common.mjs';
keepAwake();

const UA = 'story-video-skill/1.0 (local video tool; contact: the person running it)';
const API = 'https://commons.wikimedia.org/w/api.php';
// Licences that allow use in a monetised video with credit. Anything else is left out.
const OK = /^(public domain|pd\b|pd-|cc0|cc by(-sa)?( \d\.\d)?( [a-z-]+)?$|cc-by(-sa)?|no restrictions|attribution)/i;

const { pos, flags } = parseArgs(process.argv.slice(2));
const [cmd, projectDir] = pos;
if (!cmd || !projectDir) die('usage: images.mjs search|get|add|credits PROJECT ...');
const root = path.resolve(projectDir);
if (!fs.existsSync(root)) die(`no such project folder: ${root}`);
const assets = path.join(root, 'assets');
fs.mkdirSync(assets, { recursive: true });
const creditsFile = path.join(assets, 'credits.json');
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50);
const strip = (html) => String(html || '').replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#0?39;/g, "'").replace(/\s+/g, ' ').trim();

async function api(params) {
  const url = API + '?' + new URLSearchParams({ format: 'json', origin: '*', ...params });
  const r = await fetch(url, { headers: { 'User-Agent': UA } });
  if (!r.ok) die(`Wikimedia Commons answered ${r.status}`);
  return r.json();
}

// Video: the same licence rules. Each candidate carries its length and the best version up to 1080p.
async function searchVideo(query, n) {
  const j = await api({
    action: 'query', generator: 'search', gsrsearch: `${query} filetype:video`, gsrnamespace: '6', gsrlimit: String(Math.min(50, n * 3)),
    prop: 'videoinfo', viprop: 'url|size|mime|extmetadata|derivatives', viurlwidth: '640',
  });
  const pages = Object.values(j.query?.pages || {}).sort((a, b) => a.index - b.index);
  const out = [];
  for (const p of pages) {
    const vi = p.videoinfo?.[0];
    if (!vi || !vi.duration || !vi.thumburl) continue;
    const m = vi.extmetadata || {};
    const license = strip(m.LicenseShortName?.value) || 'unknown';
    if (!OK.test(license) || vi.width < 640) continue;
    const versions = (vi.derivatives || []).filter((d) => /^video\/webm/.test(d.type) && d.height <= 1080).sort((a, b) => b.height - a.height);
    const best = versions[0] || { src: vi.url, width: vi.width, height: vi.height };
    out.push({
      n: out.length + 1, video: true,
      title: p.title.replace(/^File:/, ''),
      width: best.width, height: best.height, duration: +vi.duration.toFixed(1),
      license, licenseUrl: m.LicenseUrl?.value || '',
      author: strip(m.Artist?.value).slice(0, 120) || 'unknown',
      date: strip(m.DateTimeOriginal?.value).slice(0, 40),
      description: strip(m.ImageDescription?.value).slice(0, 220),
      source: vi.descriptionurl, thumb: vi.thumburl, original: best.src,
    });
    if (out.length >= n) break;
  }
  return out;
}

async function search(query, n) {
  const j = await api({
    action: 'query', generator: 'search', gsrsearch: `${query} filetype:bitmap`, gsrnamespace: '6', gsrlimit: String(Math.min(50, n * 3)),
    prop: 'imageinfo', iiprop: 'url|size|mime|extmetadata', iiurlwidth: '640',
  });
  const pages = Object.values(j.query?.pages || {}).sort((a, b) => a.index - b.index);
  const out = [];
  for (const p of pages) {
    const ii = p.imageinfo?.[0];
    if (!ii || !/^image\/(jpeg|png|webp)$/.test(ii.mime)) continue;
    const m = ii.extmetadata || {};
    const license = strip(m.LicenseShortName?.value) || 'unknown';
    if (!OK.test(license)) continue;
    if (ii.width < 1000) continue; // too small to fill a 1080p frame
    out.push({
      n: out.length + 1,
      title: p.title.replace(/^File:/, ''),
      width: ii.width, height: ii.height,
      license, licenseUrl: m.LicenseUrl?.value || '',
      author: strip(m.Artist?.value).slice(0, 120) || 'unknown',
      credit: strip(m.Credit?.value).slice(0, 160),
      date: strip(m.DateTimeOriginal?.value).slice(0, 40),
      description: strip(m.ImageDescription?.value).slice(0, 220),
      source: ii.descriptionurl, thumb: ii.thumburl, original: ii.url,
    });
    if (out.length >= n) break;
  }
  return out;
}

async function download(url, file) {
  // Commons throttles bursts: wait and try again rather than give up
  for (let attempt = 0; ; attempt++) {
    const r = await fetch(url, { headers: { 'User-Agent': UA } });
    if (r.ok) return fs.writeFileSync(file, Buffer.from(await r.arrayBuffer()));
    if (r.status !== 429 || attempt >= 4) die(`could not download ${url}: ${r.status}`);
    await new Promise((res) => setTimeout(res, 4000 * (attempt + 1)));
  }
}

if (cmd === 'search') {
  const query = pos[2];
  if (!query) die('usage: images.mjs search PROJECT "query" [--n 12]');
  const found = await (flags.video ? searchVideo : search)(query, Number(flags.n || 12));
  const dir = path.join(assets, '_search', slug(query) + (flags.video ? '-video' : ''));
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  if (!found.length) {
    console.log(`no usable ${flags.video ? 'clips' : 'images'} for "${query}". Try fewer or different words: a place, a person's name, an object, a year.`);
    process.exit(0);
  }
  for (const c of found) await download(c.thumb, path.join(dir, `${String(c.n).padStart(2, '0')}.jpg`));
  writeJson(path.join(dir, 'candidates.json'), { query, found });
  // a numbered contact sheet to choose from by eye
  const { chromium } = await dep('playwright');
  const browser = await chromium.launch();
  const rows = Math.ceil(found.length / 4);
  const page = await browser.newPage({ viewport: { width: 1960, height: 20 + rows * 400 } });
  const cells = found.map((c) => {
    const b64 = fs.readFileSync(path.join(dir, `${String(c.n).padStart(2, '0')}.jpg`)).toString('base64');
    return `<div><div style="height:300px;background:#000;display:flex;align-items:center;justify-content:center;border-radius:6px;overflow:hidden"><img src="data:image/jpeg;base64,${b64}" style="max-width:100%;max-height:100%"></div>
      <div style="padding:6px 2px;height:74px;overflow:hidden"><b style="color:#ffd34d">#${c.n}</b> ${c.video ? `▶ ${c.duration}s · ` : ''}${c.width}×${c.height} · <span style="color:#8fd18f">${c.license.replace(/</g, '&lt;')}</span><br>${c.title.replace(/</g, '&lt;').slice(0, 90)}</div></div>`;
  }).join('');
  await page.setContent(`<body style="margin:0;background:#15161c;font:17px -apple-system,sans-serif;color:#e9eaf0"><div style="display:grid;grid-template-columns:repeat(4,470px);gap:15px;padding:15px">${cells}</div></body>`);
  await page.screenshot({ path: path.join(dir, 'sheet.png') });
  await browser.close();
  console.log(`"${query}": ${found.length} usable ${flags.video ? 'clip(s). The sheet shows one frame of each: a clip can change completely after it' : 'image(s)'}\n  look at them: ${path.join(dir, 'sheet.png')}\n`);
  for (const c of found) console.log(`  ${String(c.n).padStart(2)}  ${(c.video ? `${c.duration}s ` : '') + `${c.width}x${c.height}`.padEnd(10)} ${c.license.padEnd(16).slice(0, 16)} ${c.date.padEnd(12).slice(0, 12)} ${c.title.slice(0, 70)}\n      ${c.description.slice(0, 150)}`);
  console.log(`\n  keep one:  node images.mjs get ${projectDir} "${query}" N --as short-name${flags.video ? ' --start SECONDS --dur SECONDS' : ''}`);
} else if (cmd === 'get') {
  const [, , query, pick] = pos;
  if (!query || !pick || !flags.as) die('usage: images.mjs get PROJECT "query" N --as name');
  const cand = readJson(path.join(assets, '_search', slug(query) + (flags.video ? '-video' : ''), 'candidates.json'), null)
    || readJson(path.join(assets, '_search', slug(query) + '-video', 'candidates.json'), null);
  if (!cand) die(`search for "${query}" first`);
  const c = cand.found.find((x) => x.n === Number(pick));
  if (!c) die(`no candidate ${pick} for "${query}"`);
  if (c.video) {
    // take only the seconds wanted, straight from the source: silent, 30 fps, at most 1080p
    const start = Number(flags.start || 0);
    const dur = Math.min(Number(flags.dur || 10), Math.max(1, c.duration - start));
    const name = `${slug(flags.as)}.mp4`;
    await run(ffmpegPath(), ['-y', '-user_agent', UA, '-ss', String(start), '-t', String(dur), '-i', c.original, '-an',
      '-vf', "fps=30,scale='min(1920,iw)':-2", '-c:v', 'libx264', '-crf', '20', '-preset', 'medium', '-pix_fmt', 'yuv420p', path.join(assets, name)]);
    // a strip of frames across the cut, because one thumbnail says little about a clip
    const strip5 = path.join(assets, '_search', `${slug(flags.as)}-frames.jpg`);
    await run(ffmpegPath(), ['-y', '-i', path.join(assets, name), '-vf', `fps=${(5 / dur).toFixed(3)},scale=384:-2,tile=5x1`, '-frames:v', '1', strip5]).catch(() => {});
    const credits = readJson(creditsFile, {});
    credits[name] = { title: c.title, author: c.author, license: c.license, licenseUrl: c.licenseUrl, source: c.source, date: c.date, description: c.description, clip: { start, dur } };
    writeJson(creditsFile, credits);
    console.log(`saved assets/${name}  (${dur}s from ${start}s, ${c.license}, ${c.author})\n  what it shows, per its uploader: ${c.description || '(no description: open the source page before saying what it is)'}\n  five frames across it, READ THEM: ${strip5}\n  source: ${c.source}`);
    process.exit(0);
  }
  // Commons serves a fixed set of widths; anything else is refused
  const w = c.width >= 3840 ? 3840 : c.width >= 1920 ? 1920 : c.width;
  const j = await api({ action: 'query', titles: 'File:' + c.title, prop: 'imageinfo', iiprop: 'url', iiurlwidth: String(w) });
  const ii = Object.values(j.query.pages)[0].imageinfo[0];
  const ext = /\.png$/i.test(c.title) ? 'png' : 'jpg';
  const name = `${slug(flags.as)}.${ext}`;
  await download(ii.thumburl || ii.url, path.join(assets, name));
  const credits = readJson(creditsFile, {});
  credits[name] = { title: c.title, author: c.author, license: c.license, licenseUrl: c.licenseUrl, source: c.source, date: c.date, description: c.description };
  writeJson(creditsFile, credits);
  console.log(`saved assets/${name}  (${c.license}, ${c.author})\n  what it shows, per its uploader: ${c.description || '(no description: open the source page before saying what it is)'}\n  source: ${c.source}`);
} else if (cmd === 'add') {
  const file = pos[2];
  if (!file || !flags.as || !flags.license) die('usage: images.mjs add PROJECT FILE --as name --license "..." [--author "..."] [--source URL]');
  const ext = path.extname(file).toLowerCase() || '.jpg';
  const name = slug(flags.as) + ext;
  fs.copyFileSync(path.resolve(file), path.join(assets, name));
  const credits = readJson(creditsFile, {});
  credits[name] = { title: path.basename(file), author: flags.author || '', license: flags.license, licenseUrl: '', source: flags.source || 'supplied by the user', date: '', description: '' };
  writeJson(creditsFile, credits);
  console.log(`saved assets/${name}`);
} else if (cmd === 'credits') {
  const { story } = loadProject(root);
  const credits = readJson(creditsFile, {});
  const used = new Set();
  JSON.stringify(story.beats, (k, v) => {
    if (typeof v === 'string' && /\.(jpe?g|png|webp|mp4|mov|webm)$/i.test(v)) used.add(path.basename(v));
    return v;
  });
  for (const f of used) {
    const c = credits[f];
    console.log(c ? `${f}: "${c.title}" by ${c.author}, ${c.license}. ${c.source}` : `${f}: NO CREDIT RECORDED. Find its licence or replace it.`);
  }
} else die(`unknown command "${cmd}" (search, get, add, credits)`);
