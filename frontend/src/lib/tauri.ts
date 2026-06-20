// Thin wrappers around Tauri APIs that degrade gracefully when running in a
// plain browser (e.g. `npm run dev` without the Tauri shell).

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) {
    // Browser fallback: prompt for a path.
    const p = window.prompt("Enter folder path:");
    return p && p.trim() ? p.trim() : null;
  }
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const result = await open({ directory: true, multiple: false });
    return typeof result === "string" ? result : null;
  } catch {
    return null;
  }
}
