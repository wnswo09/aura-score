"""What can go in a score, and what each choice on the forms means.

There are two ways in. The simple form asks for a composer style, a mood, a
speed and a length, and the style decides the orchestra. The detailed form asks
for everything: how many players on each part, key, meter, tempo, form. Both
end up as the same Request, so the prompt and the MusicXML writer only ever
see one shape.

Pitches are MIDI numbers at concert pitch (middle C = 60). The score is written
in C, so only the octave-transposing instruments are written anywhere other
than where they sound.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    id: str
    ko: str                 # label on the form
    name: str               # part name in the score
    abbr: str
    section: str
    low: int                # full range, sounding
    high: int
    easy_low: int           # comfortable range, used for beginners
    easy_high: int
    clefs: tuple            # candidates; the writer picks by where the part sits
    max_players: int        # the most the detailed form offers
    numbered: bool = False  # "Flute 1·2" when several players share the staff
    octave: int = 0         # written = sounding + 12 * octave
    midi_program: int = 1
    sound: str = ""         # General MIDI soundfont name for playback

    def range_for(self, difficulty):
        if difficulty == "beginner":
            return self.easy_low, self.easy_high
        return self.low, self.high


# Score order, top to bottom. Strings count a whole section; everything else
# counts players sharing one staff.
INSTRUMENTS = [
    Instrument("piccolo", "피콜로", "Piccolo", "Picc.", "woodwind", 74, 108, 74, 96,
               ("G",), 1, octave=-1, midi_program=73, sound="piccolo"),
    Instrument("flute", "플루트", "Flute", "Fl.", "woodwind", 60, 96, 60, 91,
               ("G",), 3, numbered=True, midi_program=74, sound="flute"),
    Instrument("oboe", "오보에", "Oboe", "Ob.", "woodwind", 58, 91, 60, 86,
               ("G",), 3, numbered=True, midi_program=69, sound="oboe"),
    Instrument("clarinet", "클라리넷", "Clarinet", "Cl.", "woodwind", 50, 91, 52, 82,
               ("G",), 3, numbered=True, midi_program=72, sound="clarinet"),
    Instrument("bassoon", "바순", "Bassoon", "Bsn.", "woodwind", 34, 75, 36, 67,
               ("F", "C4"), 3, numbered=True, midi_program=71, sound="bassoon"),
    Instrument("horn", "호른", "Horn", "Hn.", "brass", 35, 77, 48, 72,
               ("G", "F"), 4, numbered=True, midi_program=61, sound="french_horn"),
    Instrument("trumpet", "트럼펫", "Trumpet", "Tpt.", "brass", 52, 82, 55, 77,
               ("G",), 3, numbered=True, midi_program=57, sound="trumpet"),
    Instrument("trombone", "트롬본", "Trombone", "Tbn.", "brass", 40, 72, 41, 65,
               ("F", "C4"), 3, numbered=True, midi_program=58, sound="trombone"),
    Instrument("tuba", "튜바", "Tuba", "Tba.", "brass", 26, 65, 29, 58,
               ("F",), 1, midi_program=59, sound="tuba"),
    Instrument("timpani", "팀파니", "Timpani", "Timp.", "percussion", 38, 57, 38, 57,
               ("F",), 1, midi_program=48, sound="timpani"),
    Instrument("violin1", "제1바이올린", "Violin I", "Vln. I", "strings", 55, 100, 55, 83,
               ("G",), 20, midi_program=41, sound="violin"),
    Instrument("violin2", "제2바이올린", "Violin II", "Vln. II", "strings", 55, 96, 55, 79,
               ("G",), 20, midi_program=41, sound="violin"),
    # Always alto: one clef serves the whole part, and a violist reads a high
    # melody in alto far more easily than low accompaniment in treble.
    Instrument("viola", "비올라", "Viola", "Vla.", "strings", 48, 88, 48, 74,
               ("C3",), 16, midi_program=42, sound="viola"),
    Instrument("cello", "첼로", "Cello", "Vc.", "strings", 36, 81, 36, 64,
               ("F", "C4"), 14, midi_program=43, sound="cello"),
    Instrument("contrabass", "콘트라베이스", "Contrabass", "Cb.", "strings", 28, 62, 28, 50,
               ("F",), 10, octave=1, midi_program=44, sound="contrabass"),
]
BY_ID = {instrument.id: instrument for instrument in INSTRUMENTS}
STRINGS = [instrument for instrument in INSTRUMENTS if instrument.section == "strings"]
WINDS = [instrument for instrument in INSTRUMENTS if instrument.section != "strings"]

SECTIONS = [
    ("woodwind", "목관"),
    ("brass", "금관"),
    ("percussion", "타악"),
    ("strings", "현악"),
]

# From this many players, a string section is told it may divide three ways.
DIVISI_A3 = 10
# From this many players, playback uses the string-ensemble sample instead of a
# solo instrument: one violin sample playing for sixteen sounds like one violin.
SECTION_SOUND_FROM = 4
SECTION_SOUND = "string_ensemble_1"


@dataclass(frozen=True)
class Part:
    """One staff in the score: an instrument and how many play it."""
    instrument: Instrument
    players: int

    @property
    def max_notes(self):
        section = self.instrument.section
        if section == "strings":
            if self.instrument.id == "contrabass":
                return 1 if self.players == 1 else 2
            return 3 if self.players >= DIVISI_A3 else 2
        if section == "percussion":
            return 2  # two mallets
        return self.players

    @property
    def name(self):
        if not self.instrument.numbered or self.players == 1:
            return self.instrument.name
        if self.players == 4:
            return f"{self.instrument.name} 1–4"
        return self.instrument.name + " " + "·".join(str(n) for n in range(1, self.players + 1))

    @property
    def sound(self):
        if self.instrument.section == "strings" and self.players >= SECTION_SOUND_FROM:
            return SECTION_SOUND
        return self.instrument.sound

    def describe(self):
        """How the prompt introduces this part."""
        notes = self.max_notes
        if self.instrument.section == "strings":
            who = "one solo player" if self.players == 1 else f"a section of {self.players}"
            if notes == 1:
                limit = "one note at a time"
            elif self.players == 1:
                limit = "up to 2 notes at once (double stops)"
            else:
                limit = f"up to {notes} notes at once (divisi)"
        else:
            who = "one player" if self.players == 1 else f"{self.players} players on one staff"
            limit = "one note at a time" if notes == 1 else f"up to {notes} notes at once"
        return f"{who}, {limit}"


def parts_from(counts):
    """{instrument id: players} -> Parts in score order, skipping zeros."""
    return [
        Part(instrument, counts[instrument.id])
        for instrument in INSTRUMENTS
        if counts.get(instrument.id, 0) > 0
    ]


def summary(counts):
    """{id: players} -> '플루트 2 · 호른 4 · 팀파니 · 현악 10-8-6-5-3 (총 44명)', for the form."""
    winds = [
        instrument.ko + ("" if instrument.max_players == 1 else f" {counts[instrument.id]}")
        for instrument in WINDS if counts.get(instrument.id)
    ]
    strings = [str(counts.get(instrument.id, 0)) for instrument in STRINGS]
    if any(count != "0" for count in strings):
        winds.append("현악 " + "-".join(strings))
    return " · ".join(winds) + f" (총 {sum(counts.values())}명)"


def _counts(winds="", strings=(0, 0, 0, 0, 0)):
    """'flute:2 oboe:2' and (vn1, vn2, va, vc, cb) -> {id: players}."""
    counts = {name: int(n) for name, n in (item.split(":") for item in winds.split())}
    counts.update(zip([instrument.id for instrument in STRINGS], strings))
    return counts


@dataclass(frozen=True)
class Choice:
    id: str
    label: str
    hint: str       # shown on the form
    prompt: str     # what GPT is told


@dataclass(frozen=True)
class Style:
    id: str
    label: str
    hint: str
    prompt: str
    orchestra: dict  # what the simple form plays it with


STYLES = [
    Style("baroque", "바로크", "바흐 · 헨델",
          "Baroque, in the manner of J. S. Bach and Handel: continuous motor rhythms, "
          "functional harmony with sequences, contrapuntal lines and imitation, terraced "
          "dynamics (sudden changes rather than long crescendos), trumpets and timpani for "
          "festive moments.",
          _counts("oboe:2 bassoon:1 trumpet:2 timpani:1", (6, 5, 4, 3, 2))),
    Style("classical", "고전", "모차르트 · 하이든",
          "Classical, in the manner of Mozart and Haydn: elegant 4+4 periodic phrases, a "
          "singable melody over light accompaniment (Alberti-like figures, repeated notes), "
          "transparent texture, clear cadences, winds for color and doubling.",
          _counts("flute:2 oboe:2 clarinet:2 bassoon:2 horn:2 trumpet:2 timpani:1",
                  (10, 8, 6, 5, 3))),
    Style("beethoven", "베토벤", "영웅적 · 극적",
          "Beethoven: bold development of a short motif, strong accents and sforzandi, "
          "dramatic dynamic contrasts, driving rhythm, heroic horns, trumpets and timpani.",
          _counts("flute:2 oboe:2 clarinet:2 bassoon:2 horn:2 trumpet:2 timpani:1",
                  (12, 10, 8, 6, 4))),
    Style("romantic", "낭만", "차이콥스키 · 드보르자크",
          "Late Romantic, in the manner of Tchaikovsky and Dvořák: sweeping lyrical melody "
          "in the strings, rich chromatic harmony, long crescendos to full-orchestra climaxes, "
          "expressive woodwind solos, powerful brass.",
          _counts("piccolo:1 flute:2 oboe:2 clarinet:2 bassoon:2 horn:4 trumpet:2 "
                  "trombone:3 tuba:1 timpani:1", (14, 12, 10, 8, 6))),
    Style("impressionist", "인상주의", "드뷔시 · 라벨",
          "Impressionist, in the manner of Debussy and Ravel: colorful, blurred harmony "
          "(added sixths and ninths, whole-tone and pentatonic touches, parallel chords), "
          "mostly soft dynamics, flowing rhythm, woodwind solos over divided strings.",
          _counts("flute:3 oboe:2 clarinet:2 bassoon:2 horn:4 trumpet:2 timpani:1",
                  (16, 14, 12, 10, 8))),
    Style("film", "영화음악", "존 윌리엄스 · 한스 짐머",
          "Modern film score, in the manner of John Williams and Hans Zimmer: a memorable "
          "heroic theme, broad brass statements, driving string ostinatos, big dynamic arcs "
          "toward a cinematic climax.",
          _counts("piccolo:1 flute:2 oboe:2 clarinet:2 bassoon:2 horn:4 trumpet:3 "
                  "trombone:3 tuba:1 timpani:1", (16, 14, 12, 10, 8))),
    Style("game", "게임·애니 OST", "히사이시 조 · 우에마츠 노부오",
          "Game and anime soundtrack, in the manner of Joe Hisaishi and Nobuo Uematsu: warm, "
          "nostalgic, singable melody; simple diatonic harmony with pop-influenced "
          "progressions (IV-V-iii-vi is a place to start, not a loop to stay in); gentle "
          "arpeggiated accompaniment in the strings; an emotional build.",
          _counts("flute:2 oboe:1 clarinet:2 bassoon:1 horn:4 trumpet:2 trombone:2 timpani:1",
                  (10, 8, 6, 6, 4))),
]
STYLE_BY_ID = {style.id: style for style in STYLES}

# Simple form: the style picks the instruments, the size picks the numbers.
SIMPLE_SIZES = [
    Choice("style", "스타일에 맞게", "그 시대의 편성", ""),
    Choice("small", "작게", "실내악 · 10명 안팎",
           "A chamber-sized group of soloists: keep textures transparent; every line is exposed."),
    Choice("medium", "중간", "체임버 · 30명 안팎",
           "A chamber orchestra: light, agile textures with room for solos."),
    Choice("large", "크게", "풀 오케스트라 · 60명 이상",
           "A full symphony orchestra: use its weight and color for the climaxes."),
]
SIMPLE_SIZE_BY_ID = {choice.id: choice for choice in SIMPLE_SIZES}
DEFAULT_SIMPLE_SIZE = "style"
SIZE_STRINGS = {"small": (1, 1, 1, 1, 1), "medium": (6, 5, 4, 3, 2), "large": (16, 14, 12, 10, 8)}


def scaled(counts, size):
    """A style's orchestra at another size. The instruments stay the style's own;
    only a big orchestra adds horns and timpani if the style had none."""
    if size == "style":
        return dict(counts)
    resized = dict(zip([instrument.id for instrument in STRINGS], SIZE_STRINGS[size]))
    for instrument in WINDS:
        players = counts.get(instrument.id, 0)
        if size == "small":
            # Soloists: one of each woodwind and horn the style uses.
            keep = (instrument.section == "woodwind" and instrument.id != "piccolo") or instrument.id == "horn"
            resized[instrument.id] = min(players, 1) if keep else 0
        elif size == "medium":
            keep = instrument.id not in ("piccolo", "trombone", "tuba")
            resized[instrument.id] = min(players, 2) if keep else 0
        else:
            # Every section at symphonic strength.
            floor = {"horn": 4, "timpani": 1}.get(
                instrument.id, 2 if players and instrument.numbered else players
            )
            resized[instrument.id] = min(max(players, floor), instrument.max_players)
    return resized


def simple_orchestras():
    """{style: {size: {summary, instruments}}} — the simple form shows the orchestra
    it will get, and offers only those instruments as the lead."""
    def describe(counts):
        return {
            "summary": summary(counts),
            "instruments": [[instrument.id, instrument.ko] for instrument in can_lead(parts_from(counts))],
        }

    return {
        style.id: {size.id: describe(scaled(style.orchestra, size.id)) for size in SIMPLE_SIZES}
        for style in STYLES
    }

# Detailed form: buttons that fill in the player counts.
PRESETS = [
    ("classical", "고전 2관", _counts(
        "flute:2 oboe:2 clarinet:2 bassoon:2 horn:2 trumpet:2 timpani:1", (10, 8, 6, 5, 3))),
    ("romantic", "낭만 3관", STYLE_BY_ID["romantic"].orchestra),
    ("strings", "현악 합주", _counts("", (8, 7, 6, 5, 3))),
    ("quartet", "현악 4중주", _counts("", (1, 1, 1, 1, 0))),
    ("winds", "목관 5중주", _counts("flute:1 oboe:1 clarinet:1 bassoon:1 horn:1")),
    ("brass", "금관 5중주", _counts("horn:1 trumpet:2 trombone:1 tuba:1")),
]
DEFAULT_PRESET = "classical"
DEFAULT_COUNTS = dict(PRESETS[0][2])

DIFFICULTIES = [
    Choice("beginner", "초급", "학생·입문 합주",
           "Beginner (school or amateur players): no durations shorter than an eighth note, "
           "no syncopation, mostly stepwise motion with small leaps, comfortable middle register, "
           "few accidentals, parts moving in similar rhythms."),
    Choice("intermediate", "중급", "아마추어 오케스트라",
           "Intermediate (community orchestra): short sixteenth-note runs, dotted rhythms, "
           "moderate leaps, the standard register, occasional accidentals."),
    Choice("advanced", "고급", "음대·세미프로",
           "Advanced (conservatory level): syncopation, fast passagework, wide register, "
           "chromatic color, independent lines."),
    Choice("professional", "전문가", "프로 오케스트라",
           "Professional orchestra: no technical limits; virtuosic writing is welcome "
           "wherever it serves the music."),
]
DIFFICULTY_BY_ID = {choice.id: choice for choice in DIFFICULTIES}
DEFAULT_DIFFICULTY = "intermediate"
# Most sharps or flats GPT may pick for the key signature, by difficulty.
MAX_FIFTHS = {"beginner": 2, "intermediate": 4, "advanced": 6, "professional": 6}

FORMS = [
    Choice("", "맡기기", "", ""),
    Choice("a", "한 도막 (A)", "", "One continuous section (A) developing a single idea."),
    Choice("ab", "두 도막 (AB)", "", "Binary form (A B): two contrasting halves."),
    Choice("aba", "세 도막 (ABA)", "", "Ternary form (A B A): a contrasting middle, then the "
           "opening returns."),
    Choice("rondo", "론도 (ABACA)", "", "Rondo (A B A C A): a refrain alternating with two "
           "contrasting episodes."),
]
FORM_BY_ID = {choice.id: choice for choice in FORMS}

# What a section is for and how thick it is. GPT plans the piece in these terms
# before writing a note; the page shows the plan with the Korean labels.
ROLES = {
    "intro": "도입", "theme": "주제", "contrast": "대비", "development": "전개",
    "solo": "솔로", "climax": "절정", "return": "재현", "coda": "종결",
}
TEXTURES = {"solo": "독주", "thin": "얇게", "medium": "중간", "full": "전체 합주"}
# What the instruments under the melody do. Left to itself GPT keeps one figure
# going for the whole piece, so the plan has to name one per section.
ACCOMPANIMENTS = {
    "sustained": "긴 화음", "arpeggio": "펼침화음", "repeated": "같은 음 반복",
    "offbeat": "엇박", "pedal": "지속음", "countermelody": "대선율", "none": "반주 없음",
}
# From this length on, the lead instrument gets a solo passage.
SOLO_FROM = 16
# Where the solo and the climax fall. Given the same instructions every time, GPT
# settles on one layout (theme, contrast, solo, climax, return, coda) for every
# piece, so each request is handed one of these at random.
SHAPES = [
    "Arch. Open quietly, build to the climax about two thirds of the way through, and "
    "close quietly. The solo comes before the build begins.",
    "The lead begins alone. The piece opens with the solo; the orchestra gathers around "
    "it section by section, and the climax comes late, leaving room for a proper close.",
    "After the storm. The climax arrives around the middle. The solo follows it as a quiet "
    "reflection, and the theme returns transformed to end the piece.",
    "Dialogue. The lead and one other instrument trade the melody all the way through. The "
    "solo is a free, cadenza-like passage just before the final return, and the climax is "
    "that return.",
    "Slow burn. One long growth from almost nothing to a climax late in the piece. The solo "
    "is an early, hushed statement of the theme; after the climax the music takes its time "
    "to come to rest.",
    "Two worlds. Two contrasting ideas, one restless and one calm, alternate and finally "
    "combine at the climax about three quarters through. The solo is the bridge between them.",
]


@dataclass(frozen=True)
class Ending:
    """How a piece comes to rest. GPT picks one; the score marks it and the
    playback performs it, because notes alone played in strict time just stop."""
    id: str
    label: str              # on the page
    mark: str               # above the top staff where the slowing starts; "" for none
    measures: int           # how many measures before the final chord the slowing starts
    slow_to: float          # tempo the final chord is reached at, as a share of the tempo
    chord: tuple            # (shortest, longest) the final chord sounds, in seconds
    fermata: bool
    fade: tuple             # (how far into the final chord it starts dying away, level it reaches)


# The final chord's length is set in seconds, not beats: one written measure is
# under two seconds at Allegro and nearly five at Adagio, and GPT may hold the
# chord for one measure or two.
ENDINGS = [
    Ending("slowing", "느려지며 맺음", "rit.", 2, 0.62, (4.0, 6.0), True, (0.4, 0.4)),
    Ending("fading", "사라지듯 맺음", "rit. e dim.", 2, 0.58, (5.0, 7.0), True, (0.0, 0.12)),
    Ending("firm", "힘 있게 맺음", "", 1, 0.88, (3.0, 4.5), False, (0.6, 0.7)),
]
ENDING_BY_ID = {ending.id: ending for ending in ENDINGS}
DEFAULT_ENDING = "slowing"


def length_range(length):
    """The requested length is a target: (fewest, most) measures GPT may use, so
    it can give the ending the room it needs instead of stopping on a count."""
    slack = max(2, length // 8)
    return max(2, length - slack), length + slack


def sections_for(length):
    """How many sections a piece of this length should be planned in: (fewest, most)."""
    for longest, span in [(8, (1, 2)), (15, (2, 3)), (23, (3, 4)), (32, (4, 6))]:
        if length <= longest:
            return span
    return 6, 8

# Simple form: three speeds, three lengths.
SPEEDS = [
    Choice("slow", "느리게", "Adagio", "66"),
    Choice("medium", "보통", "Moderato", "100"),
    Choice("fast", "빠르게", "Allegro", "138"),
]
LENGTHS = [
    Choice("8", "짧게", "8마디", ""),
    Choice("16", "보통", "16마디", ""),
    Choice("32", "길게", "32마디", ""),
]
DEFAULT_SPEED = "medium"
DEFAULT_LENGTH = "16"

# Detailed form: exact numbers.
BARS_MIN, BARS_MAX, BARS_DEFAULT = 4, 48, 16
BPM_MIN, BPM_MAX, BPM_DEFAULT = 40, 200, 80
# Tempo words by the lowest BPM they cover.
TEMPO_TERMS = [(0, "Largo"), (60, "Adagio"), (76, "Andante"), (100, "Moderato"),
               (120, "Allegro"), (156, "Presto")]

MOODS = ["웅장한", "서정적인", "긴장감 있는", "밝고 경쾌한", "슬픈", "신비로운", "평화로운", "비장한"]
SIMPLE_MOODS_MAX = 2


@dataclass(frozen=True)
class Tempo:
    term: str
    bpm: int        # quarter notes per minute


def tempo_for(bpm):
    term = [word for floor, word in TEMPO_TERMS if bpm >= floor][-1]
    return Tempo(term, bpm)


# (label, fifths, mode). Seven sharps or flats are left out on purpose.
KEYS = [
    *[(f"{name} major", fifths, "major") for name, fifths in [
        ("Gb", -6), ("Db", -5), ("Ab", -4), ("Eb", -3), ("Bb", -2), ("F", -1), ("C", 0),
        ("G", 1), ("D", 2), ("A", 3), ("E", 4), ("B", 5), ("F#", 6)]],
    *[(f"{name} minor", fifths, "minor") for name, fifths in [
        ("Eb", -6), ("Bb", -5), ("F", -4), ("C", -3), ("G", -2), ("D", -1), ("A", 0),
        ("E", 1), ("B", 2), ("F#", 3), ("C#", 4), ("G#", 5), ("D#", 6)]],
]
KEY_BY_LABEL = {label: (fifths, mode) for label, fifths, mode in KEYS}
TIME_SIGNATURES = ["4/4", "3/4", "2/4", "6/8"]

MOOD_MAX = 100
EXTRA_MAX = 500
SIMPLE_EXTRA_MAX = 200


def keys_for(difficulty):
    limit = MAX_FIFTHS[difficulty]
    return [label for label, fifths, _mode in KEYS if abs(fifths) <= limit]


@dataclass(frozen=True)
class Request:
    mode: str               # "simple" or "detailed"
    parts: list             # Part, in score order
    length: int
    difficulty: Choice
    tempo: Tempo
    key: str                # "" lets GPT choose
    time: str               # "" lets GPT choose
    form: Choice
    style: Style | None
    lead: Instrument | None  # the protagonist instrument; None lets GPT choose
    ensemble: str           # what the chosen size means for the writing; "" if none
    mood: str
    extra: str


def _number(value, low, high, what):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: 숫자로 적어 주세요.") from None
    if not low <= number <= high:
        raise ValueError(f"{what}: {low}~{high} 사이로 정해 주세요.")
    return number


def can_lead(parts):
    """The instruments a piece can be told through: anything that carries a tune.
    Timpani are left out unless there is nothing else."""
    melodic = [part.instrument for part in parts if part.instrument.section != "percussion"]
    return melodic or [part.instrument for part in parts]


def _lead(payload, parts):
    """The lead the user picked, which has to be one of the instruments playing."""
    wanted = payload.get("lead") or ""
    if not wanted:
        return None
    for instrument in can_lead(parts):
        if instrument.id == wanted:
            return instrument
    raise ValueError("주인공 악기가 편성에 없습니다. 다른 악기를 고르거나 맡기기로 바꿔 주세요.")


def _simple(payload):
    style = STYLE_BY_ID.get(payload.get("style"))
    if style is None:
        raise ValueError("작곡가 스타일을 골라 주세요.")
    moods = [mood for mood in payload.get("moods") or [] if mood in MOODS][:SIMPLE_MOODS_MAX]
    if not moods:
        raise ValueError("분위기를 한 개 이상 골라 주세요.")
    speed = next((choice for choice in SPEEDS if choice.id == payload.get("speed")), None)
    length = next((choice for choice in LENGTHS if choice.id == str(payload.get("length"))), None)
    size = SIMPLE_SIZE_BY_ID.get(payload.get("size") or DEFAULT_SIMPLE_SIZE)
    if speed is None or length is None or size is None:
        raise ValueError("규모, 빠르기, 길이를 골라 주세요.")

    parts = parts_from(scaled(style.orchestra, size.id))
    return Request(
        mode="simple",
        parts=parts,
        length=int(length.id),
        difficulty=DIFFICULTY_BY_ID[DEFAULT_DIFFICULTY],
        tempo=Tempo(speed.hint, int(speed.prompt)),
        key="",
        time="",
        form=FORM_BY_ID[""],
        style=style,
        lead=_lead(payload, parts),
        ensemble=size.prompt,
        mood=", ".join(moods),
        extra=str(payload.get("extra", "")).strip()[:SIMPLE_EXTRA_MAX],
    )


def _detailed(payload):
    wanted = payload.get("players") if isinstance(payload.get("players"), dict) else {}
    counts = {
        instrument.id: _number(wanted.get(instrument.id, 0) or 0, 0, instrument.max_players,
                               f"{instrument.ko} 인원")
        for instrument in INSTRUMENTS
    }
    parts = parts_from(counts)
    if not parts:
        raise ValueError("악기를 한 개 이상 넣어 주세요.")

    difficulty = DIFFICULTY_BY_ID.get(payload.get("difficulty"))
    form = FORM_BY_ID.get(payload.get("structure") or "")
    key = payload.get("key") or ""
    time = payload.get("time") or ""
    style_id = payload.get("style") or ""
    if (difficulty is None or form is None or key not in ("", *KEY_BY_LABEL)
            or time not in ("", *TIME_SIGNATURES) or style_id not in ("", *STYLE_BY_ID)):
        raise ValueError("입력값을 알아볼 수 없습니다. 페이지를 새로고침해 주세요.")

    return Request(
        mode="detailed",
        parts=parts,
        length=_number(payload.get("length"), BARS_MIN, BARS_MAX, "마디 수"),
        difficulty=difficulty,
        tempo=tempo_for(_number(payload.get("bpm"), BPM_MIN, BPM_MAX, "템포(BPM)")),
        key=key,
        time=time,
        form=form,
        style=STYLE_BY_ID.get(style_id),
        lead=_lead(payload, parts),
        ensemble="",
        mood=str(payload.get("mood", "")).strip()[:MOOD_MAX],
        extra=str(payload.get("extra", "")).strip()[:EXTRA_MAX],
    )


def read_request(payload):
    """Check a submitted form and turn it into a Request, or raise ValueError
    with a sentence the page can show as-is."""
    if payload.get("mode") == "simple":
        return _simple(payload)
    if payload.get("mode") == "detailed":
        return _detailed(payload)
    raise ValueError("입력 방식을 알아볼 수 없습니다. 페이지를 새로고침해 주세요.")
