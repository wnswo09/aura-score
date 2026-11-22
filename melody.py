"""A second pair of ears for solo lines.

A solo is the most exposed thing in a piece, and the first ones GPT wrote had
the faults a teacher would circle in red: a line made of leaps with a tritone
in it, a phrase chopped up by a rest every half bar, nowhere for a wind player
to breathe. `critique` finds those, bar by bar, and says what is wrong in words
GPT can act on; score_service.py sends them back for one rewrite.

Every check is a rule of thumb from melody writing, not a law, so the limits
are loose: a single leap of a seventh in a long line is let through; a line
built of them is not.
"""

import musicxml

NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
AWKWARD = {6: "a tritone", 10: "a minor seventh", 11: "a major seventh"}
HALF = musicxml.DIVISIONS * 2      # a half note, in divisions
WINDS = {"woodwind", "brass"}


def _name(midi):
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


def _notes(measures, length):
    """(bar, midi, duration, starts a new note) for each sounding event, plus the
    rests as (bar, None, duration, False)."""
    found = []
    for bar, text in enumerate(measures, 1):
        for event in musicxml.parse_measure(text, length)[0]:
            if event.pitches:
                found.append((bar, max(pitch.midi for pitch in event.pitches), event.duration, not event.tie_stop))
            else:
                found.append((bar, None, event.duration, False))
    return found


def critique(measures, instrument, difficulty, length):
    """What is wrong with this solo line, as a list of sentences. Empty is good."""
    events = _notes(measures, length)
    notes = [(bar, midi, size) for bar, midi, size, fresh in events if midi is not None and fresh]
    if len(notes) < 4:
        return ["The solo has almost no notes. Write a real melody that fills the section."]
    issues = []

    moves = [(a, b) for a, b in zip(notes, notes[1:])]
    intervals = [b[1] - a[1] for a, b in moves]

    bad = [f"{_name(a[1])} to {_name(b[1])} in bar {b[0]} ({AWKWARD.get(abs(b[1] - a[1]), 'more than an octave')})"
           for a, b in moves if abs(b[1] - a[1]) in AWKWARD or abs(b[1] - a[1]) > 12]
    if bad:
        issues.append("Awkward leaps that do not sing: " + "; ".join(bad[:4]) + ". Fill them in with steps or "
                      "choose a consonant interval (third, fourth, fifth, sixth, octave).")

    steps = sum(abs(step) <= 2 for step in intervals)
    if steps < 0.55 * len(intervals):
        issues.append(f"Only {steps} of {len(intervals)} moves are steps; the line reads like an arpeggio. "
                      "A solo sings mostly by step, with leaps as events.")

    unturned = [b[0] for (a, b), after in zip(moves, intervals[1:])
                if abs(b[1] - a[1]) >= 5 and after * (b[1] - a[1]) > 0 and abs(after) > 2]
    if len(unturned) > 1:
        issues.append("After a leap of a fourth or more the line keeps going the same way (bars "
                      + ", ".join(map(str, unturned[:4])) + "). Turn back by step after a leap.")

    inner_rests = sum(1 for index, (bar, midi, size, _fresh) in enumerate(events)
                      if midi is None and 0 < index < len(events) - 1 and size < HALF)
    if inner_rests > len(measures) * 0.75:
        issues.append(f"{inner_rests} short rests break the line into fragments. Keep each phrase legato "
                      "and breathe only between phrases.")

    durations = [size for _bar, _midi, size in notes]
    common = max(durations.count(size) for size in set(durations))
    if common > 0.7 * len(durations) and len(durations) >= 8:
        issues.append("Almost every note has the same length, so the line plods. Mix long notes with "
                      "shorter ones and give it one recognisable rhythm.")

    low, high = instrument.singing_for(difficulty)
    outside = [n for n in notes if not low <= n[1] <= high]
    if len(outside) > 0.3 * len(notes):
        issues.append(f"Much of the line sits outside the {instrument.name}'s singing register "
                      f"({_name(low)} to {_name(high)}); move it there.")

    peak = max(midi for _bar, midi, _size in notes)
    if sum(midi == peak for _bar, midi, _size in notes) > 2:
        issues.append(f"The top note {_name(peak)} comes back {sum(midi == peak for _b, midi, _s in notes)} "
                      "times. Give the solo one high point, reached once.")

    if instrument.section in WINDS:
        run = longest = 0
        for _bar, midi, size, _fresh in events:
            run = 0 if midi is None else run + size
            longest = max(longest, run)
        if longest > 4 * length:
            issues.append("A wind player gets no breath for more than four bars. Put a short rest or a "
                          "breath after a phrase ending.")

    last = notes[-1]
    if last[2] < musicxml.DIVISIONS:
        issues.append(f"The solo ends on a short note ({_name(last[1])} in bar {last[0]}). End its last "
                      "phrase on a held note.")
    return issues
