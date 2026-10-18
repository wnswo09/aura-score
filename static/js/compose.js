/* The compose page: either form, and the wait while GPT writes.
 *
 * The page renders one of two forms, marked by data-mode. Each gathers its own
 * payload; the server turns both into the same request and writes the piece as
 * a background job. The finished score is shown by score_view.js, the same code
 * that shows a saved piece.
 */

import { clock, showScore } from "./score_view.js";

const form = document.getElementById("score-form");
const mode = form.dataset.mode;
const error = document.getElementById("form-error");
const status = document.getElementById("gen-status");
const button = document.getElementById("generate");

function fail(message) {
  error.textContent = message;
  error.hidden = false;
}

// ---------------------------------------------------------------- simple form

function setUpSimple() {
  // Style picks the instruments, size the numbers; show what the pair adds up to.
  const summary = document.getElementById("style-orchestra");
  const orchestras = JSON.parse(document.getElementById("orchestras").textContent);
  const leads = document.getElementById("lead-choices");
  const showOrchestra = () => {
    const style = form.querySelector('input[name="style"]:checked');
    const size = form.querySelector('input[name="size"]:checked').value;
    if (!style) return;
    const { summary: text, instruments } = orchestras[style.value][size];
    summary.textContent = `이렇게 편성합니다: ${text}`;

    // Only instruments that are actually playing can lead; keep the pick if it survives.
    const picked = form.querySelector('input[name="lead"]:checked')?.value || "";
    const keep = instruments.some(([id]) => id === picked) ? picked : "";
    leads.replaceChildren(...[["", "맡기기"], ...instruments].map(([id, name]) => {
      const label = document.createElement("label");
      label.className = "chip-check";
      const input = Object.assign(document.createElement("input"), { type: "radio", name: "lead", value: id, checked: id === keep });
      const chip = Object.assign(document.createElement("span"), { className: "chip", textContent: name });
      label.append(input, chip);
      return label;
    }));
  };
  for (const radio of form.querySelectorAll('input[name="style"], input[name="size"]')) {
    radio.addEventListener("change", showOrchestra);
  }

  const moods = [...form.querySelectorAll('input[name="moods"]')];
  const max = Number(moods[0].closest("[data-max]").dataset.max);
  for (const box of moods) {
    box.addEventListener("change", () => {
      error.hidden = true;
      if (moods.filter((other) => other.checked).length > max) {
        box.checked = false;
        fail(`분위기는 ${max}개까지 고를 수 있습니다.`);
      }
    });
  }
}

function simplePayload(data) {
  return {
    mode,
    style: data.get("style"),
    size: data.get("size"),
    lead: data.get("lead") || "",
    moods: data.getAll("moods"),
    speed: data.get("speed"),
    minutes: data.get("minutes"),
    extra: (data.get("extra") || "").trim(),
  };
}

// ---------------------------------------------------------------- detailed form

const counts = [...form.querySelectorAll("input[data-players]")];

function players() {
  return Object.fromEntries(counts.map((input) => [input.name, Number(input.value) || 0]));
}

function setUpDetailed() {
  // Presets fill the counts; the one matching the counts exactly lights up.
  const presets = [...form.querySelectorAll(".preset")];
  const markPreset = () => {
    const now = players();
    for (const preset of presets) {
      const wanted = JSON.parse(preset.dataset.counts);
      preset.classList.toggle("on", counts.every((input) => (wanted[input.name] || 0) === now[input.name]));
    }
  };
  for (const preset of presets) {
    preset.addEventListener("click", () => {
      const wanted = JSON.parse(preset.dataset.counts);
      for (const input of counts) input.value = wanted[input.name] || 0;
      markPreset();
    });
  }
  // An instrument with nobody playing it cannot lead.
  const lead = form.elements.lead;
  const markLead = () => {
    const now = players();
    for (const option of lead.options) option.disabled = Boolean(option.value) && !now[option.value];
    if (lead.selectedOptions[0]?.disabled) lead.value = "";
  };
  for (const preset of presets) preset.addEventListener("click", markLead);
  for (const input of counts) input.addEventListener("input", () => { markPreset(); markLead(); });
  markPreset();
  markLead();

  // The tempo word follows the number: 80 -> Andante.
  const bpm = form.elements.bpm;
  const term = document.getElementById("tempo-term");
  const terms = JSON.parse(bpm.dataset.terms);
  const showTerm = () => {
    const value = Number(bpm.value);
    term.textContent = value ? terms.filter(([floor]) => value >= floor).at(-1)[1] : "";
  };
  bpm.addEventListener("input", showTerm);
  showTerm();

  // Mood chips add or remove their word in the free-text box.
  const moodInput = form.elements.mood;
  const chips = [...form.querySelectorAll(".mood")];
  const words = () => moodInput.value.split(",").map((word) => word.trim()).filter(Boolean);
  const markMoods = () => {
    const current = words();
    for (const chip of chips) chip.classList.toggle("on", current.includes(chip.textContent));
  };
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      const current = words();
      const word = chip.textContent;
      moodInput.value = (current.includes(word) ? current.filter((w) => w !== word) : [...current, word]).join(", ");
      markMoods();
    });
  }
  moodInput.addEventListener("input", markMoods);
}

