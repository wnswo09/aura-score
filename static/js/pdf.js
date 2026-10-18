/* A PDF of the score: OpenSheetMusicDisplay lays it out on A4 pages, each page is
 * drawn at 300 dpi, and jsPDF puts the pages in a file.
 *
 * Pages go in as images rather than vectors. The music is all SVG paths, but the
 * title and chapter names are Korean, which jsPDF's built-in fonts cannot draw,
 * and embedding a Korean font would add megabytes to every file. As an image a
 * page prints exactly as it looks on screen, at about 170 KB a page.
 *
 * Like the page itself, this expects OpenSheetMusicDisplay loaded as a global.
 */

const JSPDF = "https://cdn.jsdelivr.net/npm/jspdf@4.2.1/dist/jspdf.umd.min.js";
const WIDTH = 2480; // pixels across an A4 page at 300 dpi

let library = null;

/** jsPDF, loaded on the first export: 400 KB the page otherwise never needs. */
function jsPDF() {
  library ??= new Promise((resolve, reject) => {
    const script = Object.assign(document.createElement("script"), {
      src: JSPDF,
      onload: () => resolve(window.jspdf.jsPDF),
      onerror: () => {
        library = null; // let the next press try again
        reject(new Error("PDF 라이브러리를 불러오지 못했습니다. 네트워크를 확인하고 다시 눌러 주세요."));
      },
    });
    document.head.append(script);
  });
  return library;
}

/** The score laid out on A4 pages, one SVG per page, in a box off screen. */
async function layOut(musicxml) {
  const box = document.createElement("div");
  // Off screen but laid out: OSMD measures text, so the box cannot be display: none.
  Object.assign(box.style, { position: "absolute", left: "-20000px", top: "0", width: "1100px" });
  document.body.append(box);
  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(box, {
    backend: "svg",
    autoResize: false,
    autoBeam: true,
    drawTitle: true,
    drawPartNames: true,
    drawPartAbbreviations: true,
    pageFormat: "A4_P",
    pageBackgroundColor: "#FFFFFF",
  });
  await osmd.load(musicxml);
  osmd.render();
  return { box, pages: [...box.querySelectorAll("svg")] };
}

/** One page as a PNG data URL, numbered at the foot when there is more than one. */
async function draw(svg, number, total) {
  const copy = svg.cloneNode(true);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const url = URL.createObjectURL(
    new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }),
  );
  try {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error("악보 쪽을 그리지 못했습니다."));
      image.src = url;
    });
    const scale = WIDTH / Number(svg.getAttribute("width"));
    const canvas = Object.assign(document.createElement("canvas"), {
      width: WIDTH,
      height: Math.round(Number(svg.getAttribute("height")) * scale),
    });
    const paint = canvas.getContext("2d");
    paint.fillStyle = "#fff";
    paint.fillRect(0, 0, canvas.width, canvas.height);
    paint.drawImage(image, 0, 0, canvas.width, canvas.height);
    if (total > 1) {
      paint.fillStyle = "#555";
      paint.font = "36px serif";
      paint.textAlign = "center";
      paint.fillText(`${number} / ${total}`, canvas.width / 2, canvas.height - 90);
    }
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Build the PDF and hand it to the browser as a download.
 * progress(page, pages) is called as each page is drawn. */
export async function savePdf(musicxml, filename, progress = () => {}) {
  const PDF = await jsPDF();
  const { box, pages } = await layOut(musicxml);
  try {
    const pdf = new PDF({ unit: "mm", format: "a4", compress: true });
    pdf.setProperties({ title: filename, creator: "Aura Score" });
    for (const [index, svg] of pages.entries()) {
      progress(index + 1, pages.length);
      await new Promise((resolve) => setTimeout(resolve)); // let the button repaint between pages
      if (index) pdf.addPage();
      pdf.addImage(await draw(svg, index + 1, pages.length), "PNG", 0, 0, 210, 297, undefined, "FAST");
    }
    pdf.save(`${filename}.pdf`);
  } finally {
    box.remove();
  }
}
