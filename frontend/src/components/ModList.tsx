import { useEffect, useRef, type MouseEvent } from "react";
import { FolderOpen, CheckCircle2 } from "lucide-react";
import type { BuildMod, ModStatus } from "@/lib/api";
import { STATUS_META, ACTIVE_STATUSES } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

export interface ModRuntime {
  status: ModStatus;
  detail: string;
  progress: number; // 0..100
  progressLabel: string;
  error?: string;
  manualFolder?: string;
  manualReadme?: string;
}

export const DEFAULT_RUNTIME: ModRuntime = {
  status: "PENDING",
  detail: "",
  progress: 0,
  progressLabel: "",
};

function Row({
  mod,
  rt,
  onOpen,
  onContextMenu,
  selectable,
  selected,
  onToggle,
  onManualOpen,
  onManualDone,
}: {
  mod: BuildMod;
  rt: ModRuntime;
  onOpen?: () => void;
  onContextMenu?: (e: MouseEvent) => void;
  selectable?: boolean;
  selected?: boolean;
  onToggle?: (fileId: string) => void;
  onManualOpen?: (mod: BuildMod) => void;
  onManualDone?: (mod: BuildMod) => void;
}) {
  const t = useT();
  const meta = STATUS_META[rt.status];
  const active = ACTIVE_STATUSES.includes(rt.status);
  const showBar = active && (rt.progress > 0 || rt.status !== "WAITING_PATCHER");
  const deemphasized = selectable && !selected;

  return (
    <div
      data-fileid={mod.file_id}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen}
      onContextMenu={onContextMenu}
      onKeyDown={
        onOpen
          ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } }
          : undefined
      }
      className={cn(
        "flex flex-col gap-1 rounded-md border border-transparent px-3 py-2 transition-colors",
        active ? "bg-accent/40 border-border" : "hover:bg-card/60",
        deemphasized && "opacity-50",
        onOpen && "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <div className="flex items-center gap-3">
        {selectable && (
          <div onClick={(e) => e.stopPropagation()} className="flex shrink-0 items-center">
            <Checkbox
              checked={!!selected}
              onCheckedChange={() => onToggle?.(mod.file_id)}
              aria-label={mod.name}
            />
          </div>
        )}
        <span className="w-8 shrink-0 text-right font-mono text-xs text-muted-foreground">
          {mod.install_order}
        </span>
        <span className={cn("size-2 shrink-0 rounded-full", meta.dot)} />
        <span className="flex-1 truncate text-sm" title={mod.name}>
          {mod.name}
        </span>
        {rt.progressLabel && active ? (
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
            {rt.progressLabel}
          </span>
        ) : null}
        {mod.installed && rt.status === "PENDING" && (
          <Badge variant="success" className="shrink-0">Installed</Badge>
        )}
        {(!mod.installed || rt.status !== "PENDING") && (
          <Badge variant={meta.variant} className="shrink-0">
            {rt.status === "DOWNLOADING" && rt.detail ? rt.detail : meta.label}
          </Badge>
        )}
      </div>
      {showBar && <Progress value={rt.progress} className="ml-11 h-1" />}
      {rt.status === "ERROR" && (rt.error || rt.detail) && (
        <div className="ml-11 flex items-center gap-1 text-[11px] text-destructive/90">
          <span className="truncate" title={rt.error || rt.detail}>{rt.error || rt.detail}</span>
          {onOpen && <span className="shrink-0 underline opacity-80">{t("builds.viewError")}</span>}
        </div>
      )}
      {rt.status === "MANUAL" && (
        <div
          className="ml-11 flex flex-wrap items-center gap-2 text-[11px] text-[hsl(var(--warning))]"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="mr-1">{t("builds.manualNeeded")}</span>
          {onManualOpen && (
            <button
              onClick={() => onManualOpen(mod)}
              className="inline-flex items-center gap-1 rounded-sm border border-[hsl(var(--warning)/0.4)] px-1.5 py-0.5 transition-colors hover:bg-[hsl(var(--warning)/0.1)]"
            >
              <FolderOpen className="size-3" /> {t("builds.manualOpenFolder")}
            </button>
          )}
          {onManualDone && (
            <button
              onClick={() => onManualDone(mod)}
              className="inline-flex items-center gap-1 rounded-sm border border-[hsl(var(--warning)/0.4)] px-1.5 py-0.5 transition-colors hover:bg-[hsl(var(--warning)/0.1)]"
            >
              <CheckCircle2 className="size-3" /> {t("builds.manualMarkDone")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function ModList({
  mods,
  runtime,
  activeFileId,
  onOpenMod,
  onContextMenu,
  selectable,
  selected,
  onToggle,
  onManualOpen,
  onManualDone,
}: {
  mods: BuildMod[];
  runtime: Record<string, ModRuntime>;
  activeFileId: string | null;
  onOpenMod?: (mod: BuildMod) => void;
  onContextMenu?: (e: MouseEvent, mod: BuildMod) => void;
  selectable?: boolean;
  selected?: Set<string>;
  onToggle?: (fileId: string) => void;
  onManualOpen?: (mod: BuildMod) => void;
  onManualDone?: (mod: BuildMod) => void;
}) {
  const t = useT();
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll the active mod into view.
  useEffect(() => {
    if (!activeFileId || !containerRef.current) return;
    const el = containerRef.current.querySelector(`[data-fileid="${activeFileId}"]`);
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeFileId]);

  if (mods.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("builds.empty")}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="h-full space-y-0.5 overflow-auto pr-1">
      {mods.map((m) => (
        <Row
          key={m.file_id}
          mod={m}
          rt={runtime[m.file_id] ?? DEFAULT_RUNTIME}
          onOpen={onOpenMod ? () => onOpenMod(m) : undefined}
          onContextMenu={onContextMenu ? (e) => onContextMenu(e, m) : undefined}
          selectable={selectable}
          selected={selected?.has(m.file_id)}
          onToggle={onToggle}
          onManualOpen={onManualOpen}
          onManualDone={onManualDone}
        />
      ))}
    </div>
  );
}
