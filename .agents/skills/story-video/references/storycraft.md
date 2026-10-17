# Telling the story

The pipeline makes any `story.json` look finished. Whether anyone watches to
the end is decided by the angle, the first fifteen seconds and the writing.

## The angle

A topic is not a story. "Shipping containers" is a topic. "How did a steel
box make it not matter where things are made?" is a story: it has a question,
and the viewer stays to hear the answer.

Find the angle after the research, not before. Good angles come from:

- **A surprising number.** Loading a ton fell from dollars to cents.
- **A turn.** Everyone did it one way, then one person did it another.
- **A consequence nobody intended.** The box that emptied the docks.
- **A question the viewer has half-asked.** Why is everything made far away?
- **A person who wanted something.** A trucker tired of waiting at the pier.

State the angle as one question. Every beat either sets it up, moves toward
the answer, or pays it off. Anything else, however interesting, is cut.

## Structure

| Part | Share of the length | Job |
|---|---|---|
| Cold open | The first 10 to 15 seconds; up to a minute in a long essay | Start inside the most arresting true moment, then ask the question. No greeting, no "in this video" |
| Title | 3 seconds, after the open | Name it. Its own beat, with no narration over it |
| Back to the start | A fifth | Rewind to where it began: what was normal, and why it was a problem |
| Turn | A fifth | The person or event that changed it. A date, a place, a decision |
| Consequences | Two fifths | What followed, in rising scale. The largest fact or reveal lands about three quarters of the way through |
| Payoff | The last 20 to 30 seconds | Answer the question from the open. Return to the first image or line, changed |

This is the order of telling, not the order of events. Open on the moment
with the most at stake (the alarm, the discovery, the number that should not
be possible), then go back and earn it. A story told strictly from the
earliest date forward spends its opening on background.

Give each part a chapter. Three chapters suit 3 to 6 minutes; a short needs
none.

### The chain of questions

The angle is the big question. Under it, every chapter answers one smaller
question and ends by raising the next, so the viewer always has a reason to
stay for the next two minutes:

> Where was the extra lead coming from? → How much harm could a little do? →
> When did it start? → What did it do to people?

Write the chain down before writing the script. If a chapter does not answer
the question the one before it raised, it is in the wrong place or the wrong
video. The question is asked once, in the voice, and answered over the
chapter that follows, never in the next sentence.

### "But" and "so", not "and then"

Join each beat to the one before with "but" or "so". A fix that causes a new
problem ("It stopped the knocking. But it had a terrible smell") pulls a
viewer forward; "and then, in 1923" does not. Read the script's joins aloud:
wherever the honest connector is "and then", cut the beat, move it, or find
what it changed.

### Hold one thing back

Choose one true fact that changes how everything before it looks, and place
it at the midpoint or later: the police had been warned a month earlier; the
man who ran the study was the man selling the product. Plant what it needs
early, in passing, so the reveal feels earned and not sprung. Never hold back
by misleading: everything said before the reveal must still be true after it.

### Explain only when the story needs it

Background, definitions and how-it-works belong at the moment the viewer
needs them to follow the next step, and no earlier. Give the problem first
("the engine was deafeningly loud"), then the explanation of why.

### A thread, and a second one

Keep a thread: one person, one object or one place the story keeps returning
to. It turns a list of facts into a story. Give that person a small, real,
physical detail (what they said, where they slept, what was in their hand):
one per chapter is enough.

In an essay or long essay, a second thread that starts somewhere unrelated
and meets the first at the midpoint is the strongest shape there is. Cut away
from one thread at a moment of suspense, not at a resting point.

### The last line

End on a concrete fact or image the viewer has not heard yet, or the opening
line seen differently: "The money was never recovered." Not a summary of what
was just said, and not a moral.

### By length

| Length | Shape |
|---|---|
| Short | One question, three or four moves, each joined by "but". No chapters, no title card needed, no recap |
| Essay | The table above. A chain of three questions. One fact held back |
| Long essay | The same, with a 30 to 60 second open that ends by promising two or three specific things to come ("and a camera in a fast-food restaurant gives them away"), and two threads |

## Writing for the ear

- Short sentences. One fact each. The important word last.
- Concrete over abstract: "sack by sack, crate by crate", not "manual
  handling of break-bulk cargo".
- Numbers a listener can hold: "under sixteen cents", "ten years later".
  One number per sentence, and not many per minute. Put the exact figure on
  screen and a rounded one in the voice when the source allows.
- Present the setup in past tense and the turning moments close up: "In
  April 1956, his ship left Newark."
- Vary the length. Three short sentences, then a longer one that lands.
- Say it the way a person would tell it across a table. Read every line
  aloud in your head; cut anything you would not say.
