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

/**
 * Subscribe to OS file/folder drag-drop onto the webview. Returns an
 * unsubscribe function. In a plain browser this is a no-op.
 */
export async function onFilesDropped(
  cb: (paths: string[]) => void,
): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    const unlisten = await getCurrentWebview().onDragDropEvent((e) => {
      if (e.payload.type === "drop") cb(e.payload.paths);
    });
    return unlisten;
  } catch {
    return () => {};
  }
}

/**
 * Subscribe to drag-drop hover state (enter/over vs leave/drop) so the UI can
 * highlight a drop zone. Returns an unsubscribe function; no-op in a browser.
 */
export async function onDragHover(
  cb: (active: boolean) => void,
): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const { getCurrentWebview } = await import("@tauri-apps/api/webview");
    const unlisten = await getCurrentWebview().onDragDropEvent((e) => {
      const type = e.payload.type;
      if (type === "enter" || type === "over") cb(true);
      else cb(false);
    });
    return unlisten;
  } catch {
    return () => {};
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
