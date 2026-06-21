import { useState } from "react";
import {
  Play, Pause, Square, AlertTriangle, RotateCcw, Download, X,
} from "lucide-react";
import { api, type BuildInfo, type BuildMod } from "@/lib/api";
import { pickDirectory } from "@/lib/tauri";
import { ModList, type ModRuntime } from "@/components/ModList";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
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
  patcherMod: string | null;
  clearPatcher: () => void;
  addLog: (message: string, tag?: string) => void;
  setRunning: (v: boolean) => void;
  setPaused: (v: boolean) => void;
  requestLogin: () => void;
}

export function BuildsView(props: BuildsViewProps) {
  const {
    ready, loggedIn, builds, selectedBuild, onSelectBuild, mods, setMods, runtime, resetRuntime,
    activeFileId, running, paused, overall, done, errors, patcherMod, clearPatcher, addLog,
    setRunning, setPaused, requestLogin,
  } = props;

  const t = useT();
  const [loading, setLoading] = useState(false);
  const [unattended, setUnattended] = useState(false);

  const labelFor = (key: string) => builds.find((b) => b.key === key)?.label ?? key;
  const patcherName = patcherMod ? mods.find((m) => m.file_id === patcherMod)?.name : null;

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
      </div>

      {/* Mod list */}
      <div className="min-h-0 flex-1 p-4">
        <div className="flex h-full flex-col rounded-lg border bg-card/30 p-2">
          <ModList mods={mods} runtime={runtime} activeFileId={activeFileId} />
        </div>
      </div>

      {/* Sticky action bar */}
      <footer className="flex items-center gap-3 border-t bg-card/40 px-5 py-3">
        {!running ? (
          <Button onClick={startInstall} disabled={!ready || mods.length === 0}>
            <Play /> {t("builds.installAll")}
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
        <div className="ml-auto flex items-center gap-2">
          <Switch id="un" checked={unattended} onCheckedChange={setUnattended} disabled={running} />
          <label htmlFor="un" className="cursor-pointer text-xs text-muted-foreground">
            {t("builds.unattended")}
          </label>
        </div>
        <span className={cn("text-xs", ready ? "text-muted-foreground" : "text-destructive")}>
          {ready
            ? running
              ? paused ? t("builds.statusPaused") : t("builds.statusInstalling")
              : t("builds.statusIdle")
            : t("builds.statusConnecting")}
        </span>
      </footer>
    </div>
  );
}
