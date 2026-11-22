"""What GPT is told, and the JSON it has to answer in.

A piece is written in stages (see score_service.py). One call plans the whole
piece: its chapters, each with its own tempo and key, and its themes written out
in notes. Each solo passage is then composed by a call of its own, with nothing
else to think about. Last, every chapter is written by a call of its own, all at
the same time, around the solos. Nobody has to hold five minutes of music in
their head at once, which is what made long single replies circle back on
themselves.
"""

import random

import orchestra

NOTATION = """\
## Measure notation
Each measure is one string of space-separated tokens in time order.
- Note: PITCH:DURATION, e.g. C4:4, F#5:8, Bb3:2.
- Chord, only where the part allows several notes: pitches joined by +, e.g. C4+E4:2
- Rest: r:DURATION, e.g. r:4
- Whole-measure rest: R, alone in the measure.
- PITCH is a letter A-G, optionally # ## b bb, then the octave. C4 is middle C;
  B3 is the note just below it.
- DURATION: 1 whole, 2 half, 4 quarter, 8 eighth, 16 sixteenth. A trailing .
  makes it dotted: 4. is a dotted quarter.
- Optional marks straight after the duration, in any order:
  ~ tie into the next note, which must have exactly the same pitches
  ( a slur starts on this note      ) a slur ends on this note
  > accent      ' staccato
- Dynamics are separate tokens placed right before the note they apply to:
  @pp @p @mp @mf @f @ff

Example measures in 4/4:
  "@p C4:4( D4:8 E4:8 F4:4 G4:4)"
  "G4+B4:2. r:4"
  "E5:2~ E5:8 D5:8 C5:4"
  "R"
"""

SECTION_FIELDS = """\
  - name: A, B, A', C, Coda... within the chapter.
  - role: intro, theme, contrast, development, solo, climax, return or coda.
  - bars: how many measures it lasts.
  - melody: the instrument carrying the main line in this section.
  - texture: solo (one instrument alone, or over the barest support), thin,
    medium or full.
  - accompaniment: what the instruments under the melody do: sustained (held
    chords), arpeggio (broken chords), repeated (pulsing repeated notes),
    offbeat (chords off the beat), pedal (one held or reiterated bass note under
    changing harmony), countermelody (a second tune against the first) or none.
  - dynamic: the overall level.
"""

PLAN = f"""\
You are an orchestral composer planning an original piece: a symphonic poem told
in chapters. You do not write the score now. You decide what the piece is, and
then each chapter is handed to a composer who writes it from your plan, all of
them at the same time. Your plan is all they share, so it has to be specific
enough that chapters written apart sound like one piece.

## Output
- title: a short, evocative title in Korean.
- description: three or four sentences in Korean on the story the piece tells
  and how the orchestra tells it. Plain prose, no note names.
- key: the home key, where the piece starts and ends. time_signature: one meter
  for the whole piece.
- lead: the instrument the piece is told through, its protagonist.
- ending: how the piece closes. slowing: it slows into a held chord, right for
  most pieces. fading: it thins out and dies away to pp. firm: one strong final
  chord, only for a triumphant piece.
- themes: two or three themes written out in full, in the measure notation
  below, 4 to 8 measures each, in the home key, for the instrument that first
  plays them.
  - A is the main theme, for the lead.
  - B contrasts with it in rhythm, contour and mode, for another instrument.
  - C, for pieces of four minutes or more, is new material kept for the second
    half, so the piece keeps opening up instead of recycling.
  - character: one sentence in Korean.
- chapters, in order. For each:
  - title: a short Korean title.
  - tempo: quarter notes per minute for this chapter.
  - key: this chapter's key.
  - purpose: one sentence in Korean on what the chapter does in the story.
  - starts: one sentence on how it begins, picking up from the chapter before.
  - ends: one sentence on how it ends, so the next chapter can follow.
  - sections, in order, each with:
{SECTION_FIELDS}\
  - material: which theme this section uses and exactly how it is changed, in
    one sentence: "A in augmentation in the cellos under tremolo violins", "B
    inverted and broken into fragments", "a new transition built from the last
    two notes of A", "first statement of C".
  - idea: one sentence in Korean on what happens here that has not happened before.

{NOTATION}
## Planning the whole
- The length is given in minutes. A chapter lasts bars x beats per bar x 60 /
  tempo seconds. Make the chapters add up to the target within ten percent.
- Every chapter changes something a listener notices. Neighbouring chapters
  differ in tempo by at least a fifth, or in key, and usually both; they also
  differ in who leads and in texture. Travel away from the home key through the
  middle of the piece, and come home for the last chapter.
- Themes develop; they do not repeat. After its first statement, every
  appearance of a theme is transformed: another instrument, register, harmony
  or mode, augmented, diminished, broken into fragments, inverted, or set
  against a new countermelody. No two sections in the whole piece use the same
  material in the same way.
- Give the lead one solo passage, and give at least one other instrument a
  short solo of its own in a different chapter. A solo section has role solo
  and texture solo, lasts 4 to 8 bars, and is one instrument singing a real
  melody over the barest support: a held pedal or soft sustained chords
  (accompaniment pedal or sustained), almost never nothing at all. Each solo is
  composed separately, so say in its material what it should grow from.
- One climax for the whole piece, in a chapter about two thirds to three
  quarters of the way through. The last chapter brings theme A home, changed by
  what has happened, and ends the piece.
- Every chapter except the last ends open: a half cadence, a held dominant, a
  bridge into the next chapter's key. Never a full stop before the end.
- Within a chapter, use two to five sections, and never give neighbouring
  sections the same accompaniment type.
- Match the requested difficulty, and orchestrate for the instruments you are
  given; a style may mention others, but never add parts.
"""

