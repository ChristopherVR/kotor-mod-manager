// KOTOR-style UI click sound.
//
// The classic KOTOR menu blip is a short, bright, slightly metallic electronic
// tick. We synthesize it with the Web Audio API instead of shipping an audio
// file, so there is no binary asset to bundle and nothing to download. The
// click is played globally whenever the user activates an interactive element,
// but only while the preference is enabled (it is OFF by default).

const STORAGE_KEY = "kmi.uiSounds";

let enabled = readInitial();
let ctx: AudioContext | null = null;
let installed = false;

function readInitial(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function audioCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
  if (!Ctor) return null;
  if (!ctx) ctx = new Ctor();
  // A context created before a user gesture starts suspended; resume it.
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

export function isUiSoundEnabled(): boolean {
  return enabled;
}

export function setUiSoundEnabled(value: boolean): void {
  enabled = value;
  try {
    localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    /* persistence is best-effort */
  }
}

/** Play one KOTOR-style menu click. No-op if sounds are disabled. */
export function playClick(): void {
  if (!enabled) return;
  const ac = audioCtx();
  if (!ac) return;

  const now = ac.currentTime;
  const out = ac.createGain();
  out.gain.value = 0.18; // master volume for the blip
  out.connect(ac.destination);

  // Tonal part: a short square blip that drops in pitch for that digital "tick".
  const osc = ac.createOscillator();
  osc.type = "square";
  osc.frequency.setValueAtTime(1650, now);
  osc.frequency.exponentialRampToValueAtTime(720, now + 0.05);
  const oscGain = ac.createGain();
  oscGain.gain.setValueAtTime(0.0001, now);
  oscGain.gain.exponentialRampToValueAtTime(1, now + 0.004);
  oscGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.07);
  osc.connect(oscGain).connect(out);
  osc.start(now);
  osc.stop(now + 0.08);

  // Transient: a tiny high-passed noise burst gives the click its crisp edge.
  const noise = ac.createBufferSource();
  const buf = ac.createBuffer(1, Math.ceil(ac.sampleRate * 0.03), ac.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < data.length; i++) {
    data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
  }
  noise.buffer = buf;
  const hp = ac.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = 2400;
  const noiseGain = ac.createGain();
  noiseGain.gain.setValueAtTime(0.35, now);
  noiseGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.025);
  noise.connect(hp).connect(noiseGain).connect(out);
  noise.start(now);
  noise.stop(now + 0.03);
}

// Elements whose activation should click. Covers buttons, links, the custom
// switch (role="switch"), native selects, checkboxes/radios, and ARIA widgets.
const INTERACTIVE =
  'button, a[href], summary, select, [role="button"], [role="switch"], ' +
  '[role="tab"], [role="menuitem"], [role="option"], ' +
  'input[type="checkbox"], input[type="radio"]';

function handleClick(e: MouseEvent): void {
  if (!enabled) return;
  if (e.button !== 0) return; // primary clicks only
  const target = e.target as Element | null;
  const el = target?.closest?.(INTERACTIVE) as HTMLElement | null;
  if (!el) return;
  if (el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true") return;
  playClick();
}

/**
 * Initialize global UI sounds: refresh the enabled flag from storage and attach
 * the document-wide click listener. Safe to call more than once.
 */
export function initUiSounds(): void {
  enabled = readInitial();
  if (installed || typeof document === "undefined") return;
  installed = true;
  // Capture phase so it fires even when a handler stops propagation.
  document.addEventListener("click", handleClick, true);
}
