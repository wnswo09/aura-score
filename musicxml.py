"""Turn GPT's compact measure strings into a MusicXML full score.

GPT never writes MusicXML: a full score in it runs to thousands of lines, and
one slip anywhere breaks the whole file. It writes one short string per measure
instead ("@p C4:4( D4:8 E4:8 F4:4 G4:4)"), section by section after an outline
of the whole piece, and this module does the rest.

Repairs are for the mistakes a model actually makes: a measure a beat short or
long, a note an octave outside the instrument, more notes in a chord than there
are players, a tie between different pitches, a slur that never closes. Each is
counted, and the count goes back to the page with the score.
"""

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

import orchestra

DIVISIONS = 8  # per quarter note: fine enough for a dotted sixteenth (3) and a 32nd (1)

TIME_SIGNATURES = {"4/4": (4, 4), "3/4": (3, 4), "2/4": (2, 4), "6/8": (6, 8)}

# Duration code -> (divisions, MusicXML type)
DURATIONS = {
    "1": (32, "whole"),
    "2": (16, "half"),
    "4": (8, "quarter"),
    "8": (4, "eighth"),
    "16": (2, "16th"),
}
# What a gap or an overlong note is cut into, longest first: (divisions, type, dots)
PIECES = [
    (32, "whole", 0), (24, "half", 1), (16, "half", 0), (12, "quarter", 1), (8, "quarter", 0),
    (6, "eighth", 1), (4, "eighth", 0), (3, "16th", 1), (2, "16th", 0), (1, "32nd", 0),
]

DYNAMICS = {"ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"}
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
ALTERS = {"": 0, "#": 1, "##": 2, "b": -1, "bb": -2}

_PITCH = r"[A-G](?:##|#|bb|b)?\d"
NOTE = re.compile(rf"^(r|{_PITCH}(?:\+{_PITCH})*):(16|1|2|4|8)(\.?)([~()>']*)$")
PITCH = re.compile(r"^([A-G])(##|#|bb|b)?(\d)$")

# Clef -> (sign, line, MIDI note at the middle of the staff)
CLEFS = {
    "G": ("G", 2, 71),
    "F": ("F", 4, 50),
    "C3": ("C", 3, 60),
    "C4": ("C", 4, 57),
}
# How much closer to the middle of the staff another clef has to be before it
# wins over the instrument's usual one. Cellos live in bass clef up to ~D4.
CLEF_MARGIN = 6


@dataclass(frozen=True)
class Pitch:
    step: str
    alter: int
    octave: int

    @property
    def midi(self):
        return 12 * (self.octave + 1) + STEPS[self.step] + self.alter

    def moved(self, octaves):
        return Pitch(self.step, self.alter, self.octave + octaves)

    @classmethod
    def read(cls, text):
        step, accidental, octave = PITCH.match(text).groups()
        return cls(step, ALTERS[accidental or ""], int(octave))


@dataclass
class Event:
    pitches: list           # empty for a rest
    duration: int
    kind: str = ""          # MusicXML note type; empty means a whole-measure rest
    dots: int = 0
    dynamic: str = ""
    tie: bool = False       # asked for; only becomes tie_start if the next note agrees
    tie_start: bool = False
    tie_stop: bool = False
    slur_start: bool = False
    slur_stop: bool = False
    accent: bool = False
    staccato: bool = False


def measure_length(time):
    beats, beat_type = TIME_SIGNATURES[time]
    return beats * DIVISIONS * 4 // beat_type


def _rests(amount):
    rests = []
    while amount > 0:
        size, kind, dots = next(piece for piece in PIECES if piece[0] <= amount)
        rests.append(Event([], size, kind, dots))
        amount -= size
    return rests