- Write like a person who has made documentaries, not like a summary. Avoid
  the patterns that mark machine writing: "it wasn't X, it was Y" reversals,
  lists of exactly three, a dash in every other sentence, rhetorical
  questions answered at once, and words like "delve", "tapestry",
  "testament", "landscape", "pivotal". Prefer the specific detail (a date, a
  room, what someone said) to the summing-up sentence.
- No throat-clearing: "it's important to note", "interestingly", "as we'll
  see", "let's dive in", "but that's not all".
- Do not narrate the picture ("as you can see here"). The voice says what the
  picture cannot.
- Signal a view as a view: "arguably", "many historians think", with the
  source in `facts.md`.

About 150 words make a minute. Count before building: 450 to 900 words for
the default essay.

## Choosing the shot

Ask of each beat: what would a viewer want to be looking at while hearing
this?

| The sentence is about | The shot |
|---|---|
| A place, a person, an object, an event | `image` of that thing. Caption it with what it is and when |
| Something whose movement is the point: a machine working, a ship under way, a crowd, a storm | `clip`, if licensed footage of it exists |
| The central question or the twist | `text` |
| One number that changes the story | `stat`, alone on the screen |
| Two numbers set against each other | `compare` |
| Three or more numbers with a pattern | `chart` |
| A run of dates | `timeline` |
| A real person's words | `quote`, with their portrait if a licensed one exists |
| A document, a headline, a page | `image` with `"frame": "card"` and a `highlight` |
| A recap | `list`, once, near the end |
| A new part of the story | `chapter` |

Rules of thumb:

- More than half the beats should be photographs or footage. Typography is
  punctuation.
- Footage earns its place by moving. A clip of something standing still is a
  worse photograph. Open on footage when there is a strong clip: movement in
  the first seconds holds a viewer.
- Keep clips to four to eight seconds each, and let the cut begin after any
  camera wobble settles.
- Never the same shot type three times running, except `image`.
- One idea per screen. If a shot needs a paragraph to explain, it is two shots.
- On-screen words echo the voice in fewer words; they never say something
  different while the voice is talking.
- A caption is a headline of two to six words. A label is a place and a year.
- When no honest picture exists, do not use a dishonest one. Use type.

## Pacing

- A new picture every four to seven seconds on average. Under three feels
  frantic; over nine drags, and the build warns about it.
- Slow down at the turn and the payoff: a longer shot, a pause (`"tail": 0.8`).
- Speed up through lists and consequences.
- Let the important line land on a clean screen: a `text` shot, or an image
  with no caption.
- Transitions: leave the defaults. Use one `wipe` or `flash` at the biggest
  turn, if at all.

## The first fifteen seconds

Most viewers decide here. The open should contain, in this order: a concrete
image or fact that makes someone look up; a reason it matters to them; the
question. Then the title. Test: would the first two sentences make sense, and
make someone curious, with no title and no context?

The first beat is never the `title` shot. It is an `image` or `clip` (or a
`text` or `stat` if the hook is a line or a number) carrying the first
sentence. The strongest opens are a scene already under way, told in the
present tense with a named person in it ("Jenny is counting banknotes on the
night shift"), or a claim that sounds impossible and is true. The `title`
beat follows, with an empty `say`.

## Titles and thumbnails

The title promises the answer to the question without giving it: "How a
steel box remade the world", not "The history of containerisation". Keep the
title card to a few words; the long form goes in the YouTube title field.

The thumbnail is saved from the title card by default. A stronger one is
usually a `text` or `stat` beat or a striking photograph: name its moment
with `"thumbnail": { "at": 41.2 }`. Three to five words at most, readable at
the size of a postage stamp.

## Draft checklist

Read every `check/sheet-*.png`. For each frame:

- **Match.** The picture is what the sentence under it is about.
- **Honest.** The caption says what the photograph actually shows.
- **Footage.** No title card, logo, presenter, burned-in caption or watermark
  inside a clip's cut; the subject is in frame after the crop to 16:9; the
  build printed no note about a clip running out.
- **Subject.** Faces and the main subject are in frame, not under the
  caption or cut by the crop. Set `focus`, change `move`, or use `"fit":
  "contain"`.
- **Readable.** Every word on screen can be read at the sheet's size. Titles
  and statements fit without shrinking to nothing; nothing is clipped.
- **Figures.** Every number on screen matches `facts.md` digit for digit,
  with the right unit and symbol.
- **Timing.** In lists, timelines and comparisons, each item is on screen for
  the sentence that names it, and not before the one that introduces it.
- **Variety.** No run of similar-looking frames; no beat flagged as too long.
- **Tone.** No picture that is jarring, gruesome or undignified for its
  subject; nothing that makes a person look like something the story does
  not claim.
- **Credit.** Photographs show their credit unless credits were moved to the
  description.
- **Silent test.** Reading the sheets left to right, without the sound, the
  story still makes sense.
- **Order.** The first frame is a picture with the hook, not the title card;
  the title follows it.

Then check the mid-points of the two or three most important transitions with
`--at`.
