# The story file: `story.json`

One file describes the whole video. `example/story.json` is a working one.

## Top level

| Key | Meaning | Default |
|---|---|---|
| `name` | File name of the video | `story` |
| `title` | The video's title, for the record | `name` |
| `summary` | One or two sentences, printed first in the description | none |
| `sources` | List of strings, or `{ "title", "publisher", "url" }`. Printed in the description | none |
| `style` | `"documentary"`, `"bold"`, `"paper"`, or `{ "base": "bold", "accent": "#00c2a8" }` to adjust one | `documentary` |
| `font` | Typeface for titles and figures: `montserrat`, `oswald`, `bebas`, `poppins`, `dmsans`, `playfair`. Open-licensed Google Fonts bundled with the skill | The look's own: Montserrat for documentary, Poppins for bold, Playfair Display for paper |
| `voiceNote` | `false` leaves the line about the synthetic voice out of the description file. The user's choice; see `sources-and-rights.md` | `true` |
| `voice` | `{ "engine": "kokoro" \| "elevenlabs" \| "say" \| "none", "voice", "speed" }`. See `voice.md` | Kokoro, `af_heart`, 1.0 |
| `captions` | `true` burns each spoken sentence in at the bottom. A subtitle file is written either way | `false` |
| `credits` | `"onscreen"` shows each photograph's author and licence in its corner; `"description"` leaves them to the description only | `onscreen` |
| `progress` | The thin progress line and the chapter label in the corner | `true` |
| `grain` | Film grain and darkened corners | `true` |
| `letterbox` | Black bars for a 2.39:1 frame | `false` |
| `music` | A file in the project, or `{ "file", "gain" }`. Looped, lowered under the voice, faded out | none |
| `sfx` | `false` turns off the transition sound | on |
| `thumbnail` | `{ "at": 12.4 }`: the moment to save as the thumbnail | the title card |
| `beats` | The beats, in playing order | required |

A style object may override `accent`, `accent2`, `bg` (two colours), `ink`,
`display` and `body` (CSS font stacks; fonts outside the bundled set must be installed on this machine),
`grade` (a CSS filter applied to every photograph) and `transition`.

## A beat

```json
{ "id": "by-hand",
  "chapter": "Before the box",
  "shot": { "type": "image", "image": "assets/hold.jpg", "label": "Before the box", "caption": "Every sack, carried by hand" },
  "say": ["Before the box, cargo was loaded by hand.", "Sack by sack. Crate by crate."] }
```

| Key | Meaning |
|---|---|
| `id` | Unique. Used in logs and on the contact sheets |
| `shot` | The picture. `type` and that type's fields, below |
| `say` | One sentence, a list, or a list of `{ "text": "for subtitles", "speak": "spelled for the voice" }`. May be empty: a `chapter` card usually is |
| `chapter` | Starts a chapter here without a chapter card: sets the corner label and a timestamp in the description |
| `transition` | How this beat arrives: `dissolve`, `cut`, `dip` (through black), `flash` (through white), `zoom`, `slide`, `wipe` |
| `min` | Shortest length in seconds |
| `lead`, `tail` | Silence before the first sentence and after the last |

A beat lasts as long as its sentences plus a short breath. Each sentence's
start is a **cue**: lists, timelines, stats and comparisons reveal their
items on the cues, in order.

Default transitions: the style's own between ordinary beats (`dissolve` for
documentary and paper, `zoom` for bold), `dip` into a `chapter` or `outro`.

## Shots

Every shot except `image`, `clip` and `compare` takes `"bg": "assets/x.jpg"`: a
darkened photograph behind the words instead of the plain background.

### `image`

| Field | Meaning |
|---|---|
| `image` | The file, in `assets/`, with a record in `assets/credits.json` |
| `label` | Small line above the caption: a place and a year |
| `caption` | A short line in the lower third. Leave both out for a clean picture |
| `move` | `in`, `out`, `left`, `right`, `up`, `down`, `still`. Left out, consecutive images alternate |
| `focus` | `[x, y]` from 0 to 1: the point a push-in closes on. Set it to a face or the subject |
| `fit` | `"cover"` fills the frame; `"contain"` shows the whole image on a card over a blurred copy. Chosen automatically: wide photographs fill, portraits and squares sit on a card |
| `frame` | `"card"` forces the card, slightly tilted: for documents, screenshots, book covers |
| `highlight` | `[x, y, w, h]` from 0 to 1 within the image: a box drawn round one area, the rest dimmed. Card only. `highlightAt` is the sentence it appears on |

### `clip`

| Field | Meaning |
|---|---|
| `clip` | The file, in `assets/`, with a record in `assets/credits.json`. Cut to length by `images.mjs get --start --dur`, or any MP4, MOV or WebM the user supplied and registered |
| `start` | Seconds into the file to begin. Default 0 |
| `speed` | Playback speed. 0.8 slows it a little and stretches a short clip; 2 or more suits a timelapse feel |
| `label`, `caption` | As for `image` |

Footage is cropped to fill the frame and plays without its sound. It starts
slightly before the beat so it is already moving as it arrives. If the file
ends before the beat does, the last frame holds and the build prints a note.

### `title`, `chapter`, `outro`

`title`: `kicker`, `title`, `subtitle`. `chapter`: `title`; `number` is
counted automatically. `outro`: `title`, `subtitle`, `cta` (a short line in a
pill), `note` (a small line at the bottom, such as where the sources are).
Star words to give them the accent colour: `"It is just a *box*"`.

### `text`

`text`: one sentence, starred words accented. `at`: the sentence it appears
on (default the first).

### `quote`

`text` (the exact words, no quotation marks), `by`, `role` (who they were, or
the work and year), `image` (an optional portrait), `source` (a small line at
the bottom).

### `stat`

One figure: `value`, `prefix`, `suffix`, `decimals`, `label`, `from` (where
the count starts). Several: `"items": [ { ... }, { ... } ]`, up to three,
each revealed on its sentence. `title` is a small heading; `source` a small
line at the bottom. `value` is a number; the count-up always lands on it
exactly.

### `compare`

`left` and `right`, each with `label`, and either `value` (shown as typed,
so `"$5.86"` or `"16¢"`) with `text` beneath, or an `image` with `text` over
it. The left appears on the first sentence, the right on the second.

### `timeline`

`title`, and `events`: two to six of `{ "year", "label" }`. `year` is shown
as typed, so it may be a date or a decade. Each arrives on its sentence.

### `chart`

`title`, `data`: `[{ "label", "value" }]`, `prefix`, `suffix`, `decimals`,
`source`. Bars (the default): up to seven, in the order given, one marked
`"highlight": true`. `"kind": "line"`: points in order, the first and last
labelled with their values, others with `"mark": true`; `min` and `max` set
the vertical range.

### `list`

`title`, `items`: up to four strings or `{ "text", "at" }`. Each appears on
its sentence; earlier ones dim.

## Timing reveals

Items reveal on sentence cues in order: item 1 on sentence 1, item 2 on
sentence 2. With fewer sentences than items, they spread evenly across the
beat. `"at": n` on an item pins it to sentence `n` (counting from 0).

## What the build tells you

After each build: the running time, the number of beats and words, the
average seconds per picture, and any beat that holds one picture for more
than nine seconds. `check/timeline.json` has every beat's start and end and
every cue.
