/* The compose page: either form, the wait while GPT writes, and drawing the score.
 *
 * The page renders one of two forms, marked by data-mode. Each gathers its own
 * payload; the server turns both into the same request. What comes back is
 * finished MusicXML, which this file renders with OpenSheetMusicDisplay (loaded
 * as a global by the page) and offers as a download, plus a note timeline that
 * player.js plays.
 */

import { Player } from "./player.js";

const form = document.getElementById("score-form");
const mode = form.dataset.mode;
const error = document.getElementById("form-error");
const status = document.getElementById("gen-status");
const button = document.getElementById("generate");
const result = document.getElementById("result");

function fail(message) {
  error.textContent = message;
  error.hidden = false;
}

// ---------------------------------------------------------------- simple form

function setUpSimple() {
  // Style picks the instruments, size the numbers; show what the pair adds up to.
  const summary = document.getElementById("style-orchestra");
  const orchestras = JSON.parse(document.getElementById("orchestras").textContent);
  const showOrchestra = () => {
    const style = form.querySelector('input[name="style"]:checked');
    const size = form.querySelector('input[name="size"]:checked').value;
    if (style) summary.textContent = `이렇게 편성합니다: ${orchestras[style.value][size]}`;
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
    moods: data.getAll("moods"),
    speed: data.get("speed"),
    length: data.get("bars"),
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
  for (const input of counts) input.addEventListener("input", markPreset);
  markPreset();

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
    length: data.get("bars"),
    bpm: data.get("bpm"),
    difficulty: data.get("difficulty"),
    key: data.get("key"),
    time: data.get("time"),
    structure: data.get("structure"),
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

function say(state, text) {
  status.className = `gen-status ${state}`;
  status.textContent = text;
  status.hidden = false;
}

function holdPage(event) {
  event.preventDefault();
  event.returnValue = "";
}

function seconds(since) {
  return Math.round((Date.now() - since) / 1000);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.hidden = true;

  const data = new FormData(form);
  const payload = mode === "simple" ? simplePayload(data) : detailedPayload(data);
  const complaint = problem(payload);
  if (complaint) return fail(complaint);

  button.disabled = true;
  button.textContent = "악보를 쓰는 중…";
  // Nothing is saved yet, so leaving now throws the finished score away.
  window.addEventListener("beforeunload", holdPage);
  const started = Date.now();
  const tick = () => say("working", `GPT 가 악보를 쓰고 있습니다… ${seconds(started)}초`);
  tick();
  const timer = setInterval(tick, 1000);

  try {
    const response = await fetch("/api/scores", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const score = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(score.error || `서버 오류가 났습니다 (${response.status}).`);

    clearInterval(timer);
    say("good", `완성했습니다 · ${seconds(started)}초`);
    await render(score);
  } catch (failure) {
    status.hidden = true;
    fail(failure instanceof TypeError ? "서버에 연결하지 못했습니다." : failure.message);
  } finally {
    window.removeEventListener("beforeunload", holdPage);
    clearInterval(timer);
    button.disabled = false;
    button.textContent = "악보 만들기";
  }
});

// ---------------------------------------------------------------- score

let osmd = null;
let player = null;
let current = null;

const playButton = document.getElementById("play");
const playError = document.getElementById("play-error");

function showPlayer(state, { loaded, total } = {}) {
  playButton.textContent = {
    idle: "▶ 재생",
    loading: `소리 불러오는 중… ${loaded}/${total}`,
    playing: "■ 정지",
  }[state];
}

playButton.addEventListener("click", () => {
  if (!player || !current) return;
  playError.hidden = true;
  if (player.state !== "idle") return player.stop();
  player.play(current.playback).catch((failure) => {
    playError.textContent = failure.message;
    playError.hidden = false;
  });
});

async function render(score) {
  player?.stop();
  current = score;
  document.getElementById("score-title").textContent = score.title;
  document.getElementById("score-meta").textContent = [
    score.key, score.time, score.tempo, `${score.measures}마디`, "Score in C",
  ].join(" · ");
  document.getElementById("score-desc").textContent = score.description;

  const repairs = document.getElementById("score-repairs");
  repairs.textContent = `GPT 가 쓴 악보에서 ${score.repairs}군데를 자동으로 고쳤습니다 (박자 합, 음역, 붙임줄 등).`;
  repairs.hidden = !score.repairs;

  // Visible before drawing: OSMD lays the score out to the container's width.
  result.hidden = false;
  if (!osmd) {
    osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(document.getElementById("score"), {
      autoResize: true,
      backend: "svg",
      autoBeam: true,
      drawTitle: true,
      drawPartNames: true,
      drawPartAbbreviations: true,
      // The playback cursor, in the page's violet; follow scrolls it into view.
      cursorsOptions: [{ type: 0, color: "#b98cff", alpha: 0.35, follow: true }],
    });
    // A full score stacks a dozen staves; at 1.0 only three bars fit on a line.
    osmd.zoom = 0.75;
    player = new Player(osmd, showPlayer);
  }
  try {
    await osmd.load(score.musicxml);
    osmd.render();
  } catch (failure) {
    throw new Error(`악보를 그리지 못했습니다: ${failure.message}. MusicXML 다운로드는 가능합니다.`);
  }
  result.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.getElementById("download").addEventListener("click", () => {
  if (!current) return;
  const blob = new Blob([current.musicxml], { type: "application/vnd.recordare.musicxml+xml" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${current.title.replace(/[\\/:*?"<>|]/g, "").trim() || "score"}.musicxml`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});