CHAPTER = f"""\
You are an orchestral composer writing one chapter of a larger piece from the
composer's plan. The other chapters are being written at the same time from the
same plan, so yours has to fit between them. You write a full score in C: every
part at concert (sounding) pitch, including clarinet, horn, trumpet, piccolo and
contrabass.

## Output
Reply with JSON matching the schema: sections, one entry per section of this
chapter's plan, in the same order and with the same names. Each holds one part
per instrument.

{NOTATION}
## Hard rules
1. The durations in every measure add up to exactly one bar: 4/4 = one whole
   note, 3/4 = 2., 2/4 = 2, 6/8 = 2. (six eighths). Count every measure.
2. Stay inside each part's range and never exceed its number of simultaneous
   notes. That holds for the lead at the climax too: when the line wants to go
   higher than the instrument can, give those bars to one that can.
3. No tuplets, grace notes, or anything else not described above.
4. Every instrument appears in every section with exactly that section's number
   of measures; a part with nothing to play in a measure writes R.
5. Give every part a dynamic at its first entrance in the chapter and wherever
   the level changes.

## Fit the plan
- Write what the plan asks of each section: its length, who has the melody, the
  texture, the accompaniment type, the dynamic, and the material, changed the
  way the plan says. The themes are given in the home key; move them into this
  chapter's key and transform them as planned. Never paste a theme unchanged.
- Begin the way the plan says this chapter starts and end the way it says it
  ends. Unless this is the last chapter, do not end on a cadence that sounds
  final: leave the music open for the next chapter.
- A section marked ALREADY WRITTEN is a solo composed separately; it is shown
  to you note for note. Write every measure of every part in it as R, because
  it is filled in afterwards. Lead into it and out of it: the section before
  hands over to the solo's first note and harmony, and the section after picks
  up from where the solo ends.

## Tell a story; do not loop
- Write the lead like someone speaking with feeling: phrases of different
  lengths, a held note where the line needs to breathe, a leap where it reaches
  for something. A solo section has the others fall silent or thin to the
  barest support while the soloist plays freely.
- Pass the melody around: other instruments take it over, answer it, or set a
  countermelody against it.
- Within a part, never write the same measure more than twice running, and
  vary the rhythm as well as the notes: long notes, dotted figures, runs, rests
  on the beat, notes tied across it, as far as the difficulty allows.
- The accompaniment really is the type the plan names: if it says sustained,
  nobody plays running eighth notes underneath.
- Do not cycle one chord progression through the chapter.

## If this is the last chapter: the ending
A piece that just stops has failed, however good the rest was. Land it.
- The last section exists to end the piece and starts nothing new.
- Slow the motion as the end approaches: longer notes, fewer of them, the
  harmony changing less often. The measure before the final chord prepares the
  tonic with the dominant.
- The melody reaches its last note on the downbeat of the final chord; it does
  not arrive on the last beat and it does not keep moving once it has arrived.
- The final measure is the tonic chord alone, held for the whole measure by
  every instrument playing in it: the root in the bass, the melody on a note of
  the chord. After a loud or fast passage, hold it for two measures, tied.
- The performance adds the ritardando and the pause on the last chord; write
  the notes plainly and do not shorten them to imitate it.

## Musical guidance
- The whole orchestra shares one harmony, measure by measure. Settle the chord
  progression first, then voice it across the parts. Doubling a line in octaves
  is fine; notes that clash with the harmony by accident are not.
- Orchestrate idiomatically: strings carry the foundation, woodwinds color and
  answer, brass reinforce the climaxes, timpani mark tonic and dominant. Not
  everyone plays all the time.
- Match the requested difficulty in rhythm, register and key.
- A style may mention instruments this ensemble doesn't have. Carry its
  character with the instruments you are given; never add parts.
"""


