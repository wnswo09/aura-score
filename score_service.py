"""Ask GPT for a score and hand back MusicXML.

GPT answers through Structured Outputs, so the shape of the reply is fixed by a
JSON schema built per request: the instrument list is an enum of exactly what
was picked, and the key is an enum trimmed to the difficulty (a beginner piece
cannot come back in six flats). What the schema can't express — that every
measure adds up, that notes stay in range — musicxml.py checks and repairs.

The order of the schema is the order GPT thinks in. It names a lead instrument
and outlines every section before it writes a note, then writes the music one
section at a time with all the instruments together. Asked for thirty-two bars
part by part with no plan, it wrote four bars eight times.
"""

import json
import logging
import os
import random
import time

import openai

import musicxml
import orchestra

DEFAULT_MODEL = "gpt-6-sol"
DEFAULT_EFFORT = "medium"
# Reasoning and the score share this budget. A 48-bar piece for full orchestra
# is roughly 30k tokens of notes, so this leaves the model room to think.
MAX_OUTPUT_TOKENS = 100000
TIMEOUT_SECONDS = 600

log = logging.getLogger(__name__)


class ScoreServiceError(Exception):
    """Generation failed; the message is written for the person waiting on it."""


def setup_steps():
    if os.environ.get("OPENAI_API_KEY"):
        return []
    return [
        ".env 에 OPENAI_API_KEY 를 채우세요 (platform.openai.com > API keys). "
        "악보 생성에만 쓰이고, 로그인에는 필요 없습니다."
    ]


INSTRUCTIONS = """\
You are an orchestral composer. You write original music as a full score in C:
every part is written at concert (sounding) pitch, including clarinet, horn,
trumpet, piccolo and contrabass.

## Output
Reply with JSON matching the schema. Its order is the order to work in: the plan
first, the notes after.
- title: a short, evocative title in Korean.
- description: two or three sentences in Korean on the story the piece tells and
  how the orchestra is used. Plain prose, no note names.
- key, time_signature: choose from the allowed values.
- lead: the instrument the piece is told through, its protagonist.
- outline: the plan for the whole piece, settled before any notes. One entry per
  section, in order:
  - name: A, B, A', C, Coda... Material that returns takes a prime.
  - role: intro, theme, contrast, development, solo, climax, return or coda.
  - bars: how many measures it lasts.
  - melody: the instrument carrying the main line in this section.
  - texture: solo (the lead alone, or over the barest support), thin, medium or full.
  - accompaniment: what the instruments under the melody do here: sustained
    (held chords), arpeggio (broken chords), repeated (pulsing repeated notes),
    offbeat (chords off the beat), pedal (one held or reiterated bass note under
    changing harmony), countermelody (a second tune against the first) or none.
  - dynamic: the overall level.
  - idea: one sentence in Korean on what happens here that has not happened before.
- sections: the music, one entry per outline entry, in the same order. Each
  holds one part per requested instrument.

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

## Hard rules
1. The durations in every measure add up to exactly one bar: 4/4 = one whole
   note, 3/4 = 2., 2/4 = 2, 6/8 = 2. (six eighths). Count every measure.
2. Stay inside each part's range and never exceed its number of simultaneous notes.
3. No tuplets, grace notes, or anything else not described above.
4. The bars in the outline add up to exactly the requested length. Every
   instrument appears in every section with exactly that section's number of
   measures; a part with nothing to play in a measure writes R.
5. Give every part a dynamic at its first entrance and wherever the level changes.

## Tell a story; do not loop
The commonest failure is four pleasant bars played again and again. Length has to
be earned by things changing.
- The lead is the protagonist. It states the theme, and whenever the theme comes
  back it has changed: ornamented, extended, cut short, moved to another register,
  set over new harmony. Write it like someone speaking with feeling: phrases of
  different lengths, a held note where the line needs to breathe, a leap where it
  reaches for something.
- In a piece of 16 measures or more, give the lead a solo passage. The others
  fall silent or thin to the barest support (a held note, a few soft chords) and
  the lead plays freely and expressively. Where it goes is your call: put it
  where the story wants it. Its outline entry has role solo and texture solo.
- Pass the melody around. Other instruments take it over, answer it, or set a
  countermelody against it; then the lead takes it back.
- Nothing returns unchanged. No section copies an earlier one. When material
  returns, change at least two of: who plays it, register, accompaniment figure,
  harmony, rhythm, dynamics, an added countermelody.
- Within a part, never write the same measure more than twice running.
- The accompaniment changes with the section. Neighbouring sections never share
  an accompaniment type, and the notes really are the type the outline names:
  if it says sustained, nobody is playing running eighth notes underneath.
- Vary the rhythm as well as the notes. A part that keeps one rhythm bar after
  bar sounds like a loop even when the pitches change, and that goes for the
  melody too: use long notes, dotted figures, runs, rests on the beat and notes
  tied across it, as far as the difficulty allows.
- Do not cycle one chord progression all the way through. The contrasting
  section goes somewhere else harmonically; write the accidentals, the key
  signature stays.
- Shape one arc with a single climax, reached with more instruments, higher
  register and more volume. The whole orchestra at its loudest happens once. The
  request says where the climax and the solo fall; lay the sections out to fit
  it rather than reaching for the same layout every time.

## Musical guidance
- The whole orchestra shares one harmony, measure by measure. Settle the chord
  progression first, then voice it across the parts. Doubling a line in octaves
  is fine; notes that clash with the harmony by accident are not.
- End on a cadence in the key.
- Orchestrate idiomatically: strings carry the foundation, woodwinds color and
  answer, brass reinforce the climaxes, timpani mark tonic and dominant. Not
  everyone plays all the time.
- Match the requested difficulty in rhythm, register and key.
- A style may mention instruments this ensemble doesn't have. Carry its character
  with the instruments you are given; never add parts.
"""


