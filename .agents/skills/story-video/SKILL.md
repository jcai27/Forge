---
name: story-video
description: This skill should be used when the user asks to "make a YouTube video about X", "storytelling video", "video essay", "explainer video on a topic", "documentary-style video", "mini documentary", "faceless YouTube video", "tell the story of X as a video", "history of X video", "how X works, as a video", "why did X happen, as a video", "turn this article / script / idea into a video", or "narrated video about a topic". Researches the topic, writes a story with a hook and chapters, finds photographs and video clips that may legally be used (Wikimedia Commons, with licence and author recorded), and produces a narrated 1080p video built from full-screen shots: real footage, archive photographs with slow camera moves and lower-third captions, title and chapter cards, pull quotes, figures that count up, bar and line charts, timelines, side-by-side comparisons and lists. Voiced with the local Kokoro-82M model. Delivers the MP4 with subtitles, a YouTube description (chapters, sources, image credits) and a thumbnail.
argument-hint: "<topic or script> [length] [audience] [style: documentary | bold | paper]"
version: 1.1.0
---

# story-video

Turn a topic into a narrated story video: the kind of video essay that holds
a viewer with a question, a sequence of pictures and a voice. Codex
researches the topic, writes the story, finds the pictures, and composes the
video one full-screen shot per idea.

Rendering runs on this machine. The voice is Kokoro-82M, also on this
machine, unless the user chooses the hosted ElevenLabs voice
(`references/voice.md`). The picture is an
HTML compositor (`stage/`) stepped frame by frame. Photographs and footage
come from Wikimedia Commons, which needs no account and records who made each image and
under what licence. The tool cache is shared with the `product-demo-video`
skill; use that skill instead when the subject is a website or app to be
shown working.

The whole video is one file, `story.json`: a list of **beats**. A beat is a
few sentences of narration and one **shot**, the picture on screen while they
are spoken.

| Shot | The picture | Use it for |
|---|---|---|
| `image` | A photograph filling the frame, moving slowly, with a caption in the lower third | Places, people, objects, events: most of the video |
| `clip` | Real footage filling the frame, silent under the voice, with the same caption and credit | Anything that moves: machines, crowds, weather, a place as it is |
| `title` | The title over a darkened photograph or the background | Naming the video, straight after the cold open |
| `chapter` | A large number and a chapter name | A turn in the story |
| `text` | One sentence, large, word by word | The question, the twist, the point |
| `quote` | A quotation and who said it, with an optional portrait | A real person's real words |
| `stat` | One to three figures that count up | A number worth a whole screen |
| `compare` | Two halves: figures or photographs | Before and after, them and us |
| `timeline` | Dates along a line, arriving as they are spoken | A sequence of events |
| `chart` | Bars, or a line that draws itself | Several numbers with a pattern |
| `list` | Points appearing as they are spoken | A summary; three things to remember |
| `outro` | The closing line | The end |

Three looks: `documentary` (dark, warm and muted photographs), `bold` (dark,
saturated) and `paper` (light, editorial). Type is set in bundled Google
Fonts; `"font"` picks the typeface (Montserrat, Oswald, Bebas Neue, Poppins,
DM Sans, Playfair Display).

Typical lengths: a **short** of 45 to 90 seconds on one idea; an **essay** of
3 to 6 minutes with three chapters (the default); a **long essay** of 8 to
12 minutes. Narration runs about 150 words a minute.

## Hard rules

1. **Nothing is stated that has not been checked.** Every factual claim in
   the narration or on screen has a row in `facts.md` with its tag: SOURCE (a
   named, linked source read in this session, with the passage), COMMON
   (undisputed general knowledge) or VIEW (an interpretation, worded as one).
   Dates, numbers, names, causes and "the first" or "the largest" are never
   COMMON. A claim with no source is cut or reworded. A search engine's
   summary is a lead, not a source: open the page.
2. **No invented quotations.** A `quote` shot shows words a named person
   demonstrably said or wrote, with the source in `facts.md`. No paraphrase in
   quotation marks, no composite, no "as one worker put it".
3. **No invented numbers.** Every figure in a `stat`, `chart`, `compare` or
   `timeline` comes from a source and is typed into `story.json` exactly as
   the source gives it. Approximate words ("about", "nearly") are narrated
   when the source is approximate. Charts carry a `source` line.
4. **Pictures are what they are said to be.** A photograph is captioned as
   what it actually shows (its place and year), not what the narration is
   about at that moment. An illustrative picture is fine; passing off a 1962
   photograph of one port as the 1956 event in another is not. Read each
   image's own description before using it.
5. **Only images and footage that may be used.** Every image and clip is fetched with
   `images.mjs` or registered with `images.mjs add`, so its author, licence
   and source page are on record; the build refuses one without a record.
   No footage ripped from YouTube, films, television or news. Nothing from a general web search, a news site or a stock site's
   preview. Credits appear on screen and in the description.
6. **Care with real people.** No private individuals. No image or wording
   that implies something about a living person that the sources do not
   support. No sexual, medical or criminal claims about a living person
   without a strong, named source, and then stated as that source's report.
