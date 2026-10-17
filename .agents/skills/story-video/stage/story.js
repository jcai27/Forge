// The storytelling compositor. init(timeline) builds every beat's picture once;
// renderAt(t) sets all styles as a pure function of t, so render.mjs can step
// it frame by frame. Nothing here moves on its own clock.
(() => {
  const $ = (s) => document.querySelector(s);
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, u) => a + (b - a) * u;
  const outCubic = (u) => 1 - Math.pow(1 - clamp(u), 3);
  const inCubic = (u) => Math.pow(clamp(u), 3);
  const outExpo = (u) => ((u = clamp(u)) >= 1 ? 1 : 1 - Math.pow(2, -10 * u));
  const smooth = (u) => ((u = clamp(u)), u * u * (3 - 2 * u));
  const inOut = (u) => ((u = clamp(u)) < 0.5 ? 16 * u ** 5 : 1 - Math.pow(-2 * u + 2, 5) / 2);
  const outBack = (u) => {
    u = clamp(u);
    const c = 1.4;
    return 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2);
  };
  const el = (tag, cls, parent, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  };

  let TL = null;
  const drawers = []; // one per beat: { b, root, anim, ready }
  let pending = []; // footage frames still decoding for the moment being drawn

  // ---- text ----------------------------------------------------------------
  // "*starred*" words take the accent. chars=true: each word is a mask its letters rise from.
  function words(text, parent, chars = false) {
    const spans = [];
    let hi = false;
    for (const part of String(text).split(/(\*)/)) {
      if (part === '*') {
        hi = !hi;
        continue;
      }
      for (const w of part.split(/(\s+)/)) {
        if (!w) continue;
        if (/^\s+$/.test(w)) {
          parent.appendChild(document.createTextNode(' '));
          continue;
        }
        if (chars) {
          const mask = el('span', 'mw', parent);
          for (const ch of w) spans.push(el('span', 'c' + (hi ? ' hi' : ''), mask, ch));
        } else spans.push(el('span', 'w' + (hi ? ' hi' : ''), parent, w));
      }
    }
    return spans;
  }
  function rise(spans, t, start, stagger = 0.07, dur = 0.6) {
    spans.forEach((s, i) => {
      const p = outCubic((t - start - i * stagger) / dur);
      s.style.opacity = p;
      s.style.transform = `translateY(${(1 - p) * 0.4}em)`;
      s.style.filter = p < 1 ? `blur(${(1 - p) * 7}px)` : 'none';
    });
  }
  function reveal(spans, t, start, stagger = 0.035, dur = 0.8) {
    spans.forEach((s, i) => {
      const p = outExpo((t - start - i * stagger) / dur);
      s.style.opacity = clamp(p * 3);
      s.style.transform = `translateY(${(1 - p) * 110}%) rotate(${(1 - p) * 6}deg)`;
    });
  }
  function fadeUp(e, t, start, dur = 0.6, dy = 30) {
    const p = outExpo((t - start) / dur);
    e.style.opacity = clamp(((t - start) / dur) * 2.5);
    e.style.transform = `translateY(${(1 - p) * dy}px)`;
  }
  const fitFont = (text, max, min, budget) => Math.round(clamp(budget / Math.sqrt(String(text).replace(/\*/g, '').length), min, max));
  // when item i of n should appear: its own "at" (a sentence number), else that sentence, else spread across the beat
  function when(b, item, i, n) {
    const k = item && item.at != null ? item.at : i;
    if (b.cues[k] != null && (item?.at != null || b.cues.length >= n)) return b.cues[k];
    const a = (b.cues[0] ?? b.t0) + 0.25;
    return lerp(a, Math.max(a, b.t1 - 1.2), n > 1 ? i / (n - 1) : 0);
  }
  const fmt = (v, d = 0) => Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

  // ---- shots ---------------------------------------------------------------
  const build = {};

  function backdrop(b, root) {
    if (!b.shot.bg) return null;
    const f = el('div', 'fill', root);
    el('img', '', f).src = b.shot.bg.url;
    f.style.filter = 'brightness(.38) saturate(.7)';
    // words over a darkened photograph are light, whatever the look
    for (const [k, v] of [['--ink', '#f7f3ea'], ['--mute', 'rgba(247,243,234,.72)'], ['--faint', 'rgba(247,243,234,.2)']]) root.style.setProperty(k, v);
    root.style.color = '#f7f3ea';
    return (t) => (f.style.transform = `scale(${lerp(1.06, 1.14, (t - b.t0) / (b.t1 - b.t0))})`);
  }

  build.title = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const k = s.kicker ? el('div', 'kicker', c, s.kicker) : null;
    const title = el('div', 'display title', c);
    title.style.fontSize = fitFont(s.title, 170, 84, 660) + 'px';
    const sp = words(s.title, title, true);
    const rule = el('div', 'rule', c);
    const sub = s.subtitle ? el('div', 'sub', c) : null;
    const ss = sub ? words(s.subtitle, sub) : [];
    return (t) => {
      bd?.(t);
      if (k) {
        const p = outExpo((t - b.t0 - 0.15) / 1.2);
        k.style.opacity = clamp(p * 1.5);
        k.style.letterSpacing = lerp(0.7, 0.26, p) + 'em';
      }
      reveal(sp, t, b.t0 + 0.3, Math.min(0.045, 0.6 / sp.length));
      const p = outExpo((t - b.t0 - 0.9) / 0.9);
      rule.style.transform = `scaleX(${p})`;
      rise(ss, t, b.t0 + 1.0, 0.05);
    };
  };

  build.chapter = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const num = el('div', 'chapnum', c, s.number);
    const title = el('div', 'display chaptitle', c);
    title.style.fontSize = fitFont(s.title, 120, 64, 520) + 'px';
    const sp = words(s.title, title, true);
    return (t) => {
      bd?.(t);
      const p = outExpo((t - b.t0 - 0.1) / 1.0);
      num.style.opacity = clamp(p * 2) * 0.9;
      num.style.transform = `translateY(${(1 - p) * 60}px) scale(${lerp(1.15, 1, p)})`;
      reveal(sp, t, b.t0 + 0.35, Math.min(0.04, 0.5 / sp.length));
    };
  };

  build.outro = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const title = el('div', 'display title', c);
    title.style.fontSize = fitFont(s.title, 130, 70, 600) + 'px';
    const sp = words(s.title, title, true);
    const sub = s.subtitle ? el('div', 'sub', c) : null;
    const ss = sub ? words(s.subtitle, sub) : [];
    const cta = s.cta ? el('div', 'cta', c, s.cta) : null;
    const note = s.note ? el('div', 'note', root, s.note) : null;
    return (t) => {
      bd?.(t);
      reveal(sp, t, b.t0 + 0.25, Math.min(0.04, 0.6 / sp.length));
      rise(ss, t, b.t0 + 0.9, 0.05);
      if (cta) fadeUp(cta, t, b.t0 + 1.3);
      if (note) note.style.opacity = clamp((t - b.t0 - 1.8) / 0.6);
    };
  };

  build.image = (b, root) => {
    const s = b.shot;
    const blur = el('div', 'blurbg', root);
    const bimg = el('img', '', blur);
    const fill = el('div', 'fill', root);
    const img = el('img', '', fill);
    const card = el('div', 'card', root);
    const cimg = el('img', '', card);
    for (const i of [bimg, img, cimg]) i.src = s.image.url;
    const mark = s.highlight ? el('div', 'mark', card) : null;
    const scrim = el('div', 'scrim', root);
    let lower = null, bar = null, label = null, cap = null;
    if (s.caption || s.label) {
      lower = el('div', 'lower', root);
      bar = el('div', 'bar', lower);
      const col = el('div', '', lower);
      if (s.label) label = el('div', 'label', col, s.label);
      if (s.caption) cap = el('div', 'cap', col, s.caption);
    } else scrim.style.display = 'none';
    const credit = TL.look.credits === 'onscreen' ? el('div', 'credit', root, s.image.credit) : null;
    let carded = false;
    const moves = { in: [1.03, 1.15, 0, 0, 0, 0], out: [1.15, 1.03, 0, 0, 0, 0], left: [1.13, 1.13, 2.6, -2.6, 0, 0], right: [1.13, 1.13, -2.6, 2.6, 0, 0], up: [1.13, 1.13, 0, 0, 2.4, -2.4], down: [1.13, 1.13, 0, 0, -2.4, 2.4], still: [1.02, 1.02, 0, 0, 0, 0] };
    const mv = moves[s.move] || moves.in;
    const ready = () => {
      const ar = img.naturalWidth / img.naturalHeight || 1.78;
      // portraits, diagrams and screenshots sit on a card over a blurred copy; wide photographs fill the frame
      carded = s.fit ? s.fit === 'contain' : ar < 1.3 || s.frame === 'card' || !!s.highlight;
      fill.style.display = carded ? 'none' : 'block';
      card.style.display = blur.style.display = carded ? 'block' : 'none';
      if (carded) {
        const k = Math.min(1500 / img.naturalWidth, 800 / img.naturalHeight);
        card.style.width = img.naturalWidth * k + 'px';
        card.style.height = img.naturalHeight * k + 'px';
        if (mark) {
          const [x, y, w, h] = s.highlight;
          Object.assign(mark.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: h * 100 + '%' });
        }
      }
      if (s.focus) {
        fill.style.transformOrigin = `${s.focus[0] * 100}% ${s.focus[1] * 100}%`;
        // a cropped photograph is cropped round the focus, not round its middle
        const vx = Math.min(1, (1920 / 1080) / ar), vy = Math.min(1, ar / (1920 / 1080));
        const pos = (f, v) => (v >= 1 ? 50 : clamp((f - v / 2) / (1 - v)) * 100);
        img.style.objectPosition = `${pos(s.focus[0], vx)}% ${pos(s.focus[1], vy)}%`;
      }
    };
    return Object.assign((t) => {
      const u = clamp((t - b.t0 + 0.4) / (b.t1 - b.t0 + 0.8)); // keeps moving through the transitions either side
      if (carded) {
        blur.style.transform = `scale(${lerp(1.0, 1.08, u)})`;
        const p = outExpo((t - b.t0 + 0.2) / 1.1);
        card.style.transform = `translate(-50%, -50%) translateY(${(1 - p) * 40}px) scale(${lerp(0.97, 1.03, u)}) rotate(${s.frame === 'card' ? -1.2 : 0}deg)`;
        if (mark) {
          const m = outExpo((t - when(b, { at: s.highlightAt }, 0, 1) - 0.3) / 0.6);
          mark.style.opacity = clamp(m * 2);
          mark.style.transform = `scale(${lerp(1.12, 1, m)})`;
        }
      } else fill.style.transform = `scale(${lerp(mv[0], mv[1], u)}) translate(${lerp(mv[2], mv[3], u)}%, ${lerp(mv[4], mv[5], u)}%)`;
      if (lower) {
        const start = b.t0 + 0.45;
        bar.style.transform = `scaleY(${outExpo((t - start) / 0.5)})`;
        if (label) fadeUp(label, t, start + 0.1, 0.6, 16);
        if (cap) fadeUp(cap, t, start + 0.2, 0.7, 22);
      }
      if (credit) credit.style.opacity = clamp((t - b.t0 - 0.3) / 0.5) * 0.9;
    }, { ready });
  };

  // Footage, full frame. render.mjs has cut it into stills; this shows the one for time t.
  build.clip = (b, root) => {
    const s = b.shot;
    const fill = el('div', 'fill', root);
    const img = el('img', '', fill);
    const scrim = el('div', 'scrim', root);
    let lower = null, bar = null, label = null, cap = null;
    if (s.caption || s.label) {
      lower = el('div', 'lower', root);
      bar = el('div', 'bar', lower);
      const col = el('div', '', lower);
      if (s.label) label = el('div', 'label', col, s.label);
      if (s.caption) cap = el('div', 'cap', col, s.caption);
    } else scrim.style.display = 'none';
    const credit = TL.look.credits === 'onscreen' ? el('div', 'credit', root, s.clip.credit) : null;
    let shown = -1;
    return (t) => {
      // starts a moment early so it is already moving as the transition brings it in
      const i = clamp(Math.floor((t - b.t0 + 0.4) * 30 * s.speed), 0, s.frames.count - 1);
      if (i !== shown) {
        shown = i;
        img.src = s.frames.base + String(i + 1).padStart(5, '0') + '.jpg';
        pending.push(img.decode().catch(() => {}));
      }
      fill.style.transform = `scale(${lerp(1.0, 1.04, clamp((t - b.t0) / (b.t1 - b.t0)))})`;
      if (lower) {
        const start = b.t0 + 0.45;
        bar.style.transform = `scaleY(${outExpo((t - start) / 0.5)})`;
        if (label) fadeUp(label, t, start + 0.1, 0.6, 16);
        if (cap) fadeUp(cap, t, start + 0.2, 0.7, 22);
      }
      if (credit) credit.style.opacity = clamp((t - b.t0 - 0.3) / 0.5) * 0.9;
    };
  };

  build.quote = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const wrap = el('div', 'quote', root);
    let portrait = null;
    if (s.image) {
      portrait = el('div', 'portrait', wrap);
      el('img', '', portrait).src = s.image.url;
    }
    const col = el('div', '', wrap);
    const qm = el('div', 'qmark', col, '“');
    const q = el('div', 'qtext', col);
    q.style.fontSize = fitFont(s.text, 86, 44, s.image ? 760 : 900) + 'px';
    q.style.maxWidth = (s.image ? 1020 : 1400) + 'px';
    const sp = words(s.text, q);
    const by = el('div', 'qby', col);
    by.textContent = s.by ? '— ' + s.by : '';
    if (s.role) el('span', '', by, ', ' + s.role);
    const note = s.source ? el('div', 'note', root, s.source) : null;
    return (t) => {
      bd?.(t);
      if (portrait) {
        fadeUp(portrait, t, b.t0 + 0.1, 0.9, 40);
        portrait.firstChild.style.transform = `scale(${lerp(1.04, 1.12, (t - b.t0) / (b.t1 - b.t0))})`;
      }
      fadeUp(qm, t, b.t0 + 0.15, 0.6, 20);
      // the words arrive at reading pace across the spoken line
      const span = Math.max(1, Math.min(b.t1 - b.t0 - 1.6, sp.length * 0.16));
      rise(sp, t, (b.cues[0] ?? b.t0) + 0.1, span / sp.length, 0.5);
      fadeUp(by, t, (b.cues[0] ?? b.t0) + span + 0.3, 0.6, 16);
      if (note) note.style.opacity = clamp((t - b.t0 - 1) / 0.6);
    };
  };

  build.stat = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const head = s.title ? el('div', 'kicker', c, s.title) : null;
    const row = el('div', 'stats', c);
    const items = s.items || [s];
    const parts = items.map((it) => {
      const box = el('div', 'stat', row);
      const num = el('div', 'num', box);
      // as large as the longest figure allows
      const longest = Math.max(...items.map((x) => ((x.prefix || '') + fmt(x.value, x.decimals || 0) + (x.suffix || '')).length));
      num.style.fontSize = Math.round(Math.min(items.length === 1 ? 320 : items.length === 2 ? 230 : 170, 1500 / items.length / (longest * 0.6))) + 'px';
      const label = el('div', 'statlabel', box, it.label || '');
      return { it, box, num, label };
    });
    const note = s.source ? el('div', 'note', root, s.source) : null;
    return (t) => {
      bd?.(t);
      if (head) fadeUp(head, t, b.t0 + 0.1);
      parts.forEach(({ it, box, num, label }, i) => {
        const start = when(b, it, i, parts.length) + 0.05;
        const p = outExpo((t - start) / 1.4);
        // the figure counts up and lands exactly on its value
        const v = lerp(it.from ?? 0, it.value, p);
        num.textContent = (it.prefix || '') + fmt(p >= 1 ? it.value : v, it.decimals || 0) + (it.suffix || '');
        box.style.opacity = clamp((t - start) / 0.25);
        box.style.transform = `translateY(${(1 - outExpo((t - start) / 0.8)) * 40}px)`;
        fadeUp(label, t, start + 0.5, 0.6, 14);
      });
      if (note) note.style.opacity = clamp((t - b.t0 - 1) / 0.6);
    };
  };

  build.text = (b, root) => {
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const d = el('div', 'display text', c);
    d.style.fontSize = fitFont(b.shot.text, 124, 62, 760) + 'px';
    const sp = words(b.shot.text, d);
    return (t) => {
      bd?.(t);
      // "at": the sentence the words arrive on, when the line before it sets them up
      rise(sp, t, (b.cues[b.shot.at ?? 0] ?? b.t0) + 0.05, Math.min(0.12, 1.4 / sp.length), 0.6);
    };
  };

  build.list = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const box = el('div', 'list', c);
    const head = s.title ? el('div', 'display head', box, s.title) : null;
    const rows = (s.items || []).map((it, i) => {
      const item = typeof it === 'string' ? { text: it } : it;
      const r = el('div', 'li', box);
      el('b', '', r, String(i + 1).padStart(2, '0'));
      el('span', '', r, item.text);
      return { item, r };
    });
    return (t) => {
      bd?.(t);
      if (head) fadeUp(head, t, b.t0 + 0.1);
      const starts = rows.map(({ item }, i) => when(b, item, i, rows.length));
      rows.forEach(({ r }, i) => {
        const p = outExpo((t - starts[i]) / 0.7);
        const next = starts[i + 1];
        // the point being spoken is bright; the ones already made step back
        const dimmed = next != null ? lerp(1, 0.45, clamp((t - next) / 0.4)) : 1;
        r.style.opacity = clamp((t - starts[i]) / 0.3) * dimmed;
        r.style.transform = `translateX(${(1 - p) * 60}px)`;
      });
    };
  };

  build.chart = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const c = el('div', 'center', root);
    const box = el('div', 'chart', c);
    const head = s.title ? el('div', 'display head', box, s.title) : null;
    const note = s.source ? el('div', 'note', root, s.source) : null;
    const start = (b.cues[0] ?? b.t0) + 0.3;
    const val = (v) => (s.prefix || '') + fmt(v, s.decimals || 0) + (s.suffix || '');
    let draw;
    if (s.kind === 'line') {
      const W = 1500, H = 560, pad = 50;
      const vs = s.data.map((d) => d.value);
      const lo = s.min ?? Math.min(...vs), hi = s.max ?? Math.max(...vs);
      const X = (i) => pad + (i / (s.data.length - 1)) * (W - pad * 2);
      const Y = (v) => H - 70 - ((v - lo) / (hi - lo || 1)) * (H - 150);
      const ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('class', 'line');
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      box.appendChild(svg);
      const mk = (tag, attrs, text) => {
        const e = document.createElementNS(ns, tag);
        for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
        if (text != null) e.textContent = text;
        svg.appendChild(e);
        return e;
      };
      mk('line', { x1: pad, x2: W - pad, y1: H - 70, y2: H - 70, stroke: 'var(--faint)', 'stroke-width': 3 });
      const pts = s.data.map((d, i) => `${X(i)},${Y(d.value)}`).join(' ');
      const path = mk('polyline', { points: pts, fill: 'none', stroke: 'var(--accent)', 'stroke-width': 7, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
      const labels = s.data.map((d, i) => {
        const edge = i === 0 || i === s.data.length - 1 || d.mark;
        const x = mk('text', { x: X(i), y: H - 22, 'text-anchor': 'middle' }, d.label);
        const dot = edge ? mk('circle', { cx: X(i), cy: Y(d.value), r: 11, fill: 'var(--accent)' }) : null;
        const v = edge ? mk('text', { x: X(i), y: Y(d.value) - 28, 'text-anchor': i === 0 ? 'start' : i === s.data.length - 1 ? 'end' : 'middle', class: 'big' }, val(d.value)) : null;
        return { x, dot, v, u: i / (s.data.length - 1) };
      });
      draw = (t) => {
        const total = path.getTotalLength();
        const p = inOut((t - start) / 2.0);
        path.style.strokeDasharray = total;
        path.style.strokeDashoffset = total * (1 - p);
        labels.forEach(({ x, dot, v, u }) => {
          const on = clamp((p - u) * 8 + 1);
          x.style.opacity = clamp((t - b.t0 - 0.2) / 0.5);
          if (dot) dot.style.opacity = on;
          if (v) v.style.opacity = on;
        });
      };
    } else {
      const max = s.max ?? Math.max(...s.data.map((d) => d.value));
      const rows = s.data.map((d, i) => {
        const r = el('div', 'row' + (d.highlight || s.highlight === i ? ' on' : ''), box);
        el('div', 'name', r, d.label);
        const track = el('div', 'track', r);
        const bar = el('div', 'fillbar', track);
        bar.style.width = (d.value / max) * 82 + '%';
        const v = el('div', 'val', track);
        return { d, r, bar, v };
      });
      draw = (t) => rows.forEach(({ d, r, bar, v }, i) => {
        const st = start + i * 0.14;
        const p = outExpo((t - st) / 1.2);
        r.style.opacity = clamp((t - st + 0.15) / 0.3);
        bar.style.transform = `scaleX(${p})`;
        v.style.left = (d.value / max) * 82 * p + '%';
        v.textContent = val(p >= 1 ? d.value : d.value * p);
      });
    }
    return (t) => {
      bd?.(t);
      if (head) fadeUp(head, t, b.t0 + 0.1);
      draw(t);
      if (note) note.style.opacity = clamp((t - b.t0 - 1) / 0.6);
    };
  };

  build.timeline = (b, root) => {
    const s = b.shot;
    const bd = backdrop(b, root);
    const box = el('div', 'tl', root);
    const head = s.title ? el('div', 'display head', box, s.title) : null;
    const axis = el('div', 'axis', box);
    const prog = el('div', 'prog', axis);
    const n = s.events.length;
    const evs = s.events.map((e, i) => {
      const d = el('div', 'ev', box);
      const x = n > 1 ? 12 + (i / (n - 1)) * 76 : 50;
      d.style.left = x + '%';
      el('div', 'dot', d);
      const year = el('div', 'year', d, e.year);
      const what = el('div', 'what', d, e.label);
      return { e, d, x, year, what };
    });
    return (t) => {
      bd?.(t);
      if (head) fadeUp(head, t, b.t0 + 0.1);
      const starts = evs.map(({ e }, i) => when(b, e, i, n));
      // the line runs on to each date as it is spoken
      let reach = 0;
      evs.forEach(({ x }, i) => (reach = lerp(reach, x, inOut((t - starts[i] + 0.5) / 0.8))));
      prog.style.transform = `scaleX(${reach / 100})`;
      evs.forEach(({ d, year, what }, i) => {
        const p = outBack((t - starts[i]) / 0.6);
        const next = starts[i + 1];
        const live = next != null ? lerp(1, 0.5, clamp((t - next) / 0.4)) : 1;
        d.style.opacity = clamp((t - starts[i]) / 0.25);
        d.firstChild.style.transform = `scale(${p})`;
        year.style.opacity = live;
        year.style.transform = `translateX(-50%) translateY(${(1 - outExpo((t - starts[i]) / 0.6)) * 20}px) scale(${lerp(0.82, 1, live)})`;
        what.style.opacity = live * clamp((t - starts[i] - 0.15) / 0.4);
      });
    };
  };

  build.compare = (b, root) => {
    const s = b.shot;
    const grid = el('div', 'cmp', root);
    const sides = ['left', 'right'].map((k, i) => {
      const d = s[k] || {};
      const side = el('div', 'side', grid);
      let pic = null;
      if (d.image) {
        pic = el('div', 'pic', side);
        el('img', '', pic).src = d.image.url;
      }
      const tag = d.label ? el('div', 'tag', side, d.label) : null;
      const big = d.value != null ? el('div', 'big', side, String(d.value)) : null;
      const txt = d.text ? el('div', 'txt' + (d.value == null ? ' lead' : ''), side, d.text) : null;
      return { d, side, pic, tag, big, txt, i };
    });
    const divide = el('div', 'divide', root);
    return (t) => {
      sides.forEach(({ d, side, pic, tag, big, txt, i }) => {
        const st = when(b, d, i, 2);
        side.style.opacity = clamp((t - st) / 0.4);
        if (pic) pic.firstChild.style.transform = `scale(${lerp(1.04, 1.12, (t - b.t0) / (b.t1 - b.t0))})`;
        if (tag) fadeUp(tag, t, st + 0.1, 0.6, 16);
        if (big) {
          const p = outExpo((t - st - 0.15) / 0.9);
          big.style.opacity = clamp(p * 2.5);
          big.style.transform = `translateY(${(1 - p) * 50}px)`;
        }
        if (txt) fadeUp(txt, t, st + 0.35, 0.6, 16);
      });
      divide.style.transform = `scaleY(${outExpo((t - when(b, s.right, 1, 2) + 0.3) / 0.8)})`;
    };
  };

  // ---- transitions ---------------------------------------------------------
  // A boundary lasts d seconds centred on the cut. Dissolve, zoom and slide
  // overlap the two beats; dip, flash and wipe hide a hard cut at the midpoint.
  const HIDDEN = new Set(['dip', 'flash', 'wipe']);
  function plan() {
    TL.beats.forEach((b, i) => {
      const prev = TL.beats[i - 1];
      b.inB = null;
      if (!prev || b.transition === 'cut') return;
      b.inB = { type: b.transition, d: b.transitionTime, seq: HIDDEN.has(b.transition), t: b.t0 };
      prev.outB = b.inB;
    });
  }
  function phase(b, t) {
    const last = b.index === TL.beats.length - 1;
    const di = b.inB ? b.inB.d : 0;
    const dout = b.outB ? b.outB.d : 0;
    if (t < b.t0 - di / 2 - 1e-6) return null;
    if (!last && t >= b.t1 + dout / 2 - 1e-6) return null;
    const ph = { inP: 1, outP: 0, inType: b.inB?.type, outType: b.outB?.type };
    if (b.index === 0) {
      ph.inP = clamp((t - b.t0) / 1.0);
      ph.inType = 'dissolve';
    } else if (b.inB) {
      const p = (t - (b.t0 - di / 2)) / di;
      if (b.inB.seq) {
        if (p < 0.5) return null;
      } else ph.inP = clamp(p);
    }
    if (b.outB) {
      const p = (t - (b.t1 - dout / 2)) / dout;
      if (p > 0) {
        if (b.outB.seq) {
          if (p >= 0.5) return null;
        } else ph.outP = clamp(p);
      }
    }
    return ph;
  }
  function pose(ph) {
    const o = { op: 1, sc: 1, tx: 0, bl: 0 };
    if (ph.inP < 1) {
      const e = outExpo(ph.inP);
      if (ph.inType === 'zoom') (o.sc *= 1 - (1 - e) * 0.14), (o.op *= clamp(ph.inP * 2)), (o.bl += (1 - e) * 14);
      else if (ph.inType === 'slide') o.tx += (1 - inOut(ph.inP)) * 1920;
      else o.op *= smooth(ph.inP); // dissolve: the new picture fades in over the old one
    }
    if (ph.outP > 0) {
      const e = inCubic(ph.outP);
      if (ph.outType === 'zoom') (o.sc *= 1 + e * 0.18), (o.op *= Math.pow(clamp(1 - ph.outP * 1.45), 1.4)), (o.bl += e * 14);
      else if (ph.outType === 'slide') (o.tx -= inOut(ph.outP) * 520), (o.op *= 1 - ph.outP * 0.6);
    }
    return o;
  }

  // ---- public --------------------------------------------------------------
  window.init = async (timeline, scale = 1) => {
    TL = timeline;
    const st = TL.style;
    const root = document.documentElement;
    if (st.theme === 'light') root.classList.add('light');
    const set = (k, v) => root.style.setProperty(k, v);
    set('--accent', st.accent);
    set('--accent2', st.accent2 || st.accent);
    set('--bg0', st.bg[0]);
    set('--bg1', st.bg[1] || st.bg[0]);
    set('--ink', st.ink);
    set('--display', st.display);
    set('--body', st.body);
    set('--dw', st.weight);
    set('--dls', st.spacing ?? '-.02em');
    set('--dtt', st.upper ? 'uppercase' : 'none');
    set('--quote', st.quote || st.display);
    set('--grade', st.grade);
    $('#stage').style.transform = `scale(${scale})`;
    $('#b0').style.background = st.accent;
    $('#b1').style.background = st.accent2 || st.accent;
    $('#grain').style.display = TL.look.grain ? 'block' : 'none';
    $('#vignette').style.display = TL.look.grain ? 'block' : 'none';
    if (TL.look.captions) $('#stage').classList.add('capson');
    plan();
    for (const b of TL.beats) {
      const r = el('div', 'shot', $('#beats'));
      const anim = build[b.shot.type](b, r);
      drawers.push({ b, root: r, anim });
    }
    // make sure every weight in use is loaded before the first frame is taken
    await Promise.all([...document.fonts].map((f) => f.load().catch(() => {})));
    await document.fonts.ready;
    await Promise.all([...document.images].map((i) => i.decode().catch(() => {})));
    for (const d of drawers) d.anim.ready?.();
  };

  window.renderAt = async (t) => {
    $('#b0').style.transform = `translate(${200 + 300 * Math.sin(t * 0.11)}px, ${-300 + 200 * Math.cos(t * 0.09)}px)`;
    $('#b1').style.transform = `translate(${1000 + 260 * Math.cos(t * 0.08 + 1)}px, ${380 + 220 * Math.sin(t * 0.1 + 2)}px)`;

    pending = [];
    for (const d of drawers) {
      const ph = phase(d.b, t);
      d.root.style.display = ph ? 'block' : 'none';
      if (!ph) continue;
      const o = pose(ph);
      d.root.style.opacity = o.op;
      d.root.style.filter = o.bl > 0.2 ? `blur(${o.bl}px)` : 'none';
      d.root.style.transform = o.tx || o.sc !== 1 ? `translateX(${o.tx}px) scale(${o.sc})` : 'none';
      d.anim(t);
    }

    // the hidden cuts: through black, through white, or under two bands
    let dip = 0;
    let dipColor = '#000';
    let wiping = false;
    for (const b of TL.beats) {
      const B = b.inB;
      if (!B || !B.seq) continue;
      const p = (t - (B.t - B.d / 2)) / B.d;
      if (p <= 0 || p >= 1) continue;
      if (B.type === 'wipe') {
        wiping = true;
        [0, 0.09].forEach((lead, i) => {
          const band = $('#band' + (1 - i));
          band.style.display = 'block';
          band.style.transform = `translateX(${lerp(-135, 135, inOut(clamp(p + (p < 0.5 ? lead : -lead))))}%) skewX(-14deg)`;
        });
      } else {
        dip = smooth(1 - Math.abs(p * 2 - 1));
        dipColor = B.type === 'flash' ? '#fff' : '#000';
      }
    }
    if (!wiping) for (const id of ['#band0', '#band1']) $(id).style.display = 'none';
    $('#dip').style.opacity = dip;
    $('#dip').style.background = dipColor;

    const ch = [...TL.chapters].reverse().find((c) => t >= c.t);
    const label = $('#chapterlabel');
    const cur = TL.beats.find((b) => t >= b.t0 && t < b.t1) || TL.beats[TL.beats.length - 1];
    const quiet = ['title', 'chapter', 'outro'].includes(cur.shot.type);
    label.textContent = ch && !ch.auto ? ch.title : '';
    label.style.opacity = TL.look.progress && !quiet ? 0.85 * clamp((t - cur.t0 + 0.2) / 0.4) : 0;
    $('#progress').style.display = TL.look.progress ? 'block' : 'none';
    $('#progress').style.transform = `scaleX(${t / TL.duration})`;

    const cap = $('#captions');
    const s = TL.look.captions ? TL.sentences.find((x) => t >= x.t0 - 0.05 && t < x.t1 + 0.2) : null;
    if (s) {
      if (cap.dataset.text !== s.text) {
        cap.dataset.text = s.text;
        cap.textContent = s.text;
      }
      cap.style.display = 'block';
      cap.style.transform = 'translateX(-50%)';
      cap.style.opacity = Math.min(clamp((t - s.t0 + 0.05) / 0.15), clamp((s.t1 + 0.2 - t) / 0.15));
    } else cap.style.display = 'none';

    if (pending.length) await Promise.all(pending);

    const bars = TL.look.letterbox ? 132 * outExpo(t / 1.2) : 0;
    $('#bar0').style.height = bars + 'px';
    $('#bar1').style.height = bars + 'px';
  };
})();
