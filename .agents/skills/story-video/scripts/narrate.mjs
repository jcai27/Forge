#!/usr/bin/env node
// Voice every "say" sentence in story.json and time it.
// Engines: kokoro (Kokoro-82M, on this machine), elevenlabs (Eleven v3, hosted:
// the narration text is sent to ElevenLabs), say (macOS), none (captions only).
// Sentences are cached by content, so a re-run only voices what changed.
//
//   node narrate.mjs PROJECT [--engine kokoro|elevenlabs|say|none] [--voice af_heart]
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { parseArgs, loadProject, writeJson, dep, run, ffmpegPath, die, HOME, keepAwake, sleep } from './lib/common.mjs';
keepAwake();
import { readWav, writeWav, trim } from './lib/audio.mjs';

const { pos, flags } = parseArgs(process.argv.slice(2));
if (!pos[0]) die('usage: narrate.mjs PROJECT [--engine kokoro|elevenlabs|say|none] [--voice NAME]');
const { root, demo } = loadProject(pos[0]);
const voice = { engine: 'kokoro', voice: 'af_heart', speed: 1, ...(demo.voice || {}) };
if (flags.engine) voice.engine = flags.engine;
if (flags.voice) voice.voice = flags.voice;
if (voice.engine === 'say' && !demo.voice?.voice && !flags.voice) voice.voice = 'Samantha';
if (voice.engine === 'elevenlabs') {
  if (!/^[A-Za-z0-9]{20}$/.test(voice.voice)) voice.voice = 'JBFqnCBsd6RMkjVDRZzb'; // George, a premade storyteller voice
  voice.model = voice.model || 'eleven_v3';
  voice.stability = voice.stability ?? 0.5;
}
const dir = path.join(root, 'audio');
fs.mkdirSync(dir, { recursive: true });

let tts = null;
async function kokoro(text, file) {
  if (!tts) {
    const { KokoroTTS } = await dep('kokoro-js');
    process.stdout.write('  loading Kokoro-82M (first run downloads about 90 MB)...\n');
    tts = await KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', { dtype: voice.dtype || 'q8', device: 'cpu' });
    fs.writeFileSync(path.join(HOME, '.kokoro-ok'), '');
  }
  const audio = await tts.generate(text, { voice: voice.voice, speed: voice.speed });
  writeWav(file, trim(audio.audio, audio.sampling_rate), audio.sampling_rate);
}

async function macSay(text, file) {
  const aiff = file.replace(/\.wav$/, '.aiff');
  await run('say', ['-v', voice.voice, '-r', String(Math.round(175 * voice.speed)), '-o', aiff, text]);
  await run(ffmpegPath(), ['-y', '-i', aiff, '-ac', '1', '-ar', '24000', file]);
  fs.rmSync(aiff, { force: true });
  const w = readWav(file);
  writeWav(file, trim(w.samples, w.rate), w.rate);
}