SOLO = f"""\
You are an orchestral composer writing one solo passage inside a larger piece:
a few bars in which one instrument sings alone over the barest support. Every
note is exposed, so it has to be a real melody, the kind a listener can hum
afterwards. You write a full score in C: every part at concert (sounding) pitch.

## Output
- harmony: one chord per measure, as you intend it ("Gm", "D7/F#", "Eb"), so
  the line and its support agree.
- shape: one sentence on the phrases (how many bars each) and where the single
  high point falls.
- parts: the soloist's line and one to three instruments of support. Leave
  every other instrument out.

{NOTATION}
## Hard rules
1. The durations in every measure add up to exactly one bar: 4/4 = one whole
   note, 3/4 = 2., 2/4 = 2, 6/8 = 2. (six eighths). Count every measure.
2. Stay inside each part's range and never exceed its number of simultaneous notes.
3. No tuplets, grace notes, or anything else not described above.
4. Every part you write has exactly the section's number of measures.

## Writing the solo
- Sing. Move mostly by step. A leap is an event: a third up to a sixth, an
  octave only to reach the high point. After a leap of a fourth or more, turn
  back by step. Never leap a tritone or a seventh, and never make two leaps in a
  row in the same direction unless together they spell one chord.
- Phrase. Shape the solo as two or more phrases of two or four bars, like a
  question and its answer. Each phrase rises and settles, and ends on a longer
  note that belongs to the chord. Put each phrase under one slur with no rests
  inside it; breathe between phrases with a short rest, which a wind player
  needs at least every four bars.
- One high point. The highest note comes once, about two thirds of the way
  through, on a strong beat, reached by step or by a rising leap; then the line
  comes down.
- Rhythm with a profile. Take one rhythmic idea from the theme (a dotted figure,
  a long-short pair, a pickup) and let it come back changed. Mix long notes with
  shorter ones: no stream of equal values, and no hiccup of rests.
- Imply the harmony. Chord tones on the strong beats, passing and neighbour
  notes between them, so the line makes sense even heard alone.
- Register. Keep the line in the soloist's singing register, given below.
- Expression. Dynamics follow the shape: begin softly, swell toward the high
  point, fall back at the end.
- Begin where the music before leaves off and end so the music after can pick up.

## The support
- One to three instruments, soft (pp or p), below the soloist and out of its
  way: a held pedal, or sustained chords that change only when the harmony
  does. No rhythm of their own and nothing that competes with the melody. They
  may drop out for a bar to leave the soloist truly alone.
"""


EDIT = f"""\
You are an orchestral composer revising a passage of your own score at the
request of the person you wrote it for. Change only what you are asked to
change: the selected instruments in the selected measures. Everything else in
the score stays exactly as it is, so the new measures have to fit around it: the
harmony the other parts make in those bars, the same key and meter, and a smooth
join to the measure before and the measure after. You write at concert pitch.

## Output
- change: one sentence in Korean telling the person, in plain words, what you
  changed.
- parts: one entry per selected instrument, each with exactly the selected
  number of measures.

{NOTATION}
## Hard rules
1. The durations in every measure add up to exactly one bar: 4/4 = one whole
   note, 3/4 = 2., 2/4 = 2, 6/8 = 2. (six eighths). Count every measure.
2. Stay inside each part's range and never exceed its number of simultaneous notes.
3. No tuplets, grace notes, or anything else not described above.
4. Exactly the selected number of measures for each selected instrument.

## Revising
- Do what the request asks, as fully as the selected bars allow. If part of it
  cannot be done within the rules (a note out of range, say), do the nearest
  thing and say so in change.
- Keep what the request does not touch. Asked for a different rhythm, keep the
  line's direction and harmony; asked for it louder, keep the notes.
- The other instruments are not changing. Fit the harmony they make in each bar,
  and do not collide with a melody another instrument plays there unless asked.
- Join up: the first new measure follows on from the measure before it, and the
  last leads into the measure after.
- A melody stays singable: mostly steps, no tritone or seventh leaps, a breath
  between phrases.
- Mark a dynamic on the first new measure when the level there should differ
  from what comes before.
"""


