/* Choosing part of the score to change, two ways:
 *   - hover a staff and its whole line in that row lights up, asking "이 부분?";
 *     a click chooses it;
 *   - drag a box over the score and every measure of every staff it touches is
 *     chosen.
 * Positions come from OpenSheetMusicDisplay's own layout (GraphicSheet.MeasureList),
 * whose units are a tenth of a staff space at zoom 1, so the boxes follow the
 * score at any width or zoom.
 */

const DRAG = 5; // pixels the pointer has to travel before a press counts as a drag
const ROOM = 1.5; // staff spaces above and below a staff, for notes that stick out of it

function box(className, rect, label) {
  const element = Object.assign(document.createElement("div"), { className });
  Object.assign(element.style, {
    left: `${rect.x}px`, top: `${rect.y}px`, width: `${rect.w}px`, height: `${rect.h}px`,
  });
  if (label) element.append(Object.assign(document.createElement("span"), { textContent: label }));
  return element;
}

function bounds(cells) {
  const x = Math.min(...cells.map((cell) => cell.x));
  const y = Math.min(...cells.map((cell) => cell.y));
  return {
    x, y,
    w: Math.max(...cells.map((cell) => cell.x + cell.w)) - x,
    h: Math.max(...cells.map((cell) => cell.y + cell.h)) - y,
  };
}

export class Selector {
  /** onChoose({from, to, staffs}) is called with each new choice, and with null when it is cleared. */
  constructor(osmd, paper, onChoose) {
    this.osmd = osmd;
    this.paper = paper;
    this.onChoose = onChoose;
    this.chosen = null;
    this.active = true;
    this.locked = false;
    this.press = null;
    this.marks = Object.assign(document.createElement("div"), { className: "marks" });
    paper.append(this.marks);
    paper.classList.add("selectable");

    paper.addEventListener("pointermove", (event) => this.move(event));
    paper.addEventListener("pointerleave", () => { if (!this.press) this.draw(); });
    paper.addEventListener("pointerdown", (event) => this.down(event));
    paper.addEventListener("pointerup", (event) => this.up(event));
    // A touch that turns into scrolling the paper sideways is not a choice.
    paper.addEventListener("pointercancel", () => { this.press = null; this.draw(); });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.chosen && this.active && !this.locked) this.choose(null);
    });
    // OSMD lays the score out again when the window changes size.
    let settle;
    window.addEventListener("resize", () => {
      clearTimeout(settle);
      settle = setTimeout(() => this.draw(), 700);
    });
  }

  /** Every measure of every staff, as a box in the paper's coordinates. */
  cells() {
    const svg = this.paper.querySelector("svg");
    const sheet = this.osmd.GraphicSheet;
    if (!svg || !sheet) return [];
    const unit = 10 * this.osmd.zoom;
    const paper = this.paper.getBoundingClientRect();
    const score = svg.getBoundingClientRect();
    const dx = score.left - paper.left + this.paper.scrollLeft;
    const dy = score.top - paper.top + this.paper.scrollTop;
    const cells = [];
    sheet.MeasureList.forEach((staffs, index) => {
      staffs.forEach((measure, staff) => {
        if (!measure) return;
        const shape = measure.PositionAndShape;
        cells.push({
          measure: index + 1,
          staff,
          system: measure.ParentMusicSystem,
          x: dx + shape.AbsolutePosition.x * unit,
          y: dy + (shape.AbsolutePosition.y - ROOM) * unit,
          w: shape.Size.width * unit,
          h: (4 + 2 * ROOM) * unit,
        });
      });
    });
    return cells;
  }

  point(event) {
    const paper = this.paper.getBoundingClientRect();
    return { x: event.clientX - paper.left + this.paper.scrollLeft, y: event.clientY - paper.top + this.paper.scrollTop };
  }

  /** The line (one staff across one row of the score) under the pointer. */
  lineAt(point) {
    const cells = this.cells();
    const hit = cells.find((cell) => point.x >= cell.x && point.x <= cell.x + cell.w
      && point.y >= cell.y && point.y <= cell.y + cell.h);
    return hit ? cells.filter((cell) => cell.system === hit.system && cell.staff === hit.staff) : null;
  }

  move(event) {
    if (!this.active || this.locked) return;
    const point = this.point(event);
    if (this.press?.touch) return;
    if (this.press) {
      const band = {
        x: Math.min(point.x, this.press.x), y: Math.min(point.y, this.press.y),
        w: Math.abs(point.x - this.press.x), h: Math.abs(point.y - this.press.y),
      };
      if (band.w > DRAG || band.h > DRAG) this.press.band = band;
      if (this.press.band) this.draw(null, this.press.band);
      return;
    }
    const line = this.lineAt(point);
    this.paper.classList.toggle("over-line", Boolean(line));
    this.draw(line);
  }

  down(event) {
    if (!this.active || this.locked || event.button !== 0) return;
    // A finger on the paper scrolls it, so touch can only tap a line, not drag.
    if (event.pointerType === "touch") {
      this.press = { ...this.point(event), touch: true };
      return;
    }
    event.preventDefault(); // no text selection while dragging over the score
    this.paper.setPointerCapture(event.pointerId);
    this.press = this.point(event);
  }

  up(event) {
    if (!this.press) return;
    const { band } = this.press;
    this.press = null;
    if (band) {
      const touched = this.cells().filter((cell) => cell.x < band.x + band.w && cell.x + cell.w > band.x
        && cell.y < band.y + band.h && cell.y + cell.h > band.y);
      this.choose(touched.length ? this.span(touched) : null);
      return;
    }
    const line = this.lineAt(this.point(event));
    this.choose(line ? this.span(line) : null);
  }

  span(cells) {
    const measures = cells.map((cell) => cell.measure);
    return {
      from: Math.min(...measures),
      to: Math.max(...measures),
      staffs: [...new Set(cells.map((cell) => cell.staff))].sort((a, b) => a - b),
    };
  }

  choose(choice) {
    this.chosen = choice;
    this.draw();
    this.onChoose(choice);
  }

  /** Turn choosing on or off; off forgets the choice. */
  enable(on) {
    this.active = on;
    this.paper.classList.toggle("selectable", on);
    if (!on) this.chosen = null;
    this.draw();
  }

  /** Keep what is chosen while the page is busy changing it. */
  lock(on) {
    this.locked = on;
    this.paper.classList.toggle("locked", on);
    if (on) this.draw();
  }

  /** Draw the chosen measures (one box per staff per row), and the hovered
   * line or the box being dragged, if any. */
  draw(line = null, band = null) {
    this.marks.replaceChildren();
    if (!this.active) return;
    if (this.chosen) {
      const { from, to, staffs } = this.chosen;
      const rows = new Map();
      for (const cell of this.cells()) {
        if (cell.measure < from || cell.measure > to || !staffs.includes(cell.staff)) continue;
        const key = rows.get(cell.system) ?? new Map();
        rows.set(cell.system, key);
        key.set(cell.staff, [...(key.get(cell.staff) ?? []), cell]);
      }
      for (const staffsInRow of rows.values()) {
        for (const cells of staffsInRow.values()) this.marks.append(box("mark chosen", bounds(cells)));
      }
    }
    if (line && !this.locked) this.marks.append(box("mark hover", bounds(line), "이 부분?"));
    if (band) this.marks.append(box("mark band", band));
  }
}