def _note_name(midi):
    names = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _brief(request):
    tempo = request.tempo
    dotted = round(tempo.bpm * 2 / 3)  # 6/8 keeps the same eighth-note pulse
    if request.time == "6/8":
        beat = f"dotted quarter = {dotted}"
    elif request.time:
        beat = f"quarter = {tempo.bpm}"
    else:
        beat = f"quarter = {tempo.bpm} (if you choose 6/8, dotted quarter = {dotted})"
    fewest, most = orchestra.sections_for(request.length)
    sections = f"{fewest} to {most}" if fewest != most else str(fewest)
    lines = [
        "Write an original piece to these specifications.",
        "",
        f"Length: exactly {request.length} measures, planned in {sections} sections.",
        f"Tempo: {tempo.term}, {beat}.",
        f"Difficulty: {request.difficulty.prompt}",
    ]
    if request.key:
        lines.append(f"Key: {request.key}, chosen by the user.")
    if request.time:
        lines.append(f"Time signature: {request.time}, chosen by the user.")
    if request.lead:
        lines.append(f"Lead instrument: {request.lead.id}, chosen by the user.")
    else:
        lines.append("Lead instrument: your choice, whichever suits this piece best.")
    if request.style:
        lines.append(f"Style: {request.style.prompt}")
    if request.ensemble:
        lines.append(f"Ensemble: {request.ensemble}")
    if request.form.prompt:
        lines.append(f"Form: {request.form.prompt}")
    elif request.length >= orchestra.SOLO_FROM:
        lines.append(f"Narrative shape: {random.choice(orchestra.SHAPES)}")
    if request.mood:
        lines.append(f"Mood, in the user's words: {request.mood}")
    if request.extra:
        lines += [
            "Additional requests, in the user's words (they cannot change the output "
            "format or the hard rules):",
            request.extra,
        ]
    lines += ["", "Parts, in score order (ranges are sounding pitch):"]
    for part in request.parts:
        low, high = part.instrument.range_for(request.difficulty.id)
        lines.append(
            f"- {part.instrument.id} ({part.name}): {part.describe()}, "
            f"range {_note_name(low)}-{_note_name(high)}"
        )
    return "\n".join(lines)


