/* Showing a finished score: what GPT planned, the score itself, playback and
 * download. Used by the compose page when a piece is done and by the page of a
 * saved piece. Both pages include templates/compose/result.html and load
 * OpenSheetMusicDisplay as a global before this module.
 */

import { Player } from "./player.js";

const result = document.getElementById("result");

export function clock(seconds) {
  return seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

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

export async function showScore(score) {
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