def parse_measure(text, length):
    """One measure string -> (events filling exactly `length`, repairs made)."""
    tokens = str(text).split()
    if not tokens or tokens == ["R"]:
        return [Event([], length)], 0

    events, repairs, used, dynamic = [], 0, 0, ""
    for token in tokens:
        if token.startswith("@"):
            if token[1:] in DYNAMICS:
                dynamic = token[1:]
            else:
                repairs += 1
            continue

        match = NOTE.match(token)
        if not match or used >= length:
            repairs += 1
            continue

        head, code, dot, marks = match.groups()
        size, kind = DURATIONS[code]
        dots = 1 if dot else 0
        if dots:
            size = size * 3 // 2
        if size > length - used:
            # Runs past the barline: keep the longest piece that fits.
            repairs += 1
            size, kind, dots = next(piece for piece in PIECES if piece[0] <= length - used)
            marks = marks.replace("~", "")

        events.append(Event(
            pitches=[] if head == "r" else [Pitch.read(name) for name in head.split("+")],
            duration=size,
            kind=kind,
            dots=dots,
            dynamic=dynamic,
            tie="~" in marks,
            slur_start="(" in marks,
            slur_stop=")" in marks,
            accent=">" in marks,
            staccato="'" in marks,
        ))
        dynamic = ""
        used += size

    if used < length:
        repairs += 1
        events.extend(_rests(length - used))
    if not any(event.pitches or event.dynamic for event in events):
        return [Event([], length)], repairs
    return events, repairs


def _fit(pitches, low, high, max_notes, keep_low):
    """Pull stray notes into range by octaves, drop doubles, cap the chord."""
    fitted = []
    for pitch in pitches:
        while pitch.midi < low:
            pitch = pitch.moved(1)
        while pitch.midi > high:
            pitch = pitch.moved(-1)
        if pitch.midi >= low and pitch.midi not in {kept.midi for kept in fitted}:
            fitted.append(pitch)
    fitted.sort(key=lambda pitch: pitch.midi)

    if len(fitted) > max_notes:
        if max_notes == 1:
            fitted = fitted[:1] if keep_low else fitted[-1:]
        else:
            # The outer voices carry the harmony: keep the bottom and the top.
            fitted = fitted[:1] + fitted[1 - max_notes:]
    return fitted


def _link(events):
    """Keep ties and slurs only where they make sense. Returns repairs made."""
    repairs = 0
    for event, after in zip(events, events[1:] + [None]):
        if not event.tie:
            continue
        same = after is not None and after.pitches and (
            {pitch.midi for pitch in after.pitches} == {pitch.midi for pitch in event.pitches}
        )
        if event.pitches and same:
            event.tie_start = after.tie_stop = True
            after.pitches = list(event.pitches)  # one spelling on both sides of the tie
        else:
            repairs += 1

    open_slur = None
    for event in events:
        if event.slur_stop:
            if open_slur is not None and event.pitches:
                open_slur = None
            else:
                event.slur_stop = False
                repairs += 1
        if event.slur_start:
            if open_slur is None and event.pitches:
                open_slur = event
            else:
                event.slur_start = False
                repairs += 1
    if open_slur is not None:
        open_slur.slur_start = False
        repairs += 1
    return repairs


def _tidy_dynamics(bars):
    """Drop a dynamic that only repeats the one already in force.

    Writing section by section, GPT restates the level in every measure. A mark
    is kept when it changes the level, or when the part comes back in after two
    or more measures of rest, where a player wants the reminder.
    """
    current, silent = "", 0
    for events in bars:
        if not any(event.pitches for event in events):
            silent += 1
            for event in events:
                event.dynamic = ""  # nothing to play it on
            continue
        for event in events:
            if not event.dynamic:
                continue
            if event.dynamic == current and silent < 2:
                event.dynamic = ""
            else:
                current, silent = event.dynamic, 0
        silent = 0


