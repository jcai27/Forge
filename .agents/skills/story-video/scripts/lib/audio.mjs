// A small audio bench: read WAVs, lay narration and interface sounds on one
// track, write it out. Music is mixed (and ducked under the voice) by ffmpeg.
import fs from 'node:fs';

export const RATE = 48000;

export function readWav(file) {
  const b = fs.readFileSync(file);
  if (b.toString('ascii', 0, 4) !== 'RIFF') throw new Error(`${file} is not a WAV`);
  let off = 12;
  let fmt = null;
  let data = null;
  while (off + 8 <= b.length) {
    const id = b.toString('ascii', off, off + 4);
    const size = b.readUInt32LE(off + 4);
    if (id === 'fmt ') fmt = { tag: b.readUInt16LE(off + 8), ch: b.readUInt16LE(off + 10), rate: b.readUInt32LE(off + 12), bits: b.readUInt16LE(off + 22) };
    if (id === 'data') data = b.subarray(off + 8, Math.min(b.length, off + 8 + size));
    off += 8 + size + (size % 2);
  }
  if (!fmt || !data) throw new Error(`${file}: no audio data`);
  const bytes = fmt.bits / 8;
  const n = Math.floor(data.length / bytes / fmt.ch);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let v = 0;
    for (let c = 0; c < fmt.ch; c++) {
      const o = (i * fmt.ch + c) * bytes;
      if (fmt.tag === 3 && fmt.bits === 32) v += data.readFloatLE(o);
      else if (fmt.bits === 16) v += data.readInt16LE(o) / 32768;
      else if (fmt.bits === 24) v += data.readIntLE(o, 3) / 8388608;
      else if (fmt.bits === 32) v += data.readInt32LE(o) / 2147483648;
      else throw new Error(`${file}: unsupported WAV format`);
    }
    out[i] = v / fmt.ch;
  }
  return { samples: out, rate: fmt.rate };
}

export function resample({ samples, rate }, to = RATE) {
  if (rate === to) return samples;
  const n = Math.floor((samples.length * to) / rate);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i * rate) / to;
    const j = Math.floor(x);
    const f = x - j;
    out[i] = samples[j] * (1 - f) + (samples[Math.min(j + 1, samples.length - 1)] || 0) * f;
  }
  return out;
}

export function writeWav(file, samples, rate = RATE) {
  const b = Buffer.alloc(44 + samples.length * 2);
  b.write('RIFF', 0);
  b.writeUInt32LE(36 + samples.length * 2, 4);
  b.write('WAVEfmt ', 8);
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(rate, 24);
  b.writeUInt32LE(rate * 2, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write('data', 36);
  b.writeUInt32LE(samples.length * 2, 40);
  for (let i = 0; i < samples.length; i++) b.writeInt16LE(Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), 44 + i * 2);
  fs.writeFileSync(file, b);
}

// Trim silence from both ends so sentence timing is the speech, not the padding.
export function trim(samples, rate, floor = 0.004) {
  let a = 0;
  let z = samples.length - 1;
  while (a < z && Math.abs(samples[a]) < floor) a++;
  while (z > a && Math.abs(samples[z]) < floor) z--;
  const pad = Math.round(rate * 0.04);
  return samples.subarray(Math.max(0, a - pad), Math.min(samples.length, z + pad));
}

// ---- interface sounds, synthesised so the skill ships no audio files -------
let seed = 99;
const noise = () => ((seed = (seed * 16807) % 2147483647) / 2147483647) * 2 - 1;

function click() {
  const n = Math.round(RATE * 0.05);
  const out = new Float32Array(n);
  let lp = 0;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    lp += 0.35 * (noise() - lp);
    out[i] = (lp * Math.exp(-t * 160) + Math.sin(2 * Math.PI * 190 * t) * Math.exp(-t * 90) * 0.7) * 0.5;
  }
  return out;
}

function key() {
  const n = Math.round(RATE * 0.03);
  const out = new Float32Array(n);
  let lp = 0;
  const pitch = 1500 + noise() * 250;
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    lp += 0.6 * (noise() - lp);
    out[i] = (lp * 0.6 + Math.sin(2 * Math.PI * pitch * t) * 0.25) * Math.exp(-t * 260) * 0.22;
  }
  return out;
}

function whoosh() {
  const n = Math.round(RATE * 0.5);
  const out = new Float32Array(n);
  let lp = 0;
  for (let i = 0; i < n; i++) {
    const u = i / n;
    lp += (0.02 + 0.1 * u) * (noise() - lp);
    out[i] = lp * Math.sin(Math.PI * u) ** 2 * 0.3;
  }
  return out;
}

function pop() {
  const n = Math.round(RATE * 0.09);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / RATE;
    out[i] = Math.sin(2 * Math.PI * (620 + 900 * t * 8) * t) * Math.exp(-t * 55) * 0.16;
  }
  return out;
}

const SFX = { click, key, whoosh, pop };

export function mixTrack({ duration, sentences, sfx, sfxGain = 1 }) {
  const track = new Float32Array(Math.ceil((duration + 0.2) * RATE));
  const add = (buf, t, gain = 1) => {
    const o = Math.round(t * RATE);
    for (let i = 0; i < buf.length && o + i < track.length; i++) if (o + i >= 0) track[o + i] += buf[i] * gain;
  };
  for (const s of sentences) if (s.file) add(resample(readWav(s.file)), s.t0, 1);
  for (const e of sfx) add(SFX[e.kind](), e.t, sfxGain);
  return track;
}