// ElevenLabs: a whole beat goes in one request, so the voice carries its
// intonation from sentence to sentence, and the character timestamps that come
// back say where to cut it into sentences again.
const ELEVEN = (process.env.ELEVENLABS_BASE_URL || 'https://api.elevenlabs.io').replace(/\/$/, '');
const ELEVEN_RATE = 24000;
async function elevenCall(text) {
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) die('the ElevenLabs voice needs an API key: set ELEVENLABS_API_KEY (for Videor Studio, put ELEVENLABS_API_KEY=... in a .env file beside package.json and restart it)');
  const settings = { stability: voice.stability };
  if (voice.speed !== 1) settings.speed = Math.min(1.2, Math.max(0.7, voice.speed));
  for (let attempt = 0; ; attempt++) {
    let r;
    try {
      r = await fetch(`${ELEVEN}/v1/text-to-speech/${encodeURIComponent(voice.voice)}/with-timestamps?output_format=pcm_${ELEVEN_RATE}`, {
        method: 'POST',
        headers: { 'xi-api-key': key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, model_id: voice.model, voice_settings: settings }),
      });
    } catch (e) {
      if (attempt < 3) { await sleep(1500 * (attempt + 1)); continue; }
      die(`could not reach ElevenLabs: ${e.message}`);
    }
    if ((r.status === 429 || r.status >= 500) && attempt < 3) { await sleep(2000 * (attempt + 1)); continue; }
    if (!r.ok) {
      let why = '';
      try {
        const d = (await r.json()).detail;
        why = typeof d === 'string' ? d : d?.message || JSON.stringify(d);
      } catch {}
      die(`ElevenLabs answered ${r.status}${r.status === 401 ? ' (the API key was not accepted)' : ''}${why ? ': ' + String(why).slice(0, 300) : ''}`);
    }
    const j = await r.json();
    const pcm = Buffer.from(j.audio_base64 || '', 'base64');
    const samples = new Float32Array(pcm.length >> 1);
    for (let i = 0; i < samples.length; i++) samples[i] = pcm.readInt16LE(i * 2) / 32768;
    if (!samples.length) die('ElevenLabs returned no audio');
    return { samples, alignment: j.alignment };
  }
}
// Where each sentence ends in the audio, from the timestamps; null if they cannot be trusted.
function sentenceCuts(texts, al, seconds) {
  const chars = al?.characters;
  if (!chars || chars.join('') !== texts.join(' ')) return null;
  const at = []; // string offset -> index into the alignment lists
  chars.forEach((c, k) => { for (let i = 0; i < c.length; i++) at.push(k); });
  const cuts = [];
  let off = 0;
  for (const t of texts.slice(0, -1)) {
    off += t.length; // the space after this sentence
    const k = at[off];
    const cut = (al.character_end_times_seconds[k - 1] + al.character_start_times_seconds[k + 1]) / 2;
    if (!(cut > (cuts.at(-1) ?? 0) && cut < seconds)) return null;
    cuts.push(cut);
    off += 1;
  }
  return cuts;
}
async function eleven(texts) {
  const { samples, alignment } = await elevenCall(texts.join(' '));
  if (texts.length === 1) return [samples];
  const cuts = sentenceCuts(texts, alignment, samples.length / ELEVEN_RATE);
  if (!cuts) {
    console.log('  note: no usable timestamps came back for a beat; voicing its sentences one at a time');
    const out = [];
    for (const t of texts) out.push((await elevenCall(t)).samples);
    return out;
  }
  const edges = [0, ...cuts.map((c) => Math.round(c * ELEVEN_RATE)), samples.length];
  return texts.map((_, i) => samples.subarray(edges[i], edges[i + 1]));
}

const timings = {};
let total = 0;
let made = 0;
for (const scene of demo.scenes) {
  timings[scene.id] = [];
  const hosted = voice.engine === 'elevenlabs';
  // a hosted beat is voiced as one piece, so a change to any sentence in it revoices the beat
  const basis = hosted ? [voice.engine, voice.voice, voice.model, voice.stability, voice.speed, scene.say.map((s) => s.speak)] : null;
  const fileOf = (s, i) => path.join(dir, `${crypto.createHash('sha1').update(JSON.stringify(hosted ? [...basis, i] : [voice.engine, voice.voice, voice.speed, s.speak])).digest('hex').slice(0, 12)}.wav`);
  if (hosted && scene.say.length && scene.say.some((s, i) => !fs.existsSync(fileOf(s, i)))) {
    const parts = await eleven(scene.say.map((s) => s.speak));
    parts.forEach((p, i) => writeWav(fileOf(scene.say[i], i), trim(p, ELEVEN_RATE), ELEVEN_RATE));
    made += parts.length;
  }
  for (const [i, s] of scene.say.entries()) {
    if (voice.engine === 'none') {
      // No voice: give each line the time it takes to read on screen.
      const dur = Math.max(1.4, s.text.split(/\s+/).length / 2.6 + 0.4);
      timings[scene.id].push({ text: s.text, file: null, dur: +dur.toFixed(2) });
      total += dur;
      continue;
    }
    const file = fileOf(s, i);
    if (!fs.existsSync(file)) {
      if (voice.engine === 'kokoro') await kokoro(s.speak, file);
      else if (voice.engine === 'say') await macSay(s.speak, file);
      else die(`unknown voice engine "${voice.engine}" (kokoro, elevenlabs, say, none)`);
      made++;
    }
    const w = readWav(file);
    const dur = w.samples.length / w.rate;
    timings[scene.id].push({ text: s.text, file: `audio/${path.basename(file)}`, dur: +dur.toFixed(3) });
    total += dur;
  }
}
writeJson(path.join(dir, 'timings.json'), { voice, scenes: timings });
console.log(`narration: ${Object.values(timings).flat().length} sentence(s), ${total.toFixed(1)}s of speech, ${made} newly voiced (${voice.engine})`);
