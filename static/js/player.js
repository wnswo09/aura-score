/* Playback: the server's note timeline through General MIDI soundfont samples,
 * with the OSMD cursor walking the score in step.
 *
 * Samples come from smplr (Gleitzman's MusyngKite soundfonts) at about 3 MB per
 * instrument. They load on the first press of play, stay in one shared loader
 * for the page's lifetime, and go into the browser's Cache API so the next visit
 * skips the download. localhost counts as a secure context, which the Cache API
 * needs.
 *
 * Every press of play gets its own output node and its own instruments. smplr's
 * stop() silences the notes that are sounding but not the ones still scheduled,
 * so stopping instead cuts that output node loose: whatever was queued plays
 * into nothing.
 */

import { CacheStorage, SampleLoader, Soundfont } from "https://cdn.jsdelivr.net/npm/smplr@1.0.0/+esm";

const LEAD_IN = 0.2;    // seconds between pressing play and the first note
const TAIL = 1.5;       // seconds to let the last chord ring before stopping
const FADE = 0.03;      // seconds; cutting to zero instantly clicks

let context = null;
let bus = null;
let loader = null;
let storage;

function audio() {
  if (!context) {
    context = new AudioContext();
    // Every session plays into one bus: dry, plus a little synthetic hall,
    // then a compressor so a full-orchestra tutti doesn't clip.
    const compressor = new DynamicsCompressorNode(context, { threshold: -14, ratio: 4 });
    compressor.connect(context.destination);
    bus = new GainNode(context, { gain: 0.8 });
    bus.connect(compressor);
    const hall = new ConvolverNode(context, { buffer: impulse(context, 2.4) });
    bus.connect(hall).connect(new GainNode(context, { gain: 0.25 })).connect(compressor);
    loader = SampleLoader(context);
    try {
      storage = CacheStorage();
    } catch {
      storage = undefined; // no Cache API: samples come over HTTP every visit
    }
  }
  return context;
}

/** Decaying noise: a cheap stand-in for a concert hall's impulse response. */
function impulse(context, seconds) {
  const length = Math.round(context.sampleRate * seconds);
  const buffer = new AudioBuffer({ numberOfChannels: 2, length, sampleRate: context.sampleRate });
  for (let channel = 0; channel < 2; channel++) {
    const data = buffer.getChannelData(channel);
    for (let i = 0; i < length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / length) ** 3;
  }
  return buffer;
}

/** One instrument per sound, all writing to this session's output. */
async function instruments(sounds, output, progress) {
  const made = new Map();
  let done = 0;
  progress(done, sounds.length);
  await Promise.all(
    sounds.map(async (sound) => {
      const options = { instrument: sound, destination: output, loader, volume: 90 };
      if (storage) options.storage = storage;
      const instrument = Soundfont(context, options);
      made.set(sound, instrument);
      await instrument.ready;
      progress(++done, sounds.length);
    }),
  );
  return made;
}

/** Where each cursor step sits, in quarter notes from the start. */
function cursorSteps(osmd) {
  const cursor = osmd.cursor;
  cursor.reset();
  const steps = [];
  while (!cursor.Iterator.EndReached) {
    steps.push(cursor.Iterator.currentTimeStamp.RealValue * 4);
    cursor.next();
  }
  cursor.reset();
  return steps;
}

export class Player {
  /** onChange(state, detail): state is "idle", "loading" ({loaded, total}) or "playing". */
  constructor(osmd, onChange) {
    this.osmd = osmd;
    this.onChange = onChange;
    this.state = "idle";
    this.output = null;
  }

  set(state, detail = {}) {
    this.state = state;
    this.onChange(state, detail);
  }

  async play(playback) {
    if (this.state !== "idle") return;
    const ctx = audio();
    await ctx.resume(); // browsers start audio suspended until a click

    const output = new GainNode(ctx);
    output.connect(bus);
    this.output = output;

    const sounds = [...new Set(playback.tracks.map((track) => track.sound))];
    let made;
    try {
      made = await instruments(sounds, output, (loaded, total) => {
        if (this.output === output) this.set("loading", { loaded, total });
      });
    } catch {
      if (this.output === output) this.stop();
      throw new Error("악기 소리를 불러오지 못했습니다. 네트워크를 확인하고 다시 눌러 주세요.");
    }
    if (this.output !== output) return; // stopped while loading

    const perQuarter = 60 / playback.bpm;
    const start = ctx.currentTime + LEAD_IN;
    for (const track of playback.tracks) {
      const instrument = made.get(track.sound);
      for (const [at, length, note, velocity] of track.notes) {
        instrument.start({ note, velocity, time: start + at * perQuarter, duration: length * perQuarter });
      }
    }
    this.made = made;

    this.start = start;
    this.perQuarter = perQuarter;
    this.end = playback.quarters * perQuarter + TAIL;
    this.steps = cursorSteps(this.osmd);
    this.step = 0;
    this.osmd.cursor.show();
    this.set("playing");
    this.frame = requestAnimationFrame(() => this.follow());
  }

  /** Move the cursor along with the audio clock, and stop at the end. */
  follow() {
    const elapsed = context.currentTime - this.start;
    if (elapsed >= this.end) return this.stop();
    const quarters = elapsed / this.perQuarter;
    while (this.step + 1 < this.steps.length && this.steps[this.step + 1] <= quarters) {
      this.osmd.cursor.next();
      this.step++;
    }
    this.frame = requestAnimationFrame(() => this.follow());
  }

  stop() {
    cancelAnimationFrame(this.frame);
    const output = this.output;
    this.output = null;
    if (output) {
      output.gain.setTargetAtTime(0, context.currentTime, FADE / 3);
      setTimeout(() => output.disconnect(), FADE * 1000 * 4);
    }
    for (const instrument of this.made?.values() ?? []) instrument.stop();
    this.made = null;
    if (this.osmd.cursor) this.osmd.cursor.hide();
    if (this.state !== "idle") this.set("idle");
  }
}
