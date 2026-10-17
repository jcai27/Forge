# The voice

`narrate.mjs` voices every sentence in `story.json` and measures it. The edit is
timed to those measurements, so narration always runs before the render.
Sentences are cached by their text, voice and speed in `PROJECT/audio/`: a
re-run voices only what changed.

## Engines

| `voice.engine` | What it is | When |
|---|---|---|
| `kokoro` (default) | Kokoro-82M, an open text-to-speech model, run on this machine through `kokoro-js`. About 90 MB, downloaded once. A few seconds per sentence on a laptop | Almost always |
| `elevenlabs` | ElevenLabs Eleven v3, a hosted voice that sounds much closer to a person. Needs `ELEVENLABS_API_KEY` in the environment; uses the account's credits. `voice.voice` is an ElevenLabs voice id (default George, `JBFqnCBsd6RMkjVDRZzb`); `voice.model` defaults to `eleven_v3`; `voice.stability` to 0.5 | The user asks for the most natural voice, or Videor Studio has set it |
| `say` | The macOS system voice. Set `voice.voice` to a voice name (`Samantha`, `Daniel`) | Kokoro will not install, or a quick timing pass |
| `none` | No voice. Each sentence is given the time it takes to read | A silent cut; pair with `"captions": true` |

With `kokoro`, `say` and `none` the text goes to no hosted service. With
`elevenlabs` every spoken sentence is sent to ElevenLabs: that is the user's
call to make, so do not switch a project to it unasked, and say so in the
report when it was used.

## ElevenLabs

A whole beat is voiced in one request, so the voice carries its intonation
from one sentence to the next, and the timestamps that come back cut it into
sentences for the edit. Changing any sentence in a beat voices that beat
again, and costs its characters again; a five-minute script is about 4,500.

- It reads numbers, years and most names well on its own. Keep `speak`
  spellings for names it could not know and for acronyms.
- Punctuation is direction: an ellipsis is a pause, a word in capitals is
  stressed. Audio tags in square brackets (`[sighs]`, `[whispers]`) go in
  `speak` only, and sparingly: a documentary voice rarely needs one.
- The same text can be read a little differently each time it is voiced.
- `voice.speed` is honoured between 0.7 and 1.2.

## Kokoro voices

Set `voice.voice`. American English: `af_heart` (default, warm), `am_michael` (steady, suits documentary), `af_bella`,
`af_nicole`, `af_sarah`, `am_fenrir`, `am_puck`. British English:
`bf_emma`, `bf_isabella`, `bm_george`, `bm_fable`. `voice.speed` between 0.9
and 1.1 keeps it natural. A story wants an unhurried voice: 0.95 to 1.0.

One voice per video.

## Writing for the ear

Kokoro reads what it is given, literally, and ElevenLabs mostly does. Where the written form and the
spoken form differ, give both:

```json
"say": [{ "text": "In April 1956 his ship, the Ideal X, left Newark.", "speak": "In April nineteen fifty six, his ship, the Ideal Ex, left Newark." }]
```

`text` goes to the subtitle file and burned-in captions; `speak` goes to the voice.

| Written | Risk | Spell it for the voice as |
|---|---|---|
| Names of people and places (`McLean`, `Nguyen`, `Worcester`) | Stress or vowels guessed wrong | A respelling that sounds right: "Mc Clane", "Wooster" |
| Years and dates (`1956`, `26 April`) | Read as a number, or oddly | "nineteen fifty six", "the twenty sixth of April" |
| Roman numerals and regnal names (`Henry VIII`, `World War II`) | Read as letters | "Henry the Eighth", "World War Two" |
| Acronyms (`API`, `SQL`, `CSV`, `SSO`) | Read as a word | Spaced letters: "A P I"; or the usual word: "sequel" |
| Numbers and units (`3x`, `10k`, `$49/mo`, `99.9%`) | Symbols dropped or misread | Words: "three times", "ten thousand", "forty nine dollars a month" |
| Symbols and paths (`@`, `/`, `→`, `&`, URLs) | Skipped or spelled out | Words, or leave them out of what is said |
| Abbreviations (`e.g.`, `vs`, `w/`) | Read as letters | The full words |

Punctuation is pacing. A comma is a short breath, a full stop a longer one.
Split a long sentence in two rather than hoping for a pause. Avoid brackets,
dashes and ellipses in spoken text for Kokoro.

## What cannot be checked here

The voice cannot be listened to in this session. Durations are measured, so
timing is right; pronunciation is not verified. In the report, name the words
most likely to be wrong (names of people and places first, then anything in the table
above) so the user knows where to listen. Names of real people matter most:
a mispronounced name undermines the whole video. If one is wrong, change its `speak`
spelling and rebuild: only that sentence is voiced again.

## Captions and subtitles

Every final build writes `NAME.srt` from the `text` of each sentence, timed
to the voice: upload it with the video. `"captions": true` also burns each
sentence into the picture, which suits videos likely to be watched muted;
lower-third captions move up to make room.

## The voice is synthetic, and says so

The description file ends with a line saying the narration is a synthetic
voice. Leave it in. Do not name the voice after a real person or ask it to
sound like one.
