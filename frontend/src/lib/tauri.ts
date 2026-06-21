// Thin wrappers around Tauri APIs that degrade gracefully when running in a
// plain browser (e.g. `npm run dev` without the Tauri shell).

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** Invoke the Rust apply_update command (download swap + relaunch). */
export async function applyUpdate(newPath: string): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("apply_update", { newPath });
    return true;
  } catch {
    return false;
  }
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

/** Pick a single executable file (used for the custom patcher path). */
export async function pickFile(
  extensions: string[] = ["exe"],
): Promise<string | null> {
  if (!isTauri()) {
    const p = window.prompt("Enter file path:");
    return p && p.trim() ? p.trim() : null;
  }
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const result = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "Executable", extensions }],
    });
    return typeof result === "string" ? result : null;
  } catch {
    return null;
  }
}
