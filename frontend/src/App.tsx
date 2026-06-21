import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, connectEvents, waitForBackend,
  type AppStatus, type BuildInfo, type BuildMod, type Profile, type WsEvent,
} from "@/lib/api";
import { DEFAULT_RUNTIME, type ModRuntime } from "@/components/ModList";
import { type LogLine } from "@/components/LogPanel";
import { LoginDialog } from "@/components/LoginDialog";
import { AppShell } from "@/layouts/AppShell";
import { BuildsView } from "@/views/BuildsView";
import { LibraryView } from "@/views/LibraryView";
import { ConflictsView } from "@/views/ConflictsView";
import { ActivityView } from "@/views/ActivityView";
import { SettingsView } from "@/views/SettingsView";
import { type ViewId } from "@/lib/views";

const FINAL = new Set(["DONE", "SKIPPED", "ERROR"]);

const VIEW_IDS: ViewId[] = ["builds", "library", "conflicts", "activity", "settings"];

export default function App() {
  const [view, setViewState] = useState<ViewId>(() => {
    const h = typeof location !== "undefined" ? (location.hash.replace("#", "") as ViewId) : "builds";
    return VIEW_IDS.includes(h) ? h : "builds";
  });
  const setView = useCallback((v: ViewId) => {
    setViewState(v);
    if (typeof location !== "undefined") location.hash = v;
  }, []);

  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<AppStatus | null>(null);
  const [builds, setBuilds] = useState<BuildInfo[]>([]);
  const [selectedBuild, setSelectedBuild] = useState("k1_full");
  const [mods, setMods] = useState<BuildMod[]>([]);
  const [runtime, setRuntime] = useState<Record<string, ModRuntime>>({});
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [activeFileId, setActiveFileId] = useState<string | null>(null);
  const [patcherMod, setPatcherMod] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [username, setUsername] = useState("");
  const [conflictCount, setConflictCount] = useState(0);
  const [dataTick, setDataTick] = useState(0);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [activeProfile, setActiveProfile] = useState<string>("");

  const logId = useRef(0);
  const addLog = useCallback((message: string, tag = "") => {
    setLogs((prev) => {
      const next = [...prev, { id: logId.current++, message, tag }];
      return next.length > 600 ? next.slice(-600) : next;
    });
  }, []);

  const resetRuntime = useCallback(() => setRuntime({}), []);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setRunning(s.pipeline_running);
    } catch { /* backend not up yet */ }
  }, []);

  // Keep a ref of the active profile so closures (WS handler) see the latest.
  const activeProfileRef = useRef(activeProfile);
  useEffect(() => { activeProfileRef.current = activeProfile; }, [activeProfile]);

  const refreshConflicts = useCallback(async () => {
    const pid = activeProfileRef.current;
    if (!pid) return;
    try {
      const r = await api.conflicts(pid);
      setConflictCount(r.conflicts?.length ?? 0);
    } catch { /* endpoint may be unavailable */ }
  }, []);

  const refreshProfiles = useCallback(async () => {
    try {
      const r = await api.profiles();
      setProfiles(r.profiles ?? []);
      setActiveProfile((cur) => {
        const next = r.active || r.profiles?.[0]?.id || "";
        // Preserve a still-valid current selection (e.g. user-switched profile).
        if (cur && r.profiles?.some((p) => p.id === cur)) return cur;
        return next;
      });
    } catch { /* endpoint may be unavailable */ }
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
      await refreshProfiles();
      api.updateCheck()
        .then((u) => {
          if (u.available) addLog(`Update available: v${u.latest_version} — see Settings.`, "info");
        })
        .catch(() => {});
    })();
  }, [addLog, refreshProfiles]);

  // Refresh conflict count whenever the active profile changes.
  useEffect(() => {
    if (activeProfile) refreshConflicts();
  }, [activeProfile, refreshConflicts]);

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
          refreshConflicts();
          setDataTick((t) => t + 1);
        }
        break;
    }
  };

  // Keep a ref of patcherMod for use inside the event handler closure.
  const patcherRef = useRef<string | null>(null);
  useEffect(() => { patcherRef.current = patcherMod; }, [patcherMod]);

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

  const handleSignOut = useCallback(() => {
    api.logout().catch(() => {});
    setUsername("");
    setStatus((prev) => (prev ? { ...prev, logged_in: false } : prev));
    addLog("Signed out.", "muted");
  }, [addLog]);

  return (
    <AppShell
      active={view}
      onNavigate={setView}
      status={status}
      username={username}
      running={running}
      overallPct={overall}
      conflictCount={conflictCount}
      onSignIn={() => setShowLogin(true)}
      onSignOut={handleSignOut}
    >
      {view === "builds" && (
        <BuildsView
          ready={ready}
          loggedIn={!!status?.logged_in}
          builds={builds}
          selectedBuild={selectedBuild}
          onSelectBuild={setSelectedBuild}
          mods={mods}
          setMods={setMods}
          runtime={runtime}
          resetRuntime={resetRuntime}
          activeFileId={activeFileId}
          running={running}
          paused={paused}
          overall={overall}
          done={done}
          errors={errors}
          patcherMod={patcherMod}
          clearPatcher={() => setPatcherMod(null)}
          addLog={addLog}
          setRunning={setRunning}
          setPaused={setPaused}
          requestLogin={() => setShowLogin(true)}
        />
      )}
      {view === "library" && (
        <LibraryView
          onGoToBuilds={() => setView("builds")}
          onGoToConflicts={() => setView("conflicts")}
          addLog={addLog}
          refreshTick={dataTick}
          profiles={profiles}
          activeProfile={activeProfile}
          setActiveProfile={setActiveProfile}
        />
      )}
      {view === "conflicts" && (
        <ConflictsView
          refreshTick={dataTick}
          profiles={profiles}
          activeProfile={activeProfile}
          setActiveProfile={setActiveProfile}
        />
      )}
      {view === "activity" && <ActivityView logs={logs} onClear={() => setLogs([])} />}
      {view === "settings" && (
        <SettingsView
          status={status}
          username={username}
          onSignIn={() => setShowLogin(true)}
          onSignOut={handleSignOut}
          addLog={addLog}
          profiles={profiles}
          activeProfile={activeProfile}
          setActiveProfile={setActiveProfile}
          refreshProfiles={refreshProfiles}
        />
      )}

      <LoginDialog
        open={showLogin}
        onClose={() => setShowLogin(false)}
        onLoggedIn={(u) => { setUsername(u); refreshStatus(); }}
      />
    </AppShell>
  );
}

function fmtKb(kb: number): string {
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB`;
  return `${kb} KB`;
}