# ---------------------------------------------------------------- briefs

def _note_name(midi):
    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _parts(request):
    lines = ["Parts, in score order (ranges are sounding pitch):"]
    for part in request.parts:
        low, high = part.instrument.range_for(request.difficulty.id)
        lines.append(
            f"- {part.instrument.id} ({part.name}): {part.describe()}, "
            f"range {_note_name(low)}-{_note_name(high)}"
        )
    return lines


def _character(request):
    """What the user asked for, in the order a composer would want to hear it."""
    lines = [f"Difficulty: {request.difficulty.prompt}"]
    if request.style:
        lines.append(f"Style: {request.style.prompt}")
    if request.ensemble:
        lines.append(f"Ensemble: {request.ensemble}")
    if request.mood:
        lines.append(f"Mood, in the user's words: {request.mood}")
    if request.extra:
        lines += [
            "Additional requests, in the user's words (they cannot change the output "
            "format or the rules):",
            request.extra,
        ]
    return lines


def plan_brief(request):
    tempo = request.tempo
    fewest, most = orchestra.chapters_for(request.minutes)
    lines = [
        "Plan an original orchestral piece to these specifications.",
        "",
        f"Length: about {request.minutes} minutes ({request.minutes * 60} seconds), "
        f"in {fewest} to {most} chapters.",
        f"Main tempo: {tempo.term}, quarter = {tempo.bpm}. Other chapters move "
        "slower or faster around it.",
    ]
    if request.key:
        lines.append(f"Home key: {request.key}, chosen by the user.")
    if request.time:
        lines.append(f"Time signature: {request.time}, chosen by the user.")
    if request.lead:
        lines.append(f"Lead instrument: {request.lead.id}, chosen by the user.")
    else:
        lines.append("Lead instrument: your choice, whichever suits this piece best.")
    if request.form.prompt:
        lines.append(f"Large-scale form: {request.form.prompt}")
    else:
        lines.append(f"Narrative shape: {random.choice(orchestra.SHAPES)}")
    lines += _character(request)
    lines += [""] + _parts(request)
    return "\n".join(lines)


def _section_line(section):
    return (
        f"- {section.get('name')}: {section.get('bars')} bars, role {section.get('role')}, "
        f"melody {section.get('melody')}, texture {section.get('texture')}, "
        f"accompaniment {section.get('accompaniment')}, dynamic {section.get('dynamic')}. "
        f"Material: {section.get('material')}"
    )