function detailedPayload(data) {
  return {
    mode,
    players: players(),
    minutes: data.get("minutes"),
    bpm: data.get("bpm"),
    difficulty: data.get("difficulty"),
    key: data.get("key"),
    time: data.get("time"),
    structure: data.get("structure"),
    lead: data.get("lead"),
    style: data.get("style"),
    mood: (data.get("mood") || "").trim(),
    extra: (data.get("extra") || "").trim(),
  };
}

/** The checks worth doing before a two-minute wait; the server checks the rest. */
function problem(payload) {
  if (payload.mode === "simple") {
    if (!payload.style) return "작곡가 스타일을 골라 주세요.";
    if (!payload.moods.length) return "분위기를 한 개 이상 골라 주세요.";
  } else if (!Object.values(payload.players).some((n) => n > 0)) {
    return "악기를 한 개 이상 넣어 주세요.";
  }
  return "";
}

if (mode === "simple") setUpSimple();
else setUpDetailed();

// ---------------------------------------------------------------- generate
//
// Writing a long piece takes minutes, so the server runs it as a job: starting
// one returns an id at once, and the page asks about it every two seconds. The
// id is kept for this tab, so leaving and coming back picks the job up again.

const JOB = "aura-score-job";

function remember(job) {
  try { sessionStorage.setItem(JOB, job); } catch { /* private mode: no resume */ }
}

function forget() {
  try { sessionStorage.removeItem(JOB); } catch { /* nothing kept */ }
}

function remembered() {
  try { return sessionStorage.getItem(JOB); } catch { return null; }
}

function say(state, text) {
  status.className = `gen-status ${state}`;
  status.textContent = text;
  status.hidden = false;
}

function busy(on) {
  button.disabled = on;
  button.textContent = on ? "악보를 쓰는 중…" : "악보 만들기";
}

/** Ask about a job until it is done. `quiet` is for picking one up on page
 * load, where a job the server has forgotten is simply let go. */
async function wait(job, quiet = false) {
  busy(true);
  try {
    for (;;) {
      const response = await fetch(`/api/scores/${job}`);
      const report = await response.json().catch(() => ({}));
      if (response.status === 404 && quiet) {
        forget();
        status.hidden = true;
        return;
      }
      if (!response.ok) throw new Error(report.error || `서버 오류가 났습니다 (${response.status}).`);
      if (report.state === "done") {
        const score = report.score;
        say("good", `완성했습니다 · ${clock(report.elapsed)} 걸렸습니다 · `);
        if (score.id) {
          status.append(Object.assign(document.createElement("a"), {
            href: `/scores/${score.id}`, textContent: "내 악보에 저장했습니다",
          }));
        } else {
          status.append(`저장하지 못했습니다: ${score.save_error || "알 수 없는 이유"}`);
        }
        await showScore(score);
        return;
      }
      if (report.state === "failed") throw new Error(report.error);
      say("working", `${report.stage || "준비하는 중"}… ${clock(report.elapsed)}`);
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
  } catch (failure) {
    forget();
    status.hidden = true;
    fail(failure instanceof TypeError ? "서버에 연결하지 못했습니다." : failure.message);
  } finally {
    busy(false);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;

  const data = new FormData(form);
  const payload = mode === "simple" ? simplePayload(data) : detailedPayload(data);
  const complaint = problem(payload);
  if (complaint) return fail(complaint);

  busy(true);
  say("working", "작업을 시작하는 중…");
  try {
    const response = await fetch("/api/scores", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const started = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(started.error || `서버 오류가 났습니다 (${response.status}).`);
    remember(started.job);
    await wait(started.job);
  } catch (failure) {
    status.hidden = true;
    fail(failure instanceof TypeError ? "서버에 연결하지 못했습니다." : failure.message);
    busy(false);
  }
});

// A job started earlier in this tab, still running or already done.
const pending = remembered();
if (pending) wait(pending, true);