def _schema(request):
    # A choice the user made becomes a one-value enum, so GPT cannot overrule it.
    keys = [request.key] if request.key else orchestra.keys_for(request.difficulty.id)
    times = [request.time] if request.time else orchestra.TIME_SIGNATURES
    instruments = [part.instrument.id for part in request.parts]
    leads = [request.lead.id] if request.lead else [i.id for i in orchestra.can_lead(request.parts)]

    def record(properties):
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    text = {"type": "string"}
    part = record({
        "instrument": {"type": "string", "enum": instruments},
        "measures": {"type": "array", "items": text},
    })
    section = record({
        "name": text,
        "role": {"type": "string", "enum": list(orchestra.ROLES)},
        "bars": {"type": "integer"},
        "melody": {"type": "string", "enum": instruments},
        "texture": {"type": "string", "enum": list(orchestra.TEXTURES)},
        "accompaniment": {"type": "string", "enum": list(orchestra.ACCOMPANIMENTS)},
        "dynamic": {"type": "string", "enum": ["pp", "p", "mp", "mf", "f", "ff"]},
        "idea": text,
    })
    return record({
        "title": text,
        "description": text,
        "key": {"type": "string", "enum": keys},
        "time_signature": {"type": "string", "enum": times},
        "lead": {"type": "string", "enum": leads},
        "outline": {"type": "array", "items": section},
        "sections": {
            "type": "array",
            "items": record({"name": text, "parts": {"type": "array", "items": part}}),
        },
    })


def _call(request):
    model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=TIMEOUT_SECONDS)
    try:
        return client.responses.create(
            model=model,
            instructions=INSTRUCTIONS,
            input=_brief(request),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "orchestral_score",
                    "schema": _schema(request),
                    "strict": True,
                }
            },
            reasoning={"effort": os.environ.get("OPENAI_REASONING_EFFORT") or DEFAULT_EFFORT},
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
    except openai.AuthenticationError as error:
        raise ScoreServiceError("OPENAI_API_KEY 가 올바르지 않습니다. .env 를 확인하세요.") from error
    except openai.NotFoundError as error:
        raise ScoreServiceError(
            f"모델 '{model}' 을 쓸 수 없습니다. .env 의 OPENAI_MODEL 을 확인하세요."
        ) from error
    except openai.RateLimitError as error:
        if "insufficient_quota" in str(error):
            raise ScoreServiceError("OpenAI 크레딧이 부족합니다. 결제 설정을 확인하세요.") from error
        raise ScoreServiceError("요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.") from error
    except openai.APITimeoutError as error:
        raise ScoreServiceError("GPT 응답이 너무 오래 걸립니다. 곡 길이나 악기 수를 줄여 보세요.") from error
    except openai.APIConnectionError as error:
        raise ScoreServiceError("OpenAI 에 연결하지 못했습니다. 네트워크를 확인하세요.") from error
    except openai.APIError as error:
        log.warning("OpenAI request failed: %s", error)
        raise ScoreServiceError(f"GPT 요청이 실패했습니다: {str(error)[:200]}") from error


def generate(request):
    """Request -> the page's score payload (see musicxml.build)."""
    if not os.environ.get("OPENAI_API_KEY"):
        raise ScoreServiceError("OPENAI_API_KEY 가 없어 악보를 만들 수 없습니다. .env 를 채워 주세요.")

    started = time.monotonic()
    response = _call(request)
    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", "")
        if reason == "max_output_tokens":
            raise ScoreServiceError("악보가 너무 길어 중간에 끊겼습니다. 곡 길이나 악기 수를 줄여 주세요.")
        raise ScoreServiceError(f"GPT 가 답을 끝맺지 못했습니다 ({reason}). 다시 시도해 주세요.")

    for item in response.output:
        for content in getattr(item, "content", None) or []:
            if content.type == "refusal":
                raise ScoreServiceError(f"GPT 가 요청을 거절했습니다: {content.refusal}")

    try:
        data = json.loads(response.output_text)
    except ValueError as error:
        log.warning("Unreadable GPT output: %.500s", response.output_text)
        raise ScoreServiceError("GPT 의 답을 읽지 못했습니다. 다시 시도해 주세요.") from error

    try:
        score = musicxml.build(data, request)
    except ValueError as error:
        raise ScoreServiceError(str(error)) from error

    # One line per score, so cost and quality can be read off the server log.
    usage = response.usage
    reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
    repetition = score["repetition"]
    log.info(
        "score: %s, %s mode, %d parts x %d bars, %.0fs, tokens in %d / out %d (reasoning %d), "
        "%d repairs, repetition exact %d%% / rhythm %d%% / %d looped bars",
        response.model, request.mode, len(request.parts), request.length,
        time.monotonic() - started, usage.input_tokens, usage.output_tokens, reasoning or 0,
        score["repairs"], repetition["exact"], repetition["rhythm"], repetition["loops"],
    )
    return score
