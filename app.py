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
    """Form in, finished MusicXML out. Takes as long as GPT takes — a minute or two."""
    try:
        brief = orchestra.read_request(request.get_json(silent=True) or {})
    except ValueError as failure:
        return jsonify({"error": str(failure)}), 400

    try:
        return jsonify(score_service.generate(brief))
    except score_service.ScoreServiceError as failure:
        return jsonify({"error": str(failure)}), 502


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
