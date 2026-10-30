import { useEffect } from "react";
import { api } from "./api";
import { finishGameFront, isTauri, openGameFront } from "./tauri";

/** Polling makes the active browser job replayable after a frontend reload. */
export function useGameFront(ready: boolean, log: (message: string, tag?: string) => void) {
  useEffect(() => {
    if (!ready || !isTauri()) return;
    let stopped = false, busy = false, current: string | null = null;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/event").then(async ({ listen }) => {
      const off = await listen<string>("gamefront-message", e => log(e.payload, "info"));
      if (stopped) off(); else unlisten = off;
    }).catch(() => {});
    const poll = async () => {
      if (busy || stopped) return;
      busy = true;
      try {
        const { request } = await api.gamefrontRequest();
        if (stopped || request?.id === current) return;
        if (current) await finishGameFront(current);
        if (request) {
          try {
            await openGameFront(request);
          } catch {
            const fallback = await api.gamefrontExternal();
            log(`GameFront browser unavailable. Save the browser download in ${fallback.destination}.`, "warning");
          }
        }
        current = request?.id ?? null;
      } catch { /* Retry when the backend becomes reachable again. */ }
      finally { busy = false; }
    };
    void poll();
    const timer = window.setInterval(poll, 1000);
    return () => { stopped = true; window.clearInterval(timer); unlisten?.(); };
  }, [ready, log]);
}
