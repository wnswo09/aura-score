"""Firebase, for sign-in only.

Two halves of the same project are used here:
  - the Web SDK config handed to the browser, which is the only side that can
    run email/password sign-in;
  - the Admin SDK on the server, which checks the ID token the browser hands over.

Everything is looked up lazily. The pages render with no credentials at all;
only the moment of signing in insists.
"""

import json
import logging
import os

import firebase_admin
from firebase_admin import auth as admin_auth
from firebase_admin import credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Tolerance for the local clock running behind Google's. Firebase allows up to 60.
CLOCK_SKEW_SECONDS = 10

_app = None


class FirebaseError(Exception):
    """Firebase is unreachable or unconfigured — always worth saying out loud."""


def key_path():
    """Where the service account JSON lives.

    Read on use rather than at import: .env is loaded by app.py, after this
    module is imported. A relative value resolves against this file's directory,
    because the server is often launched from the parent folder.
    """
    setting = os.environ.get("FIREBASE_KEY") or "serviceAccountKey.json"
    return setting if os.path.isabs(setting) else os.path.join(BASE_DIR, setting)


def web_config():
    """The three values the browser needs to sign a user in."""
    return {
        "apiKey": os.environ.get("FIREBASE_API_KEY", ""),
        "authDomain": os.environ.get("FIREBASE_AUTH_DOMAIN", ""),
        "projectId": os.environ.get("FIREBASE_PROJECT_ID", ""),
    }


def web_config_ready():
    return all(web_config().values())


def _key_project():
    """The project a service account key belongs to, or "" if it can't be read."""
    try:
        with open(key_path(), encoding="utf-8") as handle:
            return json.load(handle).get("project_id", "")
    except (OSError, ValueError):
        return ""


def setup_steps():
    """What is still unfilled, phrased as things to go and do."""
    steps = []
    if not os.path.exists(key_path()):
        steps.append(
            "Firebase 서비스 계정 키를 내려받아 이 폴더에 serviceAccountKey.json 으로 저장하세요 "
            "(Firebase Console > 프로젝트 설정 > 서비스 계정 > 새 비공개 키 생성)."
        )
    if not web_config_ready():
        steps.append(
            ".env 에 FIREBASE_API_KEY / FIREBASE_AUTH_DOMAIN / FIREBASE_PROJECT_ID 를 채우세요 "
            "(Firebase Console > 프로젝트 설정 > 내 앱 > 웹 앱 SDK 설정). "
            "Authentication > Sign-in method 에서 이메일/비밀번호도 켜야 합니다."
        )
    # A key from another project still loads fine; it only fails at sign-in, as
    # an "incorrect aud" token error nobody could decode from the login screen.
    key_project, web_project = _key_project(), web_config()["projectId"]
    if key_project and web_project and key_project != web_project:
        steps.append(
            f"서비스 계정 키는 '{key_project}' 프로젝트인데 FIREBASE_PROJECT_ID 는 "
            f"'{web_project}' 입니다. 같은 프로젝트의 키로 바꿔 주세요."
        )
    return steps


def _ensure_app():
    global _app
    if _app is None:
        path = key_path()
        if not os.path.exists(path):
            raise FirebaseError(
                f"서비스 계정 키를 찾을 수 없습니다: {path}\n"
                "Firebase Console > 프로젝트 설정 > 서비스 계정 > 새 비공개 키 생성"
            )
        try:
            _app = firebase_admin.initialize_app(credentials.Certificate(path))
        except ValueError:
            # Already initialised elsewhere in this process (the reloader).
            _app = firebase_admin.get_app()
    return _app


def verify_id_token(id_token):
    """Check a token minted by the browser and return the authoritative user.

    The token is trusted only for the uid. The display name and email come from
    a fresh lookup, so a hand-edited request body cannot pick its own name.
    """
    _ensure_app()
    try:
        # A token is minted by Google and checked here, so the two clocks have to
        # agree. They routinely disagree by a second, which without a tolerance
        # reads as "Token used too early" and fails every single login.
        claims = admin_auth.verify_id_token(id_token, clock_skew_seconds=CLOCK_SKEW_SECONDS)
    except Exception as error:  # firebase_admin raises a family of these
        # The user gets one sentence; the log keeps the reason worth debugging.
        logging.getLogger(__name__).warning("ID token rejected: %s", error)
        raise FirebaseError("로그인 정보를 확인하지 못했습니다. 다시 로그인해 주세요.") from error

    record = admin_auth.get_user(claims["uid"])
    return {
        "uid": record.uid,
        "email": record.email or "",
        "name": record.display_name or (record.email or "").split("@")[0] or "익명",
    }
