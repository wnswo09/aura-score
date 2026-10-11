/* Firebase email/password sign-in, and the hand-off to the Flask session.
 *
 * The browser is the only side that can run email/password auth, so it does
 * exactly that much and no more: get an ID token, post it to /api/session, and
 * sign straight back out. Nothing about the login survives in the browser —
 * the server's session cookie is the only state that matters, which keeps the
 * two halves from ever disagreeing about who is logged in.
 */

import { initializeApp } from "https://www.gstatic.com/firebasejs/12.18.0/firebase-app.js";
import {
  createUserWithEmailAndPassword,
  getAuth,
  inMemoryPersistence,
  setPersistence,
  signInWithEmailAndPassword,
  signOut,
  updateProfile,
} from "https://www.gstatic.com/firebasejs/12.18.0/firebase-auth.js";

const config = JSON.parse(document.getElementById("firebase-config").textContent);
const auth = getAuth(initializeApp(config));

// Nothing in localStorage: the token is used once, on the way to the server.
await setPersistence(auth, inMemoryPersistence);

const MESSAGES = {
  "auth/email-already-in-use": "이미 가입된 이메일입니다. 로그인해 주세요.",
  "auth/invalid-email": "이메일 형식이 올바르지 않습니다.",
  "auth/weak-password": "비밀번호는 6자 이상이어야 합니다.",
  "auth/missing-password": "비밀번호를 입력해 주세요.",
  "auth/missing-email": "이메일을 입력해 주세요.",
  "auth/invalid-credential": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "auth/wrong-password": "이메일 또는 비밀번호가 올바르지 않습니다.",
  "auth/user-not-found": "가입되지 않은 이메일입니다.",
  "auth/too-many-requests": "시도가 너무 잦습니다. 잠시 후 다시 시도해 주세요.",
  "auth/network-request-failed": "네트워크에 연결하지 못했습니다.",
  "auth/operation-not-allowed":
    "Firebase Console > Authentication > Sign-in method 에서 이메일/비밀번호를 켜 주세요.",
  "auth/invalid-api-key": "FIREBASE_API_KEY 가 올바르지 않습니다. .env 를 확인하세요.",
};

export function explain(error) {
  return MESSAGES[error?.code] || error?.message || "알 수 없는 오류가 발생했습니다.";
}

/** Turn a freshly signed-in Firebase user into a Flask session, then sign out. */
async function handOff(user) {
  const idToken = await user.getIdToken(true);
  let response;
  try {
    response = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idToken }),
    });
  } finally {
    await signOut(auth);
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || "서버 세션을 만들지 못했습니다.");
  }
}

export async function signUp(email, password, nickname) {
  const { user } = await createUserWithEmailAndPassword(auth, email, password);
  await updateProfile(user, { displayName: nickname });
  try {
    await handOff(user);
  } catch (failure) {
    // The account exists now; retrying sign-up would only say "already in use".
    throw new Error(`가입은 완료됐지만 로그인하지 못했습니다. 로그인 화면에서 다시 시도해 주세요. (${failure.message})`);
  }
}

export async function signIn(email, password) {
  const { user } = await signInWithEmailAndPassword(auth, email, password);
  await handOff(user);
}
