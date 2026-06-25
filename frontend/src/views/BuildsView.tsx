import { useEffect, useMemo, useState, type MouseEvent } from "react";
import {
  Play, Pause, Square, AlertTriangle, RotateCcw, Download, X, FolderInput, UploadCloud,
  FolderOpen, ScrollText,
} from "lucide-react";
import { api, type BuildInfo, type BuildMod } from "@/lib/api";
import { pickDirectory, onFilesDropped, onDragHover } from "@/lib/tauri";
import { ModList, type ModRuntime } from "@/components/ModList";
import { ContextMenu, type ContextMenuItem } from "@/components/ui/context-menu";
import { BuildModDetail } from "@/components/BuildModDetail";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

interface BuildsViewProps {
  ready: boolean;
  loggedIn: boolean;
  builds: BuildInfo[];
  selectedBuild: string;
  onSelectBuild: (key: string) => void;
  mods: BuildMod[];
  setMods: (mods: BuildMod[]) => void;
  runtime: Record<string, ModRuntime>;
  resetRuntime: () => void;
  activeFileId: string | null;
  running: boolean;
  paused: boolean;
  overall: number;
  done: number;
  errors: number;
  manual: number;
  markManualDone: (fileId: string) => void;
  patcherMod: string | null;
  clearPatcher: () => void;
  addLog: (message: string, tag?: string) => void;
  setRunning: (v: boolean) => void;
  setPaused: (v: boolean) => void;
  requestLogin: () => void;
  activeProfile: string;
}

