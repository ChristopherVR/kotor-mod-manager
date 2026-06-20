// REST + WebSocket client for the local FastAPI backend (the Tauri sidecar).

export const BACKEND_HOST = "127.0.0.1";
export const BACKEND_PORT = 8756;
const BASE = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
const WS_URL = `ws://${BACKEND_HOST}:${BACKEND_PORT}/ws`;

export type ModStatus =
  | "PENDING" | "DOWNLOADING" | "EXTRACTING" | "READY" | "INSTALLING"
  | "WAITING_PATCHER" | "DONE" | "SKIPPED" | "ERROR";

export interface BuildInfo {
  key: string;
  label: string;
  game: string;
}

export interface BuildMod {
  install_order: number;
  file_id: string;
  slug: string;
  name: string;
  url: string;
  game: string;
  section: string;
  category: string;
  note: string;
  option_hint: string;
  install_method_hint: string;
  build_key: string;
}

export interface AppStatus {
  version: string;
  logged_in: boolean;
  pipeline_running: boolean;
  shim_available: boolean;
  shim_path: string | null;
  current_build: string;
}

export interface Settings {
  kotor1_path: string;
  kotor2_path: string;
  download_dir: string;
}

// WebSocket event shapes
export type WsEvent =
  | { type: "hello"; version: string }
  | { type: "auth"; logged_in: boolean; username: string }
  | { type: "log"; message: string; tag: string }
  | { type: "status"; file_id: string; status: ModStatus; status_label: string; detail: string }
  | { type: "progress"; file_id: string; pct: number; kb: number; total_kb: number }
  | { type: "install_progress"; file_id: string; pct: number; label: string }
  | { type: "pipeline"; event: "started" | "finished"; [k: string]: unknown };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw Object.assign(new Error((data as any)?.error || res.statusText), {
      status: res.status,
      data,
    });
  }
  return data as T;
}

export const api = {
  health: () => req<{ ok: boolean; version: string }>("/api/health"),
  status: () => req<AppStatus>("/api/status"),
  builds: () => req<{ builds: BuildInfo[] }>("/api/builds"),
  credentials: () => req<{ username: string }>("/api/credentials"),
  login: (username: string, password: string, save = true) =>
    req<{ ok: boolean; username: string }>("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password, save }),
    }),
  getSettings: () => req<Settings>("/api/settings"),
  setSettings: (s: Settings) =>
    req<{ ok: boolean }>("/api/settings", { method: "POST", body: JSON.stringify(s) }),
  loadBuild: (key: string) =>
    req<{ ok: boolean; build_key: string; mods: BuildMod[] }>(
      `/api/builds/${key}/load`, { method: "POST" }),
  startInstall: (build_key: string, unattended: boolean, game_path?: string) =>
    req<{ ok: boolean; total: number; game_path: string }>("/api/install/start", {
      method: "POST",
      body: JSON.stringify({ build_key, unattended, game_path }),
    }),
  control: (action: "pause" | "resume" | "stop" | "retry") =>
    req<{ ok: boolean; action: string }>(`/api/install/${action}`, { method: "POST" }),
  installState: () =>
    req<{ running: boolean; mods: any[] }>("/api/install/state"),
};

// Resilient WebSocket with auto-reconnect.
export function connectEvents(
  onEvent: (e: WsEvent) => void,
  onOpen?: () => void,
  onClose?: () => void,
): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => onOpen?.();
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data) as WsEvent);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      onClose?.();
      if (!closed) retry = setTimeout(open, 1000);
    };
    ws.onerror = () => ws?.close();
  };
  open();

  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    ws?.close();
  };
}

// Wait for the backend to come up (sidecar may still be starting).
export async function waitForBackend(timeoutMs = 30000): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await api.health();
      return true;
    } catch {
      await new Promise((r) => setTimeout(r, 400));
    }
  }
  return false;
}
