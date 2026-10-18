"""Each user's saved scores ("내 악보"), in Firestore.

A score is saved as what GPT wrote — the plan with every chapter's measures —
and the form it answered, not as the finished MusicXML. A five-minute piece's
MusicXML alone is about half of Firestore's 1 MB document limit; the source,
compressed, is a few tens of kilobytes. Opening a saved piece rebuilds it with
musicxml.build, so fixes to the score writer reach old pieces too.

    score_libraries/{uid}/scores/{id}
        title, description, summary, created_at, duration, measures, chapters,
        key, time, lead, ending, mode, minutes,
        request   the form as submitted (only the fields the forms send)
        source    the plan with the music, as zlib-compressed JSON
        format    how `source` is laid out, for when that changes

One collection per user keeps listing to a single-field order, so Firestore
needs no composite index, and a user can only ever reach their own scores.
"""

import json
import zlib
from zoneinfo import ZoneInfo

from firebase_admin import firestore

import firebase_setup
import musicxml
import orchestra

FORMAT = 1
LIST_LIMIT = 100
SEOUL = ZoneInfo("Asia/Seoul")
# What the forms send. Anything else in a request body is not worth keeping.
REQUEST_FIELDS = {
    "mode", "style", "size", "lead", "moods", "speed", "minutes", "extra",
    "players", "bpm", "difficulty", "key", "time", "structure", "mood",
}
# What the list page shows; the heavy `source` stays behind.
LISTED = ["title", "summary", "created_at", "duration", "chapters", "measures", "key", "lead"]


def _scores(uid):
    return firebase_setup.db().collection("score_libraries").document(uid).collection("scores")


def _when(timestamp):
    return timestamp.astimezone(SEOUL).strftime("%Y.%m.%d %H:%M") if timestamp else ""


def summary(request):
    """One line on what was asked for, for the list."""
    if request.mode == "simple":
        return " · ".join(filter(None, [request.style.label if request.style else "", request.mood]))
    style = f" · {request.style.label}" if request.style else ""
    return f"직접 편성 {len(request.parts)}파트 · {request.difficulty.label}{style}"


def save(uid, payload, request, plan, score):
    """Keep a finished piece. Returns its id. Raises firebase_setup.FirebaseError."""
    try:
        document = _scores(uid).document()
        document.set({
            "title": score["title"],
            "description": score["description"],
            "summary": summary(request),
            "created_at": firestore.SERVER_TIMESTAMP,
            "duration": score["duration"],
            "measures": score["measures"],
            "chapters": len(score["chapters"]),
            "key": score["key"],
            "time": score["time"],
            "lead": score["lead"],
            "ending": score["ending"],
            "mode": request.mode,
            "minutes": request.minutes,
            "request": {field: value for field, value in payload.items() if field in REQUEST_FIELDS},
            "source": zlib.compress(json.dumps(plan, ensure_ascii=False).encode("utf-8")),
            "format": FORMAT,
        })
    except Exception as error:  # google.api_core raises a family of these
        raise firebase_setup.friendly(error) from error
    return document.id


def listing(uid):
    """The user's scores, newest first, without their music."""
    try:
        query = (
            _scores(uid)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .select(LISTED)
            .limit(LIST_LIMIT)
        )
        found = [(document.id, document.to_dict()) for document in query.stream()]
    except Exception as error:
        raise firebase_setup.friendly(error) from error
    return [{**fields, "id": score_id, "created": _when(fields.get("created_at"))} for score_id, fields in found]


def open_score(uid, score_id):
    """A saved piece rebuilt into the page's score payload, or None if this
    user has no such score. Raises ValueError if it can no longer be rebuilt."""
    try:
        snapshot = _scores(uid).document(score_id).get()
    except Exception as error:
        raise firebase_setup.friendly(error) from error
    if not snapshot.exists:
        return None
    saved = snapshot.to_dict()
    plan = json.loads(zlib.decompress(saved["source"]).decode("utf-8"))
    score = musicxml.build(plan, orchestra.read_request(saved["request"]))
    return {**score, "id": score_id, "created": _when(saved.get("created_at"))}


def delete(uid, score_id):
    """Remove one of the user's scores. Returns False if there was no such score."""
    try:
        document = _scores(uid).document(score_id)
        if not document.get().exists:
            return False
        document.delete()
    except Exception as error:
        raise firebase_setup.friendly(error) from error
    return True