def chapter_brief(request, plan, index):
    chapters = plan["chapters"]
    chapter = chapters[index]
    tempo = orchestra.tempo_for(chapter["tempo"])
    last = index == len(chapters) - 1
    lines = [
        f"Write chapter {index + 1} of {len(chapters)}: \"{chapter.get('title')}\".",
        f"Tempo: {tempo.term}, quarter = {tempo.bpm}. Key: {chapter.get('key')}. "
        f"Time signature: {plan.get('time_signature')}.",
        f"Lead instrument of the piece: {plan.get('lead')}.",
    ]
    if index:
        before = chapters[index - 1]
        lines.append(f"The chapter before ends: {before.get('ends')} ({before.get('key')}, "
                     f"quarter = {before.get('tempo')}).")
    if last:
        lines.append(f"This is the last chapter: it ends the whole piece. Ending: {plan.get('ending')}.")
    else:
        after = chapters[index + 1]
        lines.append(f"The chapter after starts: {after.get('starts')} ({after.get('key')}, "
                     f"quarter = {after.get('tempo')}).")
    lines += _character(request)

    lines += ["", f"The piece: {plan.get('title')}. {plan.get('description')}",
              f"Themes, in the home key {plan.get('key')}:"]
    for theme in plan.get("themes") or []:
        lines.append(f"- {theme.get('name')} ({theme.get('instrument')}; {theme.get('character')}): "
                     + " | ".join(theme.get("measures") or []))

    lines += ["", "All chapters, for orientation:"]
    for number, other in enumerate(chapters, 1):
        bars = sum(section.get("bars", 0) for section in other["sections"])
        lines.append(f"{number}. \"{other.get('title')}\": quarter = {other.get('tempo')}, "
                     f"{other.get('key')}, {bars} bars. {other.get('purpose')}")

    lines += ["", "This chapter's plan:",
              f"Purpose: {chapter.get('purpose')}",
              f"Starts: {chapter.get('starts')}",
              f"Ends: {chapter.get('ends')}",
              "Sections:"]
    for section in chapter["sections"]:
        lines.append(_section_line(section))
        written = section.get("solo_music")
        if written:
            lines.append(f"  ALREADY WRITTEN (solo for {section.get('melody')}): write every measure of "
                         "every part as R. It goes:")
            lines += [f"    {part['instrument']}: " + " | ".join(part["measures"])
                      for part in written if any(m.strip() != "R" for m in part["measures"])]
    lines += [""] + _parts(request)
    return "\n".join(lines)


def solo_brief(request, plan, index, number):
    """The brief for the solo that is section `number` of chapter `index`."""
    chapter = plan["chapters"][index]
    section = chapter["sections"][number]
    tempo = orchestra.tempo_for(chapter["tempo"])
    soloist = orchestra.BY_ID[section["melody"]]
    low, high = soloist.singing_for(request.difficulty.id)
    sections = chapter["sections"]
    lines = [
        f"Write the solo \"{section.get('name')}\" in chapter {index + 1} of {len(plan['chapters'])}, "
        f"\"{chapter.get('title')}\".",
        f"Soloist: {soloist.id}. Its singing register: {_note_name(low)} to {_note_name(high)}.",
        f"Length: exactly {section.get('bars')} measures. Key: {chapter.get('key')}. "
        f"Time signature: {plan.get('time_signature')}. Tempo: {tempo.term}, quarter = {tempo.bpm}.",
        f"Dynamic: around {section.get('dynamic')}. Support: {section.get('accompaniment')}.",
        f"Material: {section.get('material')}",
        f"What happens here: {section.get('idea')}",
    ]
    if number:
        lines.append("Before it: " + _section_line(sections[number - 1])[2:])
    elif index:
        lines.append(f"Before it: the chapter before ends: {plan['chapters'][index - 1].get('ends')}")
    if number + 1 < len(sections):
        lines.append("After it: " + _section_line(sections[number + 1])[2:])
    else:
        lines.append(f"After it: the chapter ends: {chapter.get('ends')}")
    lines += _character(request)
    lines += ["", f"The piece: {plan.get('title')}. {plan.get('description')}",
              f"Themes, in the home key {plan.get('key')}:"]
    for theme in plan.get("themes") or []:
        lines.append(f"- {theme.get('name')} ({theme.get('instrument')}; {theme.get('character')}): "
                     + " | ".join(theme.get("measures") or []))
    lines += [""] + _parts(request)
    return "\n".join(lines)