7. **Balance where there is a real dispute.** On contested history, politics,
   science or health, say what is established, say what is disputed and by
   whom, and do not present one side's framing as settled. Decline to make a
   video whose point depends on a false or defamatory claim.
8. **The voice is never passed off as a person.** Never present the narration
   as a named real person, and never imitate one. The description file notes
   that the voice is synthetic unless the user turns that off
   (`"voiceNote": false`); if they do, tell them once that disclosure on
   upload is then theirs to decide.
9. **Look at every draft frame** before the final render. Read every
   `check/sheet-*.png`.
10. **Deliver the files and open the video.** The final step saves the MP4,
    subtitles, description and thumbnail to the user's Downloads folder
    (Desktop as fallback) and opens the video. Do not upload anything
    anywhere. Publishing is the user's step.

## Inputs to collect

| Input | Where it comes from | If missing |
|---|---|---|
| The topic, or a finished script | The user | Ask. With only a broad subject, propose three angles (a question each) and let the user pick |
| Length and audience | The user | A 3 to 5 minute essay for a curious general viewer |
| The angle: the one question the video answers | The user, or proposed after research | Propose it with the outline, before writing the full script |
| Sources the user trusts or wants used | The user | Find them: books, institutions, primary documents, reputable reference works. Two independent sources for anything surprising |
| Look | The user | `documentary` for history and people; `bold` for technology, business and science; `paper` for ideas and culture |
| Voice | The user | Kokoro `am_michael` or `af_heart`; ElevenLabs if they ask for the most natural voice and have a key. Captions burned in only if asked: a subtitle file is always produced |
| Their own images, logo or channel name | The user | None. Register any they supply with `images.mjs add` and their stated licence |
| Music | A file the user supplies (`"music": "bed.mp3"`) | None. The skill ships no music |

Ask at most once, for everything missing together. A topic alone is enough to
start the research; come back with the angle, the outline and any open
questions in one message, and wait for a yes before writing the full script.

## Workflow

### 1. Environment

```bash
. <skill>/scripts/env.sh && story_env_check
<skill>/scripts/setup.sh          # only when the check reports something missing
```

### 2. Project folder

Create `<scratch>/<video-name>/`. `example/` is a complete, runnable
67-second story with real photographs and credits; build it once to see the
pipeline work, and copy its `story.json` as the starting shape:

```bash
cp -R <skill>/example <scratch>/the-box && <skill>/scripts/build.sh draft <scratch>/the-box
```

### 3. Research

Find and read sources before writing anything. Search, then open the pages:
prefer books and their publishers' pages, institutions, archives, primary
documents, encyclopaedias of record, and reporting from named outlets. Note,
for each fact worth using, the exact wording, the page and the date. Look
especially for: the surprising number, the turning point and its date, the
person at the centre, a real quotation, the before and the after. Those
become shots.

Write `facts.md` as you go: one row per claim, with tag, source, the passage
it rests on, and whether a second source agrees. See
`references/sources-and-rights.md`.

### 4. Angle and outline, then confirm

Read `references/storycraft.md` first. Choose the one question the video
answers and write a short outline: the hook (the moment the video opens
inside), three or so chapters with the question each one answers and the
line that hands off to the next, the one fact held back and where it lands,
and the last line. Show the user the angle, the outline, the intended length
and anything uncertain, and wait for agreement.

### 5. Script and shots, in `story.json`

Write the beats in order. The format is in `references/story-format.md`. In
short:

- One idea per beat, one to three sentences, and a shot chosen because it
  shows that idea. Aim for a new picture every four to seven seconds.
- Write for the ear: short sentences, concrete nouns, the point at the end.
  Follow `references/voice.md` for names, numbers and acronyms: give those
  sentences a `speak` spelling.
- Open cold on the most arresting true thing, not on "In this video", over
  a picture or footage. The `title` beat comes second, with an empty `say`.
- Join beats with "but" or "so", never "and then", and end each chapter on
  the question the next one answers.
- Mark chapters with `chapter` shots or `"chapter": "Name"` on a beat; they
  become the label on screen and the timestamps in the description.
- Fill `sources` and `summary` at the top: they are printed in the
  description.

### 6. Pictures

```bash
node <skill>/scripts/images.mjs search PROJECT "longshoremen loading cargo"   # then READ the sheet it writes
node <skill>/scripts/images.mjs get PROJECT "longshoremen loading cargo" 3 --as hold
node <skill>/scripts/images.mjs search PROJECT "container ship" --video        # footage: length, size, licence
node <skill>/scripts/images.mjs get PROJECT "container ship" 3 --as ship-clip --start 6 --dur 8
node <skill>/scripts/images.mjs add PROJECT ~/photo.jpg --as founder --license "Used with permission" --author "A. Name"
node <skill>/scripts/images.mjs credits PROJECT
```

Search prints numbered candidates with size, licence and description, and
writes a contact sheet: read it and choose by eye. Search for the concrete
thing (an object, a place, a named person, a year), not the idea; try several
wordings. `get` saves the image and its credit, and prints what the uploader
says it shows: caption it as that. Prefer wide images of at least 1920
pixels; portraits and diagrams are placed on a card automatically.

