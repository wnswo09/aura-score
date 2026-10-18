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

function clock(seconds) {
  return seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
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
        say("good", `완성했습니다 · ${clock(report.elapsed)} 걸렸습니다`);
        await render(report.score);
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

/** One section of GPT's plan: where it is, what it is for, and what is new in it.
 * The badge is the rehearsal letter printed in the score. */
function flowItem(section) {
  const item = document.createElement("li");
  item.classList.toggle("solo", section.solo);
  const head = Object.assign(document.createElement("div"), { className: "flow-head" });
  const facts = [
    `${section.from}–${section.to}마디`, section.role, section.melody && `선율 ${section.melody}`,
    section.texture, section.accompaniment, section.dynamic,
  ].filter(Boolean).join(" · ");
  head.append(
    Object.assign(document.createElement("b"), { textContent: section.mark }),
    Object.assign(document.createElement("span"), { textContent: facts }),
  );
  item.append(head, Object.assign(document.createElement("p"), { textContent: section.idea }));
  return item;
}

const NUMERALS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ";

/** A chapter: its title, tempo, key and length, what it is for, and its sections. */
function chapterBlock(chapter) {
  const block = Object.assign(document.createElement("section"), { className: "chapter" });
  const head = Object.assign(document.createElement("div"), { className: "chapter-head" });
  head.append(
    Object.assign(document.createElement("h3"), {
      textContent: `${NUMERALS[(chapter.number - 1) % NUMERALS.length]}. ${chapter.title}`,
    }),
    Object.assign(document.createElement("span"), {
      textContent: [chapter.tempo, chapter.key, `${chapter.from}–${chapter.to}마디`, clock(chapter.seconds)].join(" · "),
    }),
  );
  const sections = Object.assign(document.createElement("ol"), { className: "flow" });
  sections.replaceChildren(...chapter.sections.map(flowItem));
  block.append(head, Object.assign(document.createElement("p"), { className: "chapter-purpose", textContent: chapter.purpose }), sections);
  return block;
}

async function render(score) {
  player?.stop();
  current = score;
  document.getElementById("score-title").textContent = score.title;
  document.getElementById("score-meta").textContent = [
    clock(score.duration), `${score.chapters.length}장`, `${score.measures}마디`, score.key, score.time,
    `주인공 ${score.lead}`, score.ending, "Score in C",
  ].join(" · ");
  document.getElementById("score-desc").textContent = score.description;
  document.getElementById("score-flow").replaceChildren(...score.chapters.map(chapterBlock));
  document.getElementById("score-repetition").textContent =
    `반복도: 앞 마디와 똑같은 마디 ${score.repetition.exact}% · 리듬이 같은 마디 ${score.repetition.rhythm}%`;

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

// A job started earlier in this tab, still running or already done.
const pending = remembered();
if (pending) wait(pending, true);