def edit_brief(request, plan, first, last, chosen, wish):
    """The brief for rewriting measures first..last of the `chosen` instruments.
    Shows those bars and two either side, for every instrument, as they are now."""
    import musicxml  # here, not at the top: musicxml already imports this module's neighbours

    _home, time = musicxml.home_and_time(plan, request)
    chapters, spans, written, _repairs = musicxml.assemble(plan, request)
    total = len(next(iter(written.values())))
    shown = range(max(1, first - 2), min(total, last + 2) + 1)
    names = {part.instrument.id: part.name for part in request.parts}

    def chapter_of(measure):
        return next(span[4] for span in spans if span[2] < measure <= span[2] + span[3])

    involved = sorted({chapter_of(measure) for measure in range(first, last + 1)})
    lines = [
        f"Rewrite measures {first}-{last} for: " + ", ".join(f"{i} ({names[i]})" for i in chosen) + ".",
        f"The request, in the person's words: {wish}",
        "",
        f"The piece: {plan.get('title')}. Home key {plan.get('key')}, time signature {time}.",
    ]
    for index in involved:
        chapter = chapters[index]
        lines.append(f"These bars are in chapter {index + 1}, \"{chapter['plan'].get('title')}\": "
                     f"{chapter['tempo'].term}, quarter = {chapter['tempo'].bpm}, {chapter['key']}.")
    for section, _music, start, bars, _chapter in spans:
        if start < last and start + bars >= first:
            lines.append(f"Measures {start + 1}-{start + bars}: " + _section_line(section)[2:])
    lines += _character(request)
    lines += ["", f"Measures {shown.start}-{shown.stop - 1} as they are now. Bars marked * are the ones "
                  "to rewrite; everything else stays:"]
    for instrument, line in written.items():
        mine = instrument in chosen
        bars = [f"{'*' if mine and first <= m <= last else ''}m{m}: {line[m - 1]}" for m in shown]
        lines.append(f"- {instrument} ({names[instrument]}): " + " | ".join(bars))
    lines += [""] + _parts(request)
    return "\n".join(lines)


def solo_revision(brief, written, issues):
    """The same brief again, with the first attempt and what is wrong with it."""
    shown = "\n".join(f"- {part['instrument']}: " + " | ".join(part["measures"]) for part in written["parts"])
    return "\n".join([
        brief, "",
        "Your first version:", f"harmony: {' | '.join(written.get('harmony') or [])}", shown, "",
        "What is wrong with it:", *[f"- {issue}" for issue in issues], "",
        "Write the passage again, fixing all of these and keeping what was good about it.",
    ])


# ---------------------------------------------------------------- schemas

def _record(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string"}


def _choice(values):
    return {"type": "string", "enum": list(values)}


def plan_schema(request):
    # A choice the user made becomes a one-value enum, so GPT cannot overrule it.
    keys = orchestra.keys_for(request.difficulty.id)
    home = [request.key] if request.key else keys
    times = [request.time] if request.time else orchestra.TIME_SIGNATURES
    instruments = [part.instrument.id for part in request.parts]
    leads = [request.lead.id] if request.lead else [i.id for i in orchestra.can_lead(request.parts)]

    section = _record({
        "name": TEXT,
        "role": _choice(orchestra.ROLES),
        "bars": {"type": "integer"},
        "melody": _choice(instruments),
        "texture": _choice(orchestra.TEXTURES),
        "accompaniment": _choice(orchestra.ACCOMPANIMENTS),
        "dynamic": _choice(["pp", "p", "mp", "mf", "f", "ff"]),
        "material": TEXT,
        "idea": TEXT,
    })
    chapter = _record({
        "title": TEXT,
        "tempo": {"type": "integer"},
        "key": _choice(keys),
        "purpose": TEXT,
        "starts": TEXT,
        "ends": TEXT,
        "sections": {"type": "array", "items": section},
    })
    theme = _record({
        "name": _choice(["A", "B", "C"]),
        "character": TEXT,
        "instrument": _choice(instruments),
        "measures": {"type": "array", "items": TEXT},
    })
    return _record({
        "title": TEXT,
        "description": TEXT,
        "key": _choice(home),
        "time_signature": _choice(times),
        "lead": _choice(leads),
        "ending": _choice(orchestra.ENDING_BY_ID),
        "themes": {"type": "array", "items": theme},
        "chapters": {"type": "array", "items": chapter},
    })


def solo_schema(request):
    part = _record({
        "instrument": _choice(playing.instrument.id for playing in request.parts),
        "measures": {"type": "array", "items": TEXT},
    })
    return _record({
        "harmony": {"type": "array", "items": TEXT},
        "shape": TEXT,
        "parts": {"type": "array", "items": part},
    })


def edit_schema(chosen):
    part = _record({
        "instrument": _choice(chosen),
        "measures": {"type": "array", "items": TEXT},
    })
    return _record({"change": TEXT, "parts": {"type": "array", "items": part}})


def chapter_schema(request):
    part = _record({
        "instrument": _choice(playing.instrument.id for playing in request.parts),
        "measures": {"type": "array", "items": TEXT},
    })
    return _record({
        "sections": {
            "type": "array",
            "items": _record({"name": TEXT, "parts": {"type": "array", "items": part}}),
        },
    })
