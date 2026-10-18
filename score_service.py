"""Ask GPT for a score and hand back MusicXML.

A piece is written in two stages. One call plans the whole piece: chapters
with their own tempo and key, sections inside them, and the themes written out
in notes. Then every chapter is written by a call of its own, all at once, from
that plan, and musicxml.py joins them into one score. Asked for a long piece in
a single reply, GPT ran out of ideas and circled back; asked for one chapter at a
time against a plan, it only has to make that chapter good.

Every reply comes through Structured Outputs, with a JSON schema built per
request (prompts.py). What a schema can't express — that every measure adds up,
that notes stay in range — musicxml.py checks and repairs.
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import openai

import musicxml
import orchestra
import prompts

DEFAULT_MODEL = "gpt-6-sol"
# The plan decides what the whole piece is, so it gets to think harder.
PLAN_EFFORT = "high"
CHAPTER_EFFORT = "medium"
PLAN_TOKENS = 40000
CHAPTER_TOKENS = 60000
TIMEOUT_SECONDS = 600
# How many chapters are written at once.
PARALLEL = 6
# Sanity limits on a plan; anything past them is a plan gone wrong.
MAX_CHAPTERS = 12
MAX_SECTION_BARS = 64

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


def _respond(name, instructions, brief, schema, effort, budget):
    """One structured call -> (parsed JSON, usage). Raises ScoreServiceError."""
    model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"), timeout=TIMEOUT_SECONDS)
    try:
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=brief,
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
            reasoning={"effort": effort},
            max_output_tokens=budget,
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

    if response.status == "incomplete":
        reason = getattr(response.incomplete_details, "reason", "")
        if reason == "max_output_tokens":
            raise ScoreServiceError("GPT 의 답이 너무 길어 중간에 끊겼습니다. 곡 길이나 악기 수를 줄여 주세요.")
        raise ScoreServiceError(f"GPT 가 답을 끝맺지 못했습니다 ({reason}). 다시 시도해 주세요.")
    for item in response.output:
        for content in getattr(item, "content", None) or []:
            if content.type == "refusal":
                raise ScoreServiceError(f"GPT 가 요청을 거절했습니다: {content.refusal}")
    try:
        return json.loads(response.output_text), response.usage
    except ValueError as error:
        log.warning("Unreadable GPT output: %.500s", response.output_text)
        raise ScoreServiceError("GPT 의 답을 읽지 못했습니다. 다시 시도해 주세요.") from error


def _usable(plan):
    """Keep the chapters and sections a writer can actually work from."""
    chapters = []
    for chapter in plan.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        sections = []
        for section in chapter.get("sections") or []:
            if not isinstance(section, dict):
                continue
            try:
                bars = int(section.get("bars"))
            except (TypeError, ValueError):
                continue
            if bars > 0:
                sections.append({**section, "bars": min(bars, MAX_SECTION_BARS)})
        if sections:
            chapters.append({**chapter, "sections": sections, "tempo": orchestra.tempo_for(chapter.get("tempo")).bpm})
    return chapters[:MAX_CHAPTERS]


def _write(request, plan, index):
    """Write one chapter, with one more try if the first reply is unusable."""
    for attempt in (1, 2):
        try:
            return _respond(
                "orchestral_chapter", prompts.CHAPTER, prompts.chapter_brief(request, plan, index),
                prompts.chapter_schema(request), os.environ.get("OPENAI_REASONING_EFFORT") or CHAPTER_EFFORT,
                CHAPTER_TOKENS,
            )
        except ScoreServiceError as error:
            if attempt == 2:
                raise ScoreServiceError(f"{index + 1}장을 쓰지 못했습니다: {error}") from error
            log.warning("chapter %d failed, retrying: %s", index + 1, error)


def generate(request, progress=lambda text: None):
    """Request -> the page's score payload (see musicxml.build).

    `progress` is called with a sentence for the person waiting, at each stage.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        raise ScoreServiceError("OPENAI_API_KEY 가 없어 악보를 만들 수 없습니다. .env 를 채워 주세요.")
    started = time.monotonic()
    tokens_in = tokens_out = 0

    progress("곡 전체를 설계하는 중 (장 구성, 템포와 조성, 주제 선율)")
    plan, usage = _respond(
        "orchestral_plan", prompts.PLAN, prompts.plan_brief(request), prompts.plan_schema(request),
        os.environ.get("OPENAI_PLAN_EFFORT") or PLAN_EFFORT, PLAN_TOKENS,
    )
    tokens_in, tokens_out = usage.input_tokens, usage.output_tokens
    plan["chapters"] = _usable(plan)
    count = len(plan["chapters"])
    if not count:
        raise ScoreServiceError("GPT 가 곡을 설계하지 못했습니다. 다시 시도해 주세요.")
    planned = time.monotonic() - started

    music, done = [None] * count, 0
    progress(f"{count}개 장을 동시에 쓰는 중 (0/{count} 완성)")
    with ThreadPoolExecutor(max_workers=min(count, PARALLEL)) as pool:
        jobs = {pool.submit(_write, request, plan, index): index for index in range(count)}
        for job in as_completed(jobs):
            music[jobs[job]], usage = job.result()
            tokens_in += usage.input_tokens
            tokens_out += usage.output_tokens
            done += 1
            progress(f"{count}개 장을 동시에 쓰는 중 ({done}/{count} 완성)")

    progress("악보로 옮기는 중")
    for chapter, written in zip(plan["chapters"], music):
        chapter["music"] = written
    try:
        score = musicxml.build(plan, request)
    except ValueError as error:
        raise ScoreServiceError(str(error)) from error

    # One line per score, so cost and quality can be read off the server log.
    repetition = score["repetition"]
    log.info(
        "score: %s mode, %d parts, %d chapters, %d bars, %ds of music (asked %ds), "
        "plan %.0fs + chapters %.0fs, tokens in %d / out %d, %d repairs, "
        "repetition exact %d%% / rhythm %d%% / %d looped bars",
        request.mode, len(request.parts), count, score["measures"], score["duration"],
        request.minutes * 60, planned, time.monotonic() - started - planned, tokens_in, tokens_out,
        score["repairs"], repetition["exact"], repetition["rhythm"], repetition["loops"],
    )
    return score