Footage works the same way with `--video`. The sheet shows one frame of each
clip, which says little: after `get`, read the strip of five frames it
writes across the cut, and move `--start` if the cut contains a title card,
a presenter, burned-in text or a camera swing. Cut a second or two longer
than the beat's narration. Clips play silent. Use footage where movement is
the point; two or three good clips lift a video more than ten weak ones.

Where no
honest picture exists, use a `text`, `stat` or `timeline` shot instead: a
story told half in typography is better than one told with wrong pictures.

### 7. Draft, look, fix

```bash
<skill>/scripts/build.sh draft PROJECT
node <skill>/scripts/render.mjs PROJECT --draft --at 12.5,48     # just those moments, to check/at.png
```

The draft voices the script (cached per sentence), renders 540p to
`check/draft.mp4`, and writes `check/sheet-*.png` with a frame for every
sentence and every beat's last moment. It prints the running time, the word
count, the average seconds per picture, and any beat that holds one picture
for more than nine seconds.

Read every sheet against the checklist in `references/storycraft.md`: each
picture matches its sentence; faces and subjects are not cropped out or
hidden under the caption; text fits and is readable at the sheet's size;
figures match `facts.md` digit for digit; reveals land on the sentence that
names them; nothing sits on one picture too long. Fix and repeat until a full
pass finds nothing.

### 8. Final, deliver, open

```bash
<skill>/scripts/build.sh final PROJECT [OUT.mp4]
```

Renders 1080p at 30 fps and writes four files side by side: `NAME.mp4`,
`NAME.srt` (subtitles to upload with it), `NAME-description.txt` (summary,
chapter timestamps, sources, image credits, the synthetic-voice note) and
`NAME-thumbnail.png` (the title card, or the moment named by
`"thumbnail": { "at": 12.4 }`). It opens the video and saves three frames
from the finished file to `check/final-*.jpg`: read them as the last look.

### 9. Report

Tell the user: where the four files are and the running time; the angle and
the chapter list; every claim tagged VIEW, and anything surprising that rests
on a single source; every image and clip, what it really shows, and any that is
illustrative rather than of the event described; anything asked for but left
out, and why (no source, no usable picture); that the voice was not checked
by ear, naming the words most at risk; and what remains for them to do before
publishing: watch it, paste the description, upload the subtitles, and tick
YouTube's box for altered or synthetic content if it applies to their video.

## Gotchas

- A beat with long narration and one photograph drags. Split it: same
  subject, second picture, or a `text` shot for the key line.
- Reveals in `list`, `timeline`, `stat` and `compare` follow the sentences:
  item 1 on sentence 1. Fewer sentences than items and they spread evenly;
  put `"at": n` on an item to pin it to a sentence.
- A `text` shot shows its line on the first sentence. If the first sentence
  sets it up, add `"at": 1`.
- A clip shorter than its beat holds on its last frame, and the build says
  so. Cut it longer, set `"speed": 0.8`, or shorten the narration.
- Commons footage is uneven: phone clips, news packages with logos and
  captions, long timelapses. Choose the cut by its frames, not its title.
- Commons search is literal. "poverty" finds little; "tenement New York 1900"
  finds photographs. No result is a reason to change the wording or the shot,
  not to look elsewhere for an image without a licence record.
- CC BY-SA images are fine in a video with credit, but the licence asks that
  adaptations be shared alike. Say so in the report; prefer public-domain and
  CC BY images when both exist.
- Kokoro reads digits, initials and unusual names unpredictably. Write the
  digits in `text` (for subtitles) and the words in `speak`.
- Titles shrink to fit, but a title over about 40 characters is too long for
  a card. Shorten it.
- The on-screen credit is small by design. The description carries the full
  credit; do not remove both.
- A render stalls while the machine sleeps. The scripts hold a Mac awake, but
  not with the lid closed or the battery low.
- `audio/`, `check/` and `assets/_search/` are build products. `assets/` with
  `credits.json` is the record of what was used: keep it with the project.

## Resources

- `scripts/env.sh`, `scripts/setup.sh`: locate or install the tools (shared with product-demo-video).
- `scripts/images.mjs`: search Wikimedia Commons for photographs and footage, fetch (and cut) with credit, register supplied files, list credits.
- `scripts/narrate.mjs`: the local voice and the timings; cached per sentence.
- `scripts/render.mjs`: the edit and the render; `--draft` writes contact sheets, `--at` grabs chosen moments, `--final` writes the video, subtitles, description and thumbnail.
- `scripts/build.sh`: draft and final builds in one command.
- `scripts/lib/timeline.mjs`: pacing, cues, transitions, styles, subtitles, description.
- `stage/`: the compositor and every shot type.
- `example/`: a runnable story, "The Box", with four credited photographs and one clip.
- `references/story-format.md`: `story.json`, every shot and option.
- `references/storycraft.md`: angle, structure, writing, choosing shots, pacing, the draft checklist.
- `references/sources-and-rights.md`: what counts as a source, `facts.md`, image licences, credits, people.
- `references/voice.md`: Kokoro voices and writing for the ear.
