"""Aura Score — describe the music you want, get an orchestral score back.

Sign-in is split across the two halves of Firebase on purpose: the browser runs email/password auth with the Web SDK,
because that is the only side allowed to, then hands the resulting ID token to
/api/session. The Admin SDK checks it once and the answer becomes an ordinary
Flask session cookie. Every later request is a plain server-side session check.

Secrets live in .env (see .env.example), never in this file.
"""

import functools
import logging
import os
import sys

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import firebase_setup
import jobs
import library
import orchestra
import score_service

load_dotenv()
# Plain messages: werkzeug's request lines and the per-score log line read as-is.
logging.basicConfig(level=logging.INFO, format="%(message)s")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "dev-only-not-for-production"
# Cookies are not scoped by port, so every Aura app on localhost would otherwise
# share one "session" cookie and keep signing each other out.
app.config["SESSION_COOKIE_NAME"] = "aura_score_session"
# The forms carry no CSRF token, so the cookie itself has to refuse to travel
# on cross-site requests. Lax still allows ordinary inbound links.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

if not os.environ.get("FLASK_SECRET_KEY"):
    print(
        "[Aura Score] FLASK_SECRET_KEY 가 없어 개발용 임시 키를 씁니다.\n"
        '  python3 -c "import secrets; print(secrets.token_hex(32))" 로 만들어 .env 에 넣으세요.',
        file=sys.stderr,
    )


def current_user():
    """The signed-in user as stored in the session cookie, or None."""
    uid = session.get("uid")
    if not uid:
        return None
    return {"uid": uid, "name": session.get("name", "익명"), "email": session.get("email", "")}


def login_required(view):
    """Guard for anything personal. HTML routes bounce to /login, API routes 401."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "로그인이 필요합니다."}), 401
            flash("로그인이 필요한 기능입니다.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals():
    return {
        "user": current_user(),
        "setup_steps": firebase_setup.setup_steps() + score_service.setup_steps(),
        "firebase_config": firebase_setup.web_config(),
        "firebase_ready": firebase_setup.web_config_ready(),
    }


@app.route("/")
def index():
    return render_template("index.html", active_nav="home")


# ---------------------------------------------------------------- scores

@app.route("/scores/new")
@login_required
def new_score():
    """No mode yet: ask how the person wants to describe the piece. Then the form for it."""
    mode = request.args.get("mode")
    if mode not in ("simple", "detailed"):
        mode = None
    return render_template("new_score.html", orchestra=orchestra, mode=mode, active_nav="new")


@app.route("/api/scores", methods=["POST"])
@login_required
def api_create_score():
    """Start writing a score. Answers at once with a job id; writing takes minutes."""
    payload = request.get_json(silent=True) or {}
    try:
        brief = orchestra.read_request(payload)
    except ValueError as failure:
        return jsonify({"error": str(failure)}), 400
    if not os.environ.get("OPENAI_API_KEY"):
        return jsonify({"error": "OPENAI_API_KEY 가 없어 악보를 만들 수 없습니다. .env 를 채워 주세요."}), 503

    uid = current_user()["uid"]

    def work(progress):
        score, plan = score_service.generate(brief, progress)
        progress("내 악보에 저장하는 중")
        try:
            score["id"] = library.save(uid, payload, brief, plan, score)
        except firebase_setup.FirebaseError as failure:
            # The piece is still worth showing; say why it was not kept.
            score["save_error"] = str(failure)
        return score

    job = jobs.start(uid, work, score_service.ScoreServiceError)
    return jsonify({"job": job}), 202


@app.route("/api/scores/<job_id>")
@login_required
def api_score_status(job_id):
    """Where a job has got to; the finished score once it is done."""
    report = jobs.status(job_id, current_user()["uid"])
    if report is None:
        return jsonify({"error": "이 작업을 찾을 수 없습니다. 서버가 다시 켜졌다면 처음부터 만들어 주세요."}), 404
    return jsonify(report)


# ---------------------------------------------------------------- my scores

@app.template_filter("clock")
def clock(seconds):
    """302 -> "5분 2초"."""
    seconds = int(seconds or 0)
    return f"{seconds}초" if seconds < 60 else f"{seconds // 60}분 {seconds % 60}초"


@app.route("/scores")
@login_required
def my_scores():
    scores, load_error = [], None
    try:
        scores = library.listing(current_user()["uid"])
    except firebase_setup.FirebaseError as failure:
        load_error = str(failure)
    return render_template("library.html", scores=scores, load_error=load_error, active_nav="library")


@app.route("/scores/<score_id>")
@login_required
def saved_score(score_id):
    """The page for one saved piece; its score is fetched from the API below."""
    return render_template("score.html", score_id=score_id, active_nav="library")


@app.route("/api/library/<score_id>")
@login_required
def api_saved_score(score_id):
    try:
        score = library.open_score(current_user()["uid"], score_id)
    except firebase_setup.FirebaseError as failure:
        return jsonify({"error": str(failure)}), 503
    except (ValueError, KeyError) as failure:
        app.logger.warning("saved score %s could not be rebuilt: %s", score_id, failure)
        return jsonify({"error": "저장된 악보를 다시 만들지 못했습니다."}), 500
    if score is None:
        return jsonify({"error": "이 악보를 찾을 수 없습니다."}), 404
    return jsonify(score)


@app.route("/scores/<score_id>/delete", methods=["POST"])
@login_required
def delete_score(score_id):
    try:
        removed = library.delete(current_user()["uid"], score_id)
    except firebase_setup.FirebaseError as failure:
        flash(str(failure), "error")
        return redirect(url_for("saved_score", score_id=score_id))
    flash("악보를 삭제했습니다." if removed else "이미 없는 악보입니다.", "ok")
    return redirect(url_for("my_scores"))


# ---------------------------------------------------------------- auth

@app.route("/signup")
def signup():
    if current_user():
        return redirect(url_for("index"))
    return render_template("signup.html", active_nav="signup")


@app.route("/login")
def login():
    if current_user():
        return redirect(url_for("index"))
    return render_template("login.html", active_nav="login")


@app.route("/api/session", methods=["POST"])
def api_session():
    """Trade a Firebase ID token for a Flask session. The browser calls this
    right after sign-in, and then signs itself back out — the cookie is the
    only piece of login state that outlives the request."""
    payload = request.get_json(silent=True) or {}
    id_token = payload.get("idToken", "")
    if not id_token:
        return jsonify({"error": "인증 토큰이 없습니다."}), 400

    try:
        account = firebase_setup.verify_id_token(id_token)
    except firebase_setup.FirebaseError as failure:
        return jsonify({"error": str(failure)}), 401

    session.clear()
    session.permanent = True
    session["uid"] = account["uid"]
    session["name"] = account["name"]
    session["email"] = account["email"]
    return jsonify({"ok": True, "name": account["name"]})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("로그아웃했습니다.", "ok")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="찾을 수 없는 페이지입니다."), 404


if __name__ == "__main__":
    # macOS holds 5000 for AirPlay and Music Aura sits on 5001, so default to 5002.
    app.run(debug=True, port=int(os.environ.get("PORT", 5002)))
