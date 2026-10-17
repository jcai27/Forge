# Sources and rights

A story video makes claims to an audience that cannot check them and shows
pictures made by other people. Both need a record.

## What counts as a source

Best first:

1. **Primary material**: the document, the dataset, the speech, the patent,
   the court ruling, the company's own filing.
2. **Books and papers by named authors**, from academic or established
   publishers. Cite the work; where the text itself was not read in this
   session, say which summary of it was.
3. **Institutions**: national archives, statistical offices, museums,
   universities, standards bodies.
4. **Reference works of record** and reporting from named outlets with
   editorial standards.
5. **A well-sourced encyclopaedia article**, as a map to the above. Follow
   its footnotes for anything that matters.

Not sources: a search engine's summary or an AI answer; unsourced listicles
and content farms; forums and social posts (except as the thing being
reported); another video essay; your own memory. Memory is where to look, not
what to cite.

Anything surprising, disputed, or carrying the weight of the story needs two
independent sources. Two pages that copy the same third page are one source.

When sources disagree, say so in the narration or use the more careful
figure, and note the disagreement in `facts.md`.

## `facts.md`

One row per claim made in the voice or on screen.

| # | Claim as worded in the video | Tag | Source | Passage it rests on | Second source |
|---|---|---|---|---|---|
| 1 | The Ideal X left Newark for Houston in April 1956 | SOURCE | Wikipedia, "SS Ideal X" (read on the day of writing) | "on 26 April 1956, the Ideal X carried 58 containers from Port Newark, New Jersey, to Port of Houston, Texas" | Wikipedia, "Containerization", same date and count |
| 2 | Cargo had been loaded by hand | COMMON | | | |
| 3 | Where a thing is made stopped mattering very much | VIEW | The thesis of Marc Levinson's *The Box* (not read in this session) | | |

- **SOURCE**: a named source read in this session, with the passage.
- **COMMON**: undisputed general knowledge. Never a date, number, name, cause
  or superlative.
- **VIEW**: an interpretation. Worded as one, and attributed where it is
  someone's argument.

`example/facts.md` is the sheet for the example story. An encyclopaedia was
enough there because the example exists to show the format; a video meant
for an audience should go to the sources behind it.

Before the final render, read `story.json` against `facts.md` line by line:
every sentence and every on-screen figure has a row, and the wording has not
drifted past what the source supports ("fell sharply" is not "fell by 97
percent").

## Quotations

A `quote` shot needs: the exact words, who said or wrote them, where and
when, and a source that reproduces them. Check famous quotations twice: many
are misattributed. Translate only with a note that it is a translation. If
the exact words cannot be confirmed, paraphrase in the narration without
quotation marks.

## Images

### Where they come from

`images.mjs` searches Wikimedia Commons and keeps only images whose licence
allows reuse with credit: public domain, CC0, CC BY and CC BY-SA. For each
image kept it records the title, author, licence, licence link and source
page in `assets/credits.json`. The build refuses any image without a record.

Images the user supplies are registered with `images.mjs add`, with the
licence as the user states it ("Own work", "Used with permission from ...",
"Licensed from ..."). Take their word and record it.

Do not use: images from a general web search, news photographs, stock-site
previews, film stills, album or book covers and logos as decoration,
screenshots of someone else's video. "It's on the internet" is not a licence.

### Footage

The same rules, with `images.mjs search --video`. Commons holds government
and military b-roll (often public domain), archive film, and clips people
have shot and released. Not usable: anything downloaded from YouTube or
other video sites (a "Creative Commons" label there is not a record this
skill can check), film and television, news broadcasts, sports, music
videos, and stock-site previews.

Clips need extra reading. A news package uploaded under a free licence may
still show a broadcaster's logo, named private people or music; cut around
them or choose another. Clips play silent, which removes music and speech
from the question.

### What the licences ask

| Licence | Asks for |
|---|---|
| Public domain, CC0 | Nothing. Credit anyway: it is good practice and helps viewers |
| CC BY | Credit to the author and a link to the licence |
| CC BY-SA | The same, and that adaptations are shared under the same licence. Tell the user when one is used |

The build puts the author and licence on screen with each photograph and
writes the full credit, with links, into the description. Keep at least the
description credits.

A licence covers the photograph, not everything in it. A freely licensed
photo of a painting, a sculpture, a trademark or a recognisable private
person can still carry other rights. For a history or explainer video this
is rarely a problem; flag it in the report when an image's subject is itself
a recent artwork, a logo, or an identifiable private individual.

### Honest pictures

Read each image's description when fetching it. Caption it as what it is.

- **Of the thing itself**: caption plainly. "Newark, 1956".
- **Of the same kind of thing, elsewhere or at another time**: usable to show
  what something looked like, captioned with its real place and year.
  "Hallstavik, Sweden, 1962" under a line about docks in general.
- **Unrelated but evocative**: avoid. Use typography instead.

Never caption or imply an illustrative image as the specific event, person
or place being described.

### People

- Public figures in their public role: fine, from licensed images.
- Private individuals: do not make them subjects. Incidental people in a
  street scene or an archive photograph are fine.
- Children, victims, patients, people in distress: use with great restraint,
  never as decoration, and never identified beyond what the source does.
- No picture placed beside a claim so as to suggest something about the
  person that the sources do not say.

## Subjects that need more care

- **Contested history and current politics**: separate what is established
  from what is argued; attribute the arguments; do not adopt one side's
  vocabulary as neutral. Offer the user a version that says "historians
  disagree" rather than one that picks a winner without evidence.
- **Health, medicine, money, law**: describe and explain; do not advise.
  Use the careful source's wording for risks and effects.
- **Crime and accusation**: "was convicted of", "was accused by", "according
  to the ruling", with the source. Nothing about a living person that the
  sources do not state.
- **Tragedy**: no sensational pictures or phrasing; numbers from official
  sources; dignity for the people in it.

If the story the user wants depends on a claim that the sources contradict,
say so and offer the story the sources do support.

## Before publishing: what to tell the user

- The narration is a synthetic voice, and the description says so. YouTube
  asks creators to disclose realistic altered or synthetic content; whether
  that applies to this video is theirs to judge when uploading.
- Which images are CC BY-SA.
- Which claims are views, and which surprising ones rest on one source.
- That the description file holds the credits and sources and should be
  pasted in.
