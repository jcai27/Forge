// The edit. Turns story.json + narration timings into one resolved timeline:
// when each beat plays, when each sentence starts (the cues that reveals hang
// on), how beats cross, where chapters fall. stage/story.js only draws it.
import path from 'node:path';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { die } from './common.mjs';

const GAP = 0.24; // between sentences
const MIN = { title: 3.2, chapter: 2.4, outro: 3.6, clip: 2, quote: 3, stat: 2.6, chart: 3.4, timeline: 3, list: 2.6, compare: 3, text: 2.2, image: 2 };
export const TRANSITIONS = ['cut', 'dissolve', 'dip', 'flash', 'zoom', 'slide', 'wipe'];
const TIME = { dissolve: 0.6, dip: 0.9, flash: 0.45, zoom: 0.7, slide: 0.7, wipe: 0.85 };

// Typefaces: open-licensed Google Fonts bundled in stage/fonts. "font" in story.json names one.
const SANS = '"Inter", "Helvetica Neue", Arial, sans-serif';
const FONTS = {
  montserrat: { display: `"Montserrat", ${SANS}`, body: SANS, weight: 800, spacing: '-.025em', quote: '"Playfair Display", Georgia, serif' },
  oswald: { display: `"Oswald", ${SANS}`, body: SANS, weight: 600, spacing: '.01em', upper: true, quote: '"Playfair Display", Georgia, serif' },
  bebas: { display: `"Bebas Neue", "Oswald", ${SANS}`, body: SANS, weight: 400, spacing: '.03em', upper: true, quote: '"Playfair Display", Georgia, serif' },
  poppins: { display: `"Poppins", ${SANS}`, body: SANS, weight: 800, spacing: '-.02em', quote: `"Poppins", ${SANS}` },
  dmsans: { display: `"DM Sans", ${SANS}`, body: `"DM Sans", ${SANS}`, weight: 800, spacing: '-.03em', quote: '"Playfair Display", Georgia, serif' },
  playfair: { display: '"Playfair Display", Georgia, serif', body: `"DM Sans", ${SANS}`, weight: 800, spacing: '-.01em', quote: '"Playfair Display", Georgia, serif' },
};
export const FONT_NAMES = Object.keys(FONTS);

// Three looks. "style" in story.json names one, or { "base": "...", "accent": "#..." } adjusts one.
const STYLES = {
  documentary: {
    theme: 'dark', bg: ['#0b0c0f', '#1c1a16'], ink: '#f5efe4', accent: '#e6ad45', accent2: '#c9772e',
    font: 'montserrat', grade: 'contrast(1.07) saturate(0.8) sepia(0.16) brightness(0.96)', transition: 'dissolve',
  },
  bold: {
    theme: 'dark', bg: ['#0a0b18', '#1d1145'], ink: '#ffffff', accent: '#ff4d6d', accent2: '#ffb347',
    font: 'poppins', grade: 'contrast(1.1) saturate(1.12)', transition: 'zoom',
  },
  paper: {
    theme: 'light', bg: ['#f5efe3', '#e7dcc8'], ink: '#1d1b17', accent: '#bf3f2b', accent2: '#8a5a2b',
    font: 'playfair', grade: 'contrast(1.03) saturate(0.88) sepia(0.08)', transition: 'dissolve',
  },
};

