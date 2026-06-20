import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Play, Pause, Square, Settings as SettingsIcon, LogIn, CheckCircle2,
  Zap, AlertTriangle, RotateCcw, Download,
} from "lucide-react";
import {
  api, connectEvents, waitForBackend,
  type AppStatus, type BuildInfo, type BuildMod, type WsEvent,
} from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { ModList, DEFAULT_RUNTIME, type ModRuntime } from "@/components/ModList";
import { LogPanel, type LogLine } from "@/components/LogPanel";
import { LoginDialog } from "@/components/LoginDialog";
import { SettingsDialog } from "@/components/SettingsDialog";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

const FINAL = new Set(["DONE", "SKIPPED", "ERROR"]);

export default function App() {
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [builds, setBuilds] = useState<BuildInfo[]>([]);
  const [selectedBuild, setSelectedBuild] = useState("k1_full");
  const [mods, setMods] = useState<BuildMod[]>([]);
  const [runtime, setRuntime] = useState<Record<string, ModRuntime>>({});
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [unattended, setUnattended] = useState(false);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [patcherMod, setPatcherMod] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [username, setUsername] = useState("");

  const logId = useRef(0);
  const addLog = useCallback((message: string, tag = "") => {
    setLogs((prev) => {
      const next = [...prev, { id: logId.current++, message, tag }];
      return next.length > 600 ? next.slice(-600) : next;
    });
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setRunning(s.pipeline_running);
    } catch { /* backend not up yet */ }
  }, []);

  // Boot: wait for backend, load builds + status.
  useEffect(() => {
    (async () => {
      const ok = await waitForBackend();
      setReady(ok);
      if (!ok) { addLog("Could not reach the backend service.", "error"); return; }
      try {
        const [b, s, c] = await Promise.all([api.builds(), api.status(), api.credentials()]);
        setBuilds(b.builds);
        setStatus(s);
        setUsername(c.username);
      } catch (e: any) {
        addLog(`Startup error: ${e?.message}`, "error");
      }
    })();
  }, [addLog]);

  // WebSocket event stream.
  useEffect(() => {
    if (!ready) return;
    const disconnect = connectEvents(
      (e: WsEvent) => handleEvent(e),
      () => {},
      () => {}
    );
    return disconnect;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);

  const handleEvent = (e: WsEvent) => {
    switch (e.type) {
      case "auth":
        if (e.logged_in) { setUsername(e.username); refreshStatus(); }
        break;
      case "log":
        addLog(e.message, e.tag);
        break;
      case "status": {
        setActiveFileId(e.file_id);
        if (e.status === "WAITING_PATCHER") setPatcherMod(e.file_id);
        else if (FINAL.has(e.status) && patcherRef.current === e.file_id) setPatcherMod(null);
        setRuntime((prev) => ({
          ...prev,
          [e.file_id]: {
            ...(prev[e.file_id] ?? DEFAULT_RUNTIME),
            status: e.status,
            detail: e.detail,
            ...(FINAL.has(e.status) ? { progress: e.status === "DONE" ? 100 : prev[e.file_id]?.progress ?? 0 } : {}),
          },
        }));
        break;
      }
      case "progress": {
        const label = e.total_kb ? `${fmtKb(e.kb)} / ${fmtKb(e.total_kb)}` : `${fmtKb(e.kb)}`;
        setRuntime((prev) => ({
          ...prev,
          [e.file_id]: { ...(prev[e.file_id] ?? DEFAULT_RUNTIME), progress: e.pct * 100, progressLabel: label },
        }));
        break;
      }
      case "install_progress":
        setRuntime((prev) => ({
          ...prev,
          [e.file_id]: { ...(prev[e.file_id] ?? DEFAULT_RUNTIME), progress: e.pct * 100, progressLabel: e.label },
        }));
        break;
      case "pipeline":
        if (e.event === "started") { setRunning(true); setPaused(false); }
        else if (e.event === "finished") {
          setRunning(false); setPaused(false); setActiveFileId(null); setPatcherMod(null);
          addLog(`Finished: ${e.done}/${e.total} installed${e.errors ? `, ${e.errors} error(s)` : ""}.`,
            e.errors ? "warning" : "success");
        }
        break;
    }
  };

  // Keep a ref of patcherMod for use inside the event handler closure.
  const patcherRef = useRef<string | null>(null);
  useEffect(() => { patcherRef.current = patcherMod; }, [patcherMod]);

  const loadBuild = async () => {
    setLoading(true);
    setRuntime({});
    try {
      const r = await api.loadBuild(selectedBuild);
      setMods(r.mods);
      addLog(`Loaded ${r.mods.length} mods for ${labelFor(selectedBuild)}.`, "success");
    } catch (e: any) {
      addLog(`Load failed: ${e?.message}`, "error");
    } finally {
      setLoading(false);
    }
  };

  const startInstall = async () => {
    if (!status?.logged_in) { setShowLogin(true); return; }
    if (mods.length === 0) { addLog("Load a mod list first.", "warning"); return; }
    try {
      await api.startInstall(selectedBuild, unattended);
      setRunning(true);
    } catch (e: any) {
      if (e?.data?.error === "game_path_required") {
        addLog(`Select your ${e.data.game} installation folder…`, "warning");
        const dir = await pickDirectory();
        if (!dir) return;
        try {
          await api.startInstall(selectedBuild, unattended, dir);
          setRunning(true);
        } catch (e2: any) {
          addLog(`Start failed: ${e2?.message}`, "error");
        }
      } else {
        addLog(`Start failed: ${e?.message}`, "error");
      }
    }
  };

  const control = async (action: "pause" | "resume" | "stop" | "retry") => {
    try {
      await api.control(action);
      if (action === "pause") setPaused(true);
      if (action === "resume") setPaused(false);
      if (action === "stop") { setRunning(false); setPaused(false); }
    } catch (e: any) {
      addLog(`${action} failed: ${e?.message}`, "error");
    }
  };

  // Overall progress = finished / total.
  const { done, errors, overall } = useMemo(() => {
    let d = 0, er = 0;
    for (const m of mods) {
      const st = runtime[m.file_id]?.status;
      if (st === "DONE" || st === "SKIPPED") d++;
      else if (st === "ERROR") { d++; er++; }
    }
    return { done: d, errors: er, overall: mods.length ? (d / mods.length) * 100 : 0 };
  }, [mods, runtime]);

  const patcherName = patcherMod ? mods.find((m) => m.file_id === patcherMod)?.name : null;

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      {/* Top bar */}
      <header className="flex items-center gap-3 border-b bg-card/40 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Zap className="size-5 text-primary" />
          <span className="text-sm font-semibold">KOTOR Mod Installer</span>
          {status && <span className="text-xs text-muted-foreground">v{status.version}</span>}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {status?.shim_available ? (
            <span className="flex items-center gap-1 text-xs text-[hsl(var(--success))]">
              <Zap className="size-3.5" /> Headless patcher ready
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-[hsl(var(--warning))]">
              <AlertTriangle className="size-3.5" /> No HoloPatcher shim
            </span>
          )}
          <Separator orientation="vertical" className="h-5" />
          {status?.logged_in ? (
            <span className="flex items-center gap-1 text-xs text-[hsl(var(--success))]">
              <CheckCircle2 className="size-3.5" /> {username || "Logged in"}
            </span>
          ) : (
            <Button variant="default" size="sm" onClick={() => setShowLogin(true)}>
              <LogIn /> Login
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setShowSettings(true)}>
            <SettingsIcon /> Settings
          </Button>
        </div>
      </header>

      {/* TSLPatcher banner */}
      {patcherName && (
        <div className="flex items-center gap-2 border-b border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.1)] px-4 py-2 text-sm text-[hsl(var(--warning))] animate-fade-in">
          <AlertTriangle className="size-4 shrink-0" />
          <span>
            TSLPatcher is open for <b>{patcherName}</b>. The game path is on your clipboard — paste it,
            click Install, then close the patcher window.
          </span>
        </div>
      )}

      {/* Build selector */}
      <div className="flex items-center gap-3 border-b bg-card/20 px-4 py-2">
        <Select
          value={selectedBuild}
          onChange={(e) => setSelectedBuild(e.target.value)}
          disabled={running}
          className="w-64"
        >
          {builds.map((b) => (
            <option key={b.key} value={b.key}>{b.label}</option>
          ))}
        </Select>
        <Button variant="secondary" size="sm" onClick={loadBuild} disabled={loading || running}>
          <Download /> {loading ? "Loading…" : "Load Mod List"}
        </Button>
        {mods.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {mods.length} mods · {done}/{mods.length} done{errors ? ` · ${errors} error(s)` : ""}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Overall</span>
          <Progress value={overall} className="w-40" />
        </div>
      </div>

      {/* Main content */}
      <main className="flex min-h-0 flex-1 gap-3 p-3">
        <section className="flex min-h-0 flex-[3] flex-col rounded-lg border bg-card/30 p-2">
          <ModList mods={mods} runtime={runtime} activeFileId={activeFileId} />
        </section>
        <section className="flex min-h-0 flex-[2] flex-col gap-2">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-medium text-muted-foreground">Activity Log</span>
            <Button variant="ghost" size="sm" onClick={() => setLogs([])}>Clear</Button>
          </div>
          <div className="min-h-0 flex-1">
            <LogPanel lines={logs} />
          </div>
        </section>
      </main>

      {/* Bottom action bar */}
      <footer className="flex items-center gap-3 border-t bg-card/40 px-4 py-2.5">
        {!running ? (
          <Button onClick={startInstall} disabled={!ready || mods.length === 0}>
            <Play /> Download &amp; Install All
          </Button>
        ) : (
          <>
            {!paused ? (
              <Button variant="secondary" onClick={() => control("pause")}>
                <Pause /> Pause
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => control("resume")}>
                <Play /> Resume
              </Button>
            )}
            <Button variant="destructive" onClick={() => control("stop")}>
              <Square /> Stop
            </Button>
          </>
        )}
        {!running && errors > 0 && (
          <Button variant="outline" onClick={() => control("retry").then(startInstall)}>
            <RotateCcw /> Retry failed
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Switch id="un" checked={unattended} onCheckedChange={setUnattended} disabled={running} />
          <label htmlFor="un" className="cursor-pointer text-xs text-muted-foreground">
            Unattended (never prompt; skip mods needing a manual GUI)
          </label>
        </div>
        <span className={cn("text-xs", ready ? "text-muted-foreground" : "text-destructive")}>
          {ready ? (running ? (paused ? "Paused" : "Installing…") : "Idle") : "Connecting to backend…"}
        </span>
      </footer>

      <LoginDialog
        open={showLogin}
        onClose={() => setShowLogin(false)}
        onLoggedIn={(u) => { setUsername(u); refreshStatus(); }}
      />
      <SettingsDialog open={showSettings} onClose={() => setShowSettings(false)} />
    </div>
  );

  function labelFor(key: string) {
    return builds.find((b) => b.key === key)?.label ?? key;
  }
}

function fmtKb(kb: number): string {
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB`;
  return `${kb} KB`;
}