export function BuildsView(props: BuildsViewProps) {
  const {
    ready, loggedIn, builds, refreshBuilds, selectedBuild, onSelectBuild, mods, setMods, runtime,
    resetRuntime, activeFileId, running, paused, overall, done, errors, manual, markManualDone,
    patcherMod, clearPatcher, addLog, setRunning, setPaused, requestLogin, activeProfile,
  } = props;

  const t = useT();
  const [loading, setLoading] = useState(false);
  const [openMod, setOpenMod] = useState<BuildMod | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dragActive, setDragActive] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number; mod: BuildMod } | null>(null);

  const buildGame = builds.find((b) => b.key === selectedBuild)?.game ?? mods[0]?.game ?? "";

  const labelFor = (key: string) => builds.find((b) => b.key === key)?.label ?? key;
  const patcherName = patcherMod ? mods.find((m) => m.file_id === patcherMod)?.name : null;

  // Default to ALL mods selected whenever the loaded mod list changes.
  useEffect(() => {
    setSelected(new Set(mods.map((m) => m.file_id)));
  }, [mods]);

  const toggleMod = (fileId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(fileId)) next.delete(fileId);
      else next.add(fileId);
      return next;
    });
  };
  const selectAll = () => setSelected(new Set(mods.map((m) => m.file_id)));
  const selectNone = () => setSelected(new Set());

  const selectedCount = useMemo(
    () => mods.filter((m) => selected.has(m.file_id)).length,
    [mods, selected],
  );

  // Import a dropped folder of mods, or a single archive.
  const importFolder = async (path: string) => {
    if (!buildGame) { addLog(t("builds.importNoGame"), "warning"); return; }
    try {
      addLog(t("builds.importingFolder", { path }), "info");
      await api.importFolder({ game: buildGame, path, profile: activeProfile || undefined });
    } catch (e: any) {
      addLog(t("builds.importFailed", { error: e?.message ?? "error" }), "error");
    }
  };
  const importArchive = async (path: string) => {
    if (!buildGame) { addLog(t("builds.importNoGame"), "warning"); return; }
    try {
      addLog(t("builds.importingMod", { path }), "info");
      await api.importMod({ game: buildGame, path, profile: activeProfile || undefined });
    } catch (e: any) {
      addLog(t("builds.importFailed", { error: e?.message ?? "error" }), "error");
    }
  };

  const pickImportFolder = async () => {
    const dir = await pickDirectory();
    if (dir) importFolder(dir);
  };

  // Register OS drag-drop listeners (Tauri only; no-op in a browser).
  useEffect(() => {
    let disposed = false;
    const cleanups: Array<() => void> = [];
    onFilesDropped((paths) => {
      setDragActive(false);
      for (const p of paths) {
        const low = p.toLowerCase();
        if (low.endsWith(".zip") || low.endsWith(".7z") || low.endsWith(".rar")) importArchive(p);
        else importFolder(p);
      }
    }).then((un) => { if (disposed) un(); else cleanups.push(un); });
    onDragHover((active) => setDragActive(active))
      .then((un) => { if (disposed) un(); else cleanups.push(un); });
    return () => { disposed = true; cleanups.forEach((c) => c()); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildGame, activeProfile]);

  const loadBuild = async () => {
    setLoading(true);
    resetRuntime();
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
    if (!loggedIn) { requestLogin(); return; }
    if (mods.length === 0) { addLog("Load a mod list first.", "warning"); return; }
    if (selectedCount === 0) { addLog(t("builds.selectNoneWarn"), "warning"); return; }
    const fileIds = Array.from(selected);
    try {
      await api.startInstall(selectedBuild, undefined, fileIds);
      setRunning(true);
    } catch (e: any) {
      if (e?.data?.error === "game_path_required") {
        addLog(`Select your ${e.data.game} installation folder…`, "warning");
        const dir = await pickDirectory();
        if (!dir) return;
        try {
          await api.startInstall(selectedBuild, dir, fileIds);
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

  const openDownloadFolder = async (mod: BuildMod) => {
    try {
      const r = await api.openDownloadFolder(mod.file_id, mod.slug, mod.game);
      if (r.fallback) addLog(t("builds.downloadFolderMissing", { name: mod.name }), "info");
    } catch {
      addLog(t("builds.downloadFolderMissing", { name: mod.name }), "warning");
    }
  };

  // Open the extracted folder for a mod the player must install by hand.
  const openManualFolder = async (mod: BuildMod) => {
    const folder = runtime[mod.file_id]?.manualFolder;
    try {
      if (folder) await api.openPath(folder);
      else await api.openDownloadFolder(mod.file_id, mod.slug, mod.game);
    } catch {
      addLog(t("builds.downloadFolderMissing", { name: mod.name }), "warning");
    }
  };

  const markDone = (mod: BuildMod) => {
    markManualDone(mod.file_id);
    addLog(t("builds.manualMarkedDone", { name: mod.name }), "success");
  };

  const menuItems = (mod: BuildMod): ContextMenuItem[] => [
    { label: t("modDetail.viewDetails"), icon: ScrollText, onSelect: () => setOpenMod(mod) },
    { label: t("builds.openDownloadFolder"), icon: FolderOpen, onSelect: () => openDownloadFolder(mod) },
  ];

  const showBanner = !!patcherName;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b bg-card/30 px-5 py-3">
        <div>
          <h1 className="text-base font-semibold">{t("builds.title")}</h1>
          <p className="text-xs text-muted-foreground">
            {mods.length > 0
              ? errors
                ? t("builds.summaryErrors", { count: mods.length, done, total: mods.length, errors })
                : manual
                  ? t("builds.summaryManual", { count: mods.length, done, total: mods.length, manual })
                  : t("builds.summary", { count: mods.length, done, total: mods.length })
              : t("builds.subtitle")}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{t("builds.overall")}</span>
          <Progress value={overall} className="w-40" />
          <span className="w-10 text-right font-mono text-xs text-muted-foreground">
            {Math.round(overall)}%
          </span>
        </div>
      </header>

      {/* TSLPatcher banner */}
      {showBanner && (
        <div className="flex items-center gap-2 border-b border-[hsl(var(--warning)/0.4)] bg-[hsl(var(--warning)/0.1)] px-5 py-2.5 text-sm text-[hsl(var(--warning))] animate-fade-in">
          <AlertTriangle className="size-4 shrink-0" />
          <span className="flex-1">{t("builds.patcherBanner", { mod: patcherName ?? "" })}</span>
          <button
            onClick={clearPatcher}
            className="rounded-sm text-[hsl(var(--warning))]/80 transition-colors hover:text-[hsl(var(--warning))]"
            title={t("common.dismiss")}
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {/* Build selector */}
      <div className="flex items-center gap-3 border-b bg-card/15 px-5 py-2.5">
        <Select
          value={selectedBuild}
          onChange={(e) => onSelectBuild(e.target.value)}
          disabled={running}
          className="w-64"
        >
          {builds.map((b) => (
            <option key={b.key} value={b.key}>{b.label}</option>
          ))}
        </Select>
        <Button variant="secondary" size="sm" onClick={loadBuild} disabled={loading || running}>
          <Download /> {loading ? t("builds.loading") : t("builds.loadList")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={pickImportFolder}
          disabled={running}
          title={t("builds.importFolderHint")}
        >
          <FolderInput /> {t("builds.importFolder")}
        </Button>
        {mods.length > 0 && !running && (
          <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            <span>{t("builds.selectedCount", { selected: selectedCount, total: mods.length })}</span>
            <Button variant="ghost" size="sm" onClick={selectAll}>{t("builds.selectAll")}</Button>
            <Button variant="ghost" size="sm" onClick={selectNone}>{t("builds.selectNone")}</Button>
          </div>
        )}
      </div>

      {/* Drop zone hint */}
      <div
        className={cn(
          "mx-5 mt-3 flex items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-2.5 text-xs transition-colors",
          dragActive
            ? "border-primary bg-primary/10 text-primary"
            : "border-border/60 text-muted-foreground"
        )}
      >
        <UploadCloud className="size-4 shrink-0" />
        <span>{t("builds.dropHint")}</span>
      </div>

      {/* Mod list */}
      <div className="min-h-0 flex-1 p-4">
        <div className="flex h-full flex-col rounded-lg border bg-card/30 p-2">
          <ModList
            mods={mods}
            runtime={runtime}
            activeFileId={activeFileId}
            onOpenMod={setOpenMod}
            onContextMenu={(e: MouseEvent, mod) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, mod }); }}
            selectable={!running}
            selected={selected}
            onToggle={toggleMod}
            onManualOpen={openManualFolder}
            onManualDone={markDone}
          />
        </div>
      </div>

      {/* Sticky action bar */}
      <footer className="flex items-center gap-3 border-t bg-card/40 px-5 py-3">
        {!running ? (
          <Button onClick={startInstall} disabled={!ready || mods.length === 0 || selectedCount === 0}>
            <Play /> {t("builds.installSelected", { count: selectedCount })}
          </Button>
        ) : (
          <>
            {!paused ? (
              <Button variant="secondary" onClick={() => control("pause")}>
                <Pause /> {t("builds.pause")}
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => control("resume")}>
                <Play /> {t("builds.resume")}
              </Button>
            )}
            <Button variant="destructive" onClick={() => control("stop")}>
              <Square /> {t("builds.stop")}
            </Button>
          </>
        )}
        {!running && errors > 0 && (
          <Button variant="outline" onClick={() => control("retry").then(startInstall)}>
            <RotateCcw /> {t("builds.retry")}
          </Button>
        )}
        <span className={cn("ml-auto text-xs", ready ? "text-muted-foreground" : "text-destructive")}>
          {ready
            ? running
              ? paused ? t("builds.statusPaused") : t("builds.statusInstalling")
              : t("builds.statusIdle")
            : t("builds.statusConnecting")}
        </span>
      </footer>

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          items={menuItems(menu.mod)}
          onClose={() => setMenu(null)}
        />
      )}

      {openMod && <BuildModDetail mod={openMod} onClose={() => setOpenMod(null)} />}
    </div>
  );
}