export function buildTimeline({ root, story, timings, fps = 30 }) {
  const base = typeof story.style === 'string' ? story.style : story.style?.base || 'documentary';
  if (!STYLES[base]) die(`unknown style "${base}" (${Object.keys(STYLES).join(', ')})`);
  const over = typeof story.style === 'object' ? story.style : {};
  const font = story.font || over.font || STYLES[base].font;
  if (!FONTS[font]) die(`unknown font "${font}" (${FONT_NAMES.join(', ')})`);
  const style = { ...STYLES[base], ...FONTS[font], ...over, font, name: base };
  const credits = fs.existsSync(path.join(root, 'assets', 'credits.json')) ? JSON.parse(fs.readFileSync(path.join(root, 'assets', 'credits.json'), 'utf8')) : {};
  const used = [];

  // "assets/ship.jpg" -> a file URL, checked, with its credit attached
  const image = (rel, where) => {
    if (!rel) return null;
    const file = path.resolve(root, rel);
    if (!fs.existsSync(file)) die(`${where}: image not found: ${rel}`);
    const key = path.basename(file);
    const credit = credits[key];
    if (!credit) die(`${where}: ${rel} has no entry in assets/credits.json. Fetch it with images.mjs get, or register it with images.mjs add, so its licence and author are on record.`);
    if (!used.find((u) => u.file === key)) used.push({ file: key, ...credit });
    return { url: pathToFileURL(file).href, path: file, credit: `${credit.author && credit.author !== 'unknown' ? credit.author + ' · ' : ''}${credit.license}` };
  };

  const beats = [];
  const sentences = [];
  const chapters = [];
  const sfx = [];
  let T = 0;
  let imageCount = 0;
  let chapterNo = 0;

  story.beats.forEach((beat, idx) => {
    const said = timings?.scenes?.[beat.id] || [];
    if (said.length !== beat.say.length) die(`narration is stale for beat "${beat.id}": run narrate.mjs again`);
    const shot = { ...beat.shot };
    const where = `beat "${beat.id}"`;
    const t0 = T;
    const lead = beat.lead ?? (idx === 0 ? 0.7 : shot.type === 'chapter' || shot.type === 'title' ? 0.5 : 0.22);
    const tail = beat.tail ?? (shot.type === 'chapter' ? 0.5 : idx === story.beats.length - 1 ? 1.4 : 0.3);

    // sentences back to back; each start is a cue that reveals can hang on
    const cues = [];
    let t = t0 + lead;
    said.forEach((s, i) => {
      cues.push(t);
      sentences.push({ beat: beat.id, t0: t, t1: t + s.dur, text: s.text, file: s.file ? path.join(root, s.file) : null });
      t += s.dur + GAP;
    });
    const spoken = said.length ? t - GAP : t0;
    T = Math.max(spoken + tail, t0 + (beat.min ?? MIN[shot.type]));

    // images
    if (shot.image) shot.image = image(shot.image, where);
    if (shot.type === 'clip') {
      if (!shot.clip) die(`${where}: a clip shot needs "clip": "assets/name.mp4"`);
      shot.clip = image(shot.clip, where);
      shot.speed = shot.speed ?? 1;
      shot.start = shot.start ?? 0;
    }
    if (shot.bg) shot.bg = image(shot.bg, where);
    for (const side of ['left', 'right']) if (shot[side]?.image) shot[side] = { ...shot[side], image: image(shot[side].image, where) };
    if (shot.type === 'image') {
      if (!shot.image) die(`${where}: an image shot needs "image"`);
      // vary the camera so consecutive photographs do not all move the same way
      if (!shot.move) shot.move = ['in', 'right', 'out', 'left'][imageCount % 4];
      imageCount++;
    }
    if (shot.type === 'chart' && !(shot.data || []).length) die(`${where}: a chart needs "data": [{ "label", "value" }]`);
    if (shot.type === 'chapter') {
      chapterNo++;
      shot.number = shot.number ?? String(chapterNo).padStart(2, '0');
    }
    if (beat.chapter || shot.type === 'chapter') chapters.push({ t: t0, title: beat.chapter || shot.title });
    else if (idx === 0) chapters.push({ t: 0, title: 'Intro', auto: true });

    let transition = beat.transition || (shot.type === 'chapter' || shot.type === 'outro' ? 'dip' : idx === 0 ? 'cut' : style.transition);
    if (!TRANSITIONS.includes(transition)) die(`${where}: unknown transition "${transition}" (${TRANSITIONS.join(', ')})`);
    if (idx === 0) transition = 'cut';
    if (idx > 0 && transition !== 'cut' && transition !== 'dissolve') sfx.push({ t: Math.max(0, t0 - 0.25), kind: 'whoosh' });

    beats.push({ id: beat.id, index: idx, t0, t1: T, cues, transition, transitionTime: beat.transitionTime ?? TIME[transition] ?? 0, shot });
  });


  return {
    name: story.name || 'story',
    title: story.title || story.name || 'Untitled',
    fps, width: 1920, height: 1080,
    duration: +T.toFixed(3),
    style,
    voiceNote: story.voiceNote !== false,
    voiceEngine: story.voice?.engine || 'kokoro',
    look: { captions: !!story.captions, grain: story.grain !== false, letterbox: !!story.letterbox, progress: story.progress !== false, credits: story.credits || 'onscreen' },
    beats, sentences, chapters,
    sfx: story.sfx === false ? [] : sfx,
    used,
  };
}

// Moments worth a look in the draft: each beat settled, and the middle of each sentence.
export function checkpoints(tl) {
  const pts = [];
  for (const b of tl.beats) {
    pts.push({ t: b.t1 - 0.12, label: `${b.id} · ${b.shot.type} · end` });
    b.cues.forEach((c, i) => {
      const s = tl.sentences.find((x) => x.beat === b.id && Math.abs(x.t0 - c) < 1e-6);
      if (s) pts.push({ t: (s.t0 + s.t1) / 2, label: `${b.id} · “${s.text.slice(0, 40)}${s.text.length > 40 ? '…' : ''}”` });
    });
    if (!b.cues.length) pts.push({ t: (b.t0 + b.t1) / 2, label: `${b.id} · ${b.shot.type}` });
  }
  pts.sort((a, b) => a.t - b.t);
  const out = [];
  for (const p of pts) {
    if (out.length && p.t - out[out.length - 1].t < 0.5) continue;
    out.push(p);
  }
  return out;
}

const stamp = (t, sep) => {
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  const ms = Math.round((t % 1) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}${sep}${String(ms).padStart(3, '0')}`;
};

export function srt(tl) {
  return tl.sentences.map((s, i) => `${i + 1}\n${stamp(s.t0, ',')} --> ${stamp(s.t1 + 0.15, ',')}\n${s.text}\n`).join('\n');
}

// The text to paste under the video: summary, chapters, sources, image credits.
export function description(tl, story) {
  const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
  const out = [];
  if (story.summary) out.push(story.summary, '');
  // YouTube wants the first chapter at 0:00, at least three, each ten seconds or longer
  const listed = tl.chapters.filter((c, i, all) => i === 0 || c.t - all[i - 1].t >= 10);
  if (listed.length >= 3) out.push('Chapters', ...listed.map((c) => `${mmss(c.t)} ${c.title}`), '');
  if ((story.sources || []).length) out.push('Sources', ...story.sources.map((s) => (typeof s === 'string' ? `- ${s}` : `- ${s.title}${s.publisher ? ', ' + s.publisher : ''}${s.url ? ' ' + s.url : ''}`)), '');
  if (tl.used.length) out.push('Images and footage', ...tl.used.map((u) => `- "${u.title}"${u.author && u.author !== 'unknown' ? ' by ' + u.author : ''}, ${u.license}${u.licenseUrl ? ' (' + u.licenseUrl + ')' : ''}. ${u.source}`), '');
  if (tl.voiceNote && tl.voiceEngine !== 'none') out.push(`Narration is a synthetic voice (${{ elevenlabs: 'ElevenLabs', say: 'macOS' }[tl.voiceEngine] || 'Kokoro-82M'}).`);
  return out.join('\n').trim() + '\n';
}