def _clef(instrument, bars):
    written = sorted(
        pitch.midi + 12 * instrument.octave
        for events in bars for event in events for pitch in event.pitches
    )
    usual = instrument.clefs[0]
    if not written:
        return usual
    middle = written[len(written) // 2]
    best = min(instrument.clefs, key=lambda clef: abs(CLEFS[clef][2] - middle))
    if abs(CLEFS[usual][2] - middle) - abs(CLEFS[best][2] - middle) > CLEF_MARGIN:
        return best
    return usual


def _layout(data, total):
    """The outline's sections with room made for exactly `total` measures.

    Returns ([[outline entry, its music, first measure, measures]], repairs). A
    section that would run past the end is cut; whatever is left unplanned is
    added to the last one.
    """
    outline = data.get("outline") if isinstance(data.get("outline"), list) else []
    music = data.get("sections") if isinstance(data.get("sections"), list) else []
    spans, repairs, at = [], 0, 0
    for index, entry in enumerate(outline):
        if not isinstance(entry, dict):
            continue
        try:
            wanted = int(entry.get("bars"))
        except (TypeError, ValueError):
            wanted = 0
        bars = max(0, min(wanted, total - at))
        repairs += bars != wanted
        if bars:
            written = music[index] if index < len(music) and isinstance(music[index], dict) else {}
            spans.append([entry, written, at, bars])
            at += bars
    if at < total:
        repairs += 1
        if spans:
            spans[-1][3] += total - at
        else:
            spans.append([{}, music[0] if music and isinstance(music[0], dict) else {}, 0, total])
    return spans, repairs


def build(data, request):
    """GPT's JSON plus the request it answered -> the page's score payload.

    Raises ValueError when there is nothing worth showing.
    """
    key = data.get("key") if data.get("key") in orchestra.KEY_BY_LABEL else request.key or "C major"
    time = data.get("time_signature")
    if time not in TIME_SIGNATURES:
        time = request.time or "4/4"
    length = measure_length(time)

    # GPT writes section by section; the score needs each instrument end to end.
    spans, repairs = _layout(data, request.length)
    written = {part.instrument.id: [] for part in request.parts}
    for _entry, music, _first, bars in spans:
        given = {}
        for part in music.get("parts") or []:
            if isinstance(part, dict) and part.get("instrument") not in given:
                given[part.get("instrument")] = [str(m) for m in part.get("measures") or []]
        for instrument, line in written.items():
            measures = given.get(instrument, [])
            repairs += len(measures) != bars
            line += (measures + ["R"] * bars)[:bars]

    notes, parts = 0, []
    for part in request.parts:
        instrument = part.instrument
        low, high = instrument.range_for(request.difficulty.id)
        max_notes = part.max_notes
        bars = []
        for text in written[instrument.id]:
            events, fixed = parse_measure(text, length)
            repairs += fixed
            for event in events:
                if not event.pitches:
                    continue
                fitted = _fit(event.pitches, low, high, max_notes, instrument.clefs[0] == "F")
                if [pitch.midi for pitch in fitted] != sorted(pitch.midi for pitch in event.pitches):
                    repairs += 1
                event.pitches = fitted
                notes += len(fitted)
            bars.append(events)
        repairs += _link([event for events in bars for event in events])
        _tidy_dynamics(bars)
        parts.append((part, bars))

    if not notes:
        raise ValueError("GPT 가 음표를 하나도 쓰지 않았습니다. 다시 시도해 주세요.")

    playing = {part.instrument.id: part for part in request.parts}
    lead = playing.get(data.get("lead")) or playing.get(request.lead.id if request.lead else None) or request.parts[0]
    flow = _flow(spans, playing)
    marks = _marks(flow, lead)

    title = str(data.get("title") or "").strip()[:60] or "무제"
    return {
        "title": title,
        "description": str(data.get("description") or "").strip()[:600],
        "key": key,
        "time": time,
        "tempo": _tempo_label(request.tempo, time),
        "measures": request.length,
        "lead": lead.instrument.ko,
        "flow": flow,
        "repairs": repairs,
        "repetition": _repetition(parts),
        "musicxml": _write(title, parts, key, time, request, marks),
        "playback": _playback(parts, length, request.tempo, marks),
    }


def _flow(spans, playing):
    """The plan as the page shows it: what each stretch of the piece is for."""
    flow = []
    for number, (entry, _music, first, bars) in enumerate(spans):
        melody = playing.get(entry.get("melody"))
        flow.append({
            "name": str(entry.get("name") or "").strip()[:8] or chr(ord("A") + number % 26),
            "role": orchestra.ROLES.get(entry.get("role"), ""),
            "solo": entry.get("role") == "solo",
            "from": first + 1,
            "to": first + bars,
            "melody": melody.instrument.ko if melody else "",
            "texture": orchestra.TEXTURES.get(entry.get("texture"), ""),
            "accompaniment": orchestra.ACCOMPANIMENTS.get(entry.get("accompaniment"), ""),
            "dynamic": entry.get("dynamic") if entry.get("dynamic") in DYNAMICS else "",
            "idea": str(entry.get("idea") or "").strip()[:200],
        })
    return flow


def _marks(flow, lead):
    """What the plan adds to the page of music: a rehearsal letter where each
    section starts, and Solo over the lead's staff where it plays alone."""
    words, solo = {}, set()
    for section, after in zip(flow, flow[1:] + [None]):
        if not section["solo"]:
            continue
        words[section["from"] - 1] = "Solo"
        solo.update(range(section["from"] - 1, section["to"]))
        # Several players share this staff, so say when the rest of them come back in.
        if after and not after["solo"] and lead.players > 1:
            words[after["from"] - 1] = "tutti"
    return {
        "rehearsal": {section["from"] - 1: section["name"] for section in flow},
        "lead": lead,
        "words": words,
        "solo": solo,
    }


# ---------------------------------------------------------------- repetition

def _repetition(parts):
    """How much of the piece is something already heard, as numbers.

    exact:  share of notes sitting in a measure that copies an earlier measure of
            the same part, pitch for pitch.
    rhythm: the same, comparing rhythm only — different notes in a rhythm heard
            before still sound like the same idea.
    loops:  measures in which the whole orchestra copies an earlier measure.

    Measures are weighted by how many notes they hold: a repeated eight-note
    figure is far more audible than a held note carried over the barline.
    """
    def exact(events):
        return tuple((tuple(pitch.midi for pitch in event.pitches), event.duration) for event in events)

    def rhythm(events):
        return tuple((bool(event.pitches), event.duration) for event in events)

    total = copied = same_rhythm = 0
    for _part, bars in parts:
        heard, rhythms = set(), set()
        for events in bars:
            weight = sum(1 for event in events if event.pitches)
            if not weight:
                continue
            total += weight
            copied += weight if exact(events) in heard else 0
            same_rhythm += weight if rhythm(events) in rhythms else 0
            heard.add(exact(events))
            rhythms.add(rhythm(events))

    heard, loops, sounding = set(), 0, 0
    for index in range(len(parts[0][1])):
        column = tuple(exact(bars[index]) for _part, bars in parts)
        if not any(pitches for part in column for pitches, _duration in part):
            continue
        sounding += 1
        loops += column in heard
        heard.add(column)

    return {
        "exact": round(100 * copied / total) if total else 0,
        "rhythm": round(100 * same_rhythm / total) if total else 0,
        "loops": loops,
        "measures": sounding,
    }


# ---------------------------------------------------------------- playback

# MIDI velocity for each dynamic. Parts start at mf until told otherwise.
VELOCITIES = {"ppp": 28, "pp": 38, "p": 50, "mp": 64, "mf": 78, "f": 94, "ff": 108, "fff": 120}
ACCENT = 15


def _playback(parts, length, tempo, marks):
    """The same notes as the score, as a timeline the browser can play.

    Times are in quarter notes from the start, so the page only needs the tempo
    to turn them into seconds. Tied notes become one long note, the way a player
    would hold them, and dynamics become velocities. A section's solo passage
    goes on a track of its own, played with the solo instrument's sample.
    """
    tracks = []
    for part, bars in parts:
        alone = part is marks["lead"] and part.sound != part.instrument.sound
        notes, solo, holding, velocity = [], [], {}, VELOCITIES["mf"]
        for index, events in enumerate(bars):
            at = index * length
            target = solo if alone and index in marks["solo"] else notes
            for event in events:
                if event.dynamic:
                    velocity = VELOCITIES[event.dynamic]
                sounding = event.duration / 2 if event.staccato else event.duration
                loud = min(127, velocity + (ACCENT if event.accent else 0))
                tied = {}
                for pitch in event.pitches:
                    if event.tie_stop and pitch.midi in holding:
                        note = holding[pitch.midi]
                        note[1] += sounding  # keep holding the note it's tied from
                    else:
                        note = [at, sounding, pitch.midi, loud]
                        target.append(note)
                    if event.tie_start:
                        tied[pitch.midi] = note
                holding = tied
                at += event.duration
        for sound, timeline in ((part.sound, notes), (part.instrument.sound, solo)):
            if timeline:
                tracks.append({
                    "sound": sound,
                    "notes": [[start / DIVISIONS, size / DIVISIONS, midi, loud]
                              for start, size, midi, loud in timeline],
                })
    return {"bpm": tempo.bpm, "quarters": len(parts[0][1]) * length / DIVISIONS, "tracks": tracks}


# ---------------------------------------------------------------- writing

def _part_list(parts):
    lines = ["<part-list>"]
    group = 0
    for index, (part, _bars) in enumerate(parts):
        instrument = part.instrument
        section = [other for other, _ in parts if other.instrument.section == instrument.section]
        first, last = section[0] is part, section[-1] is part
        if first and len(section) > 1:
            group += 1
            lines.append(
                f'<part-group type="start" number="{group}"><group-symbol>bracket</group-symbol>'
                "<group-barline>yes</group-barline></part-group>"
            )
        pid = f"P{index + 1}"
        channel = index + 1 if index < 9 else index + 2  # channel 10 is for drum kits
        lines.append(
            f'<score-part id="{pid}">'
            f"<part-name>{escape(part.name)}</part-name>"
            f"<part-abbreviation>{escape(instrument.abbr)}</part-abbreviation>"
            f'<score-instrument id="{pid}-I1"><instrument-name>{escape(instrument.name)}</instrument-name></score-instrument>'
            f'<midi-instrument id="{pid}-I1"><midi-channel>{channel}</midi-channel>'
            f"<midi-program>{instrument.midi_program}</midi-program></midi-instrument>"
            "</score-part>"
        )
        if last and len(section) > 1:
            lines.append(f'<part-group type="stop" number="{group}"/>')
    lines.append("</part-list>")
    return lines


def _beat(tempo, beat_type):
    """(per minute, dotted?) — in 6/8 the beat is the dotted quarter, at the same eighth-note pulse."""
    if beat_type == 8:
        return round(tempo.bpm * 2 / 3), True
    return tempo.bpm, False


def _tempo_label(tempo, time):
    per_minute, dotted = _beat(tempo, TIME_SIGNATURES[time][1])
    return f"{tempo.term} ♩{'.' if dotted else ''}={per_minute}"


def _tempo(tempo, beat_type):
    per_minute, compound = _beat(tempo, beat_type)
    dot = "<beat-unit-dot/>" if compound else ""
    return (
        '<direction placement="above">'
        f'<direction-type><words font-weight="bold">{tempo.term}</words></direction-type>'
        f'<direction-type><metronome parentheses="no"><beat-unit>quarter</beat-unit>{dot}'
        f"<per-minute>{per_minute}</per-minute></metronome></direction-type>"
        f'<sound tempo="{tempo.bpm}"/></direction>'
    )


def _notes(event, octave):
    if not event.pitches:
        if not event.kind:
            return f'<note><rest measure="yes"/><duration>{event.duration}</duration><voice>1</voice></note>'
        return (
            f"<note><rest/><duration>{event.duration}</duration><voice>1</voice>"
            f"<type>{event.kind}</type>{'<dot/>' * event.dots}</note>"
        )

    out = []
    for index, pitch in enumerate(event.pitches):
        pitch = pitch.moved(octave)
        alter = f"<alter>{pitch.alter}</alter>" if pitch.alter else ""
        ties = ('<tie type="stop"/>' if event.tie_stop else "") + ('<tie type="start"/>' if event.tie_start else "")
        notations = ('<tied type="stop"/>' if event.tie_stop else "") + ('<tied type="start"/>' if event.tie_start else "")
        if index == 0:  # slurs and articulations belong to the chord, written once
            notations += '<slur type="stop" number="1"/>' if event.slur_stop else ""
            notations += '<slur type="start" number="1"/>' if event.slur_start else ""
            marks = ("<accent/>" if event.accent else "") + ("<staccato/>" if event.staccato else "")
            notations += f"<articulations>{marks}</articulations>" if marks else ""
        out.append(
            "<note>"
            + ("<chord/>" if index else "")
            + f"<pitch><step>{pitch.step}</step>{alter}<octave>{pitch.octave}</octave></pitch>"
            + f"<duration>{event.duration}</duration>{ties}<voice>1</voice>"
            + f"<type>{event.kind}</type>{'<dot/>' * event.dots}"
            + (f"<notations>{notations}</notations>" if notations else "")
            + "</note>"
        )
    return "".join(out)


def _write(title, parts, key, time, request, marks):
    fifths, mode = orchestra.KEY_BY_LABEL[key]
    beats, beat_type = TIME_SIGNATURES[time]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">',
        '<score-partwise version="4.0">',
        f"<work><work-title>{escape(title)}</work-title></work>",
        "<identification><encoding><software>Aura Score</software></encoding></identification>",
        *_part_list(parts),
    ]

    for index, (part, bars) in enumerate(parts):
        instrument = part.instrument
        lines.append(f'<part id="P{index + 1}">')
        sign, line, _middle = CLEFS[_clef(instrument, bars)]
        transpose = (
            "<transpose><diatonic>0</diatonic><chromatic>0</chromatic>"
            f"<octave-change>{-instrument.octave}</octave-change></transpose>"
            if instrument.octave else ""
        )
        for number, events in enumerate(bars, 1):
            lines.append(f'<measure number="{number}">')
            if number == 1:
                lines.append(
                    f"<attributes><divisions>{DIVISIONS}</divisions>"
                    f"<key><fifths>{fifths}</fifths><mode>{mode}</mode></key>"
                    f"<time><beats>{beats}</beats><beat-type>{beat_type}</beat-type></time>"
                    f"<clef><sign>{sign}</sign><line>{line}</line></clef>{transpose}</attributes>"
                )
                if index == 0:
                    lines.append(_tempo(request.tempo, beat_type))
            if index == 0 and number - 1 in marks["rehearsal"]:
                lines.append(
                    '<direction placement="above"><direction-type><rehearsal>'
                    f'{escape(marks["rehearsal"][number - 1])}</rehearsal></direction-type></direction>'
                )
            if part is marks["lead"] and number - 1 in marks["words"]:
                lines.append(
                    '<direction placement="above"><direction-type><words font-style="italic">'
                    f'{marks["words"][number - 1]}</words></direction-type></direction>'
                )
            for event in events:
                if event.dynamic:
                    lines.append(
                        '<direction placement="below"><direction-type><dynamics>'
                        f"<{event.dynamic}/></dynamics></direction-type></direction>"
                    )
                lines.append(_notes(event, instrument.octave))
            if number == len(bars):
                lines.append('<barline location="right"><bar-style>light-heavy</bar-style></barline>')
            lines.append("</measure>")
        lines.append("</part>")

    lines.append("</score-partwise>")
    return "\n".join(lines)
