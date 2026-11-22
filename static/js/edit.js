/* Asking GPT to rewrite part of a saved score.
 * select.js chooses measures × staves on the score; this module shows what was
 * chosen, takes the wish, runs the edit as a background job on the server
 * (/api/library/<id>/edit, polled like a new piece at /api/scores/<job>), and
 * shows the edited score in place. Edits are saved with the piece; "되돌리기"
 * takes the last one back off (/api/library/<id>/undo).
 */

import { Selector } from "./select.js";

const MAX_MEASURES = 24; // as score_service.MAX_EDIT_MEASURES
const POLL = 1500;

const guide = document.getElementById("edits");
const last = document.getElementById("edit-last");
const lastWhere = document.getElementById("edit-last-where");
const lastChange = document.getElementById("edit-last-change");
const undoButtons = [document.getElementById("edit-undo"), document.getElementById("edit-panel-undo")];
const panel = document.getElementById("edit-panel");
const where = document.getElementById("edit-where");
const wish = document.getElementById("edit-wish");
const status = document.getElementById("edit-status");
const submit = document.getElementById("edit-submit");
const cancel = document.getElementById("edit-cancel");
const ideas = document.getElementById("edit-ideas");

let selector = null;
let score = null;
let show = null;
let busy = false;

function say(text, tone = "") {
  status.textContent = text;
  status.className = `edit-status ${tone}`;
}

function message(failure) {
  return failure instanceof TypeError ? "서버에 연결하지 못했습니다." : failure.message;
}

function bars(from, to) {
  return from === to ? `${from}마디` : `${from}–${to}마디`;
}

function partsOf(choice) {
  return choice.staffs.map((staff) => score.parts[staff]).filter(Boolean);
}

function describe(choice) {
  const parts = partsOf(choice);
  const names = parts.length <= 3
    ? parts.map((part) => part.name).join(", ")
    : `${parts[0].name} 외 ${parts.length - 1}파트`;
  return `${names} · ${bars(choice.from, choice.to)}`;
}

function setBusy(on) {
  busy = on;
  selector?.lock(on);
  for (const control of [wish, submit, cancel, ...undoButtons, ...ideas.children]) control.disabled = on;
  submit.textContent = on ? "고치는 중…" : "이 부분 고치기";
}

function chosen(choice) {
  if (busy) return;
  panel.hidden = !choice;
  if (!choice) return;
  where.textContent = describe(choice);
  const count = choice.to - choice.from + 1;
  const tooLong = count > MAX_MEASURES;
  submit.disabled = tooLong;
  say(tooLong ? `한 번에 ${MAX_MEASURES}마디까지 고칠 수 있습니다. 지금 ${count}마디를 골랐어요.` : "", tooLong ? "bad" : "");
  wish.focus({ preventScroll: true });
}

async function send(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(answer.error || `서버 오류가 났습니다 (${response.status}).`);
  return answer;
}

/** Ask about the edit's job until it is done; returns the edited score. */
async function follow(job) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, POLL));
    const response = await fetch(`/api/scores/${job}`);
    const report = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(report.error || `서버 오류가 났습니다 (${response.status}).`);
    if (report.state === "done") return report.score;
    if (report.state === "failed") throw new Error(report.error);
    say(`${report.stage || "준비하는 중"}… ${report.elapsed ?? 0}초`, "working");
  }
}

panel.addEventListener("submit", async (event) => {
  event.preventDefault();
  const choice = selector?.chosen;
  const text = wish.value.trim();
  if (!choice || busy || !score?.id) return;
  if (!text) {
    say("어떻게 고칠지 적어 주세요.", "bad");
    wish.focus();
    return;
  }
  setBusy(true);
  say("GPT 에게 보내는 중…", "working");
  try {
    const { job } = await send(`/api/library/${score.id}/edit`, {
      from: choice.from, to: choice.to, parts: partsOf(choice).map((part) => part.id), wish: text,
    });
    const edited = await follow(job);
    setBusy(false);
    await show(edited);
    wish.value = "";
    say(edited.save_error
      ? `고쳤지만 저장하지 못했습니다: ${edited.save_error}`
      : "고쳤습니다. 들어 보고 마음에 들지 않으면 되돌리기를 누르세요.", edited.save_error ? "bad" : "good");
  } catch (failure) {
    setBusy(false);
    say(message(failure), "bad");
  }
});

async function undo(button) {
  if (busy || !score?.id) return;
  setBusy(true);
  button.textContent = "되돌리는 중…";
  try {
    const previous = await send(`/api/library/${score.id}/undo`);
    setBusy(false);
    await show(previous);
    if (!panel.hidden) say("마지막 수정을 되돌렸습니다.", "good");
  } catch (failure) {
    setBusy(false);
    if (panel.hidden) alert(message(failure));
    else say(message(failure), "bad");
  } finally {
    button.textContent = "되돌리기";
  }
}

for (const button of undoButtons) button.addEventListener("click", () => undo(button));

cancel.addEventListener("click", () => selector?.choose(null));

ideas.addEventListener("click", (event) => {
  const idea = event.target.closest(".chip");
  if (!idea) return;
  const text = wish.value.trim();
  wish.value = text ? `${text}, ${idea.textContent}` : idea.textContent;
  wish.focus();
});

// Enter sends, Shift+Enter starts a new line.
wish.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    panel.requestSubmit();
  }
});

/** Called by score_view.js each time a score is drawn. `redraw` shows an
 * edited score the same way, without scrolling the page. */
export function editing(osmd, paper, shown, redraw) {
  const changed = score?.id !== shown.id;
  score = shown;
  show = redraw;
  if (!selector) selector = new Selector(osmd, paper, chosen);

  // A piece that could not be saved has nowhere to keep its edits.
  const editable = Boolean(shown.id && shown.parts?.length);
  guide.hidden = !editable;
  if (changed) selector.chosen = null;
  selector.enable(editable); // also draws the same choice again on the new drawing
  if (!editable || changed) {
    panel.hidden = true;
    say("");
  }

  const edits = shown.edits || [];
  const latest = edits.at(-1);
  last.hidden = !latest;
  undoButtons[1].hidden = !latest;
  if (latest) {
    lastWhere.textContent = `${bars(latest.from, latest.to)} · “${latest.wish}”${edits.length > 1 ? ` (모두 ${edits.length}번 고침)` : ""}`;
    lastChange.textContent = latest.change;
  }
}
