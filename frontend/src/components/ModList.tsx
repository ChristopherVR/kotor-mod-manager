import { useEffect, useRef } from "react";
import type { BuildMod, ModStatus } from "@/lib/api";
import { STATUS_META, ACTIVE_STATUSES } from "@/lib/status";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

export interface ModRuntime {
  status: ModStatus;
  detail: string;
  progress: number; // 0..100
  progressLabel: string;
  error?: string;
}

export const DEFAULT_RUNTIME: ModRuntime = {
  status: "PENDING",
  detail: "",
  progress: 0,
  progressLabel: "",
};

function Row({ mod, rt }: { mod: BuildMod; rt: ModRuntime }) {
  const meta = STATUS_META[rt.status];
  const active = ACTIVE_STATUSES.includes(rt.status);
  const showBar = active && (rt.progress > 0 || rt.status !== "WAITING_PATCHER");

  return (
    <div
      data-fileid={mod.file_id}
      className={cn(
        "flex flex-col gap-1 rounded-md border border-transparent px-3 py-2 transition-colors",
        active ? "bg-accent/40 border-border" : "hover:bg-card/60"
      )}
    >
      <div className="flex items-center gap-3">
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
        <Badge variant={meta.variant} className="shrink-0">
          {rt.status === "DOWNLOADING" && rt.detail ? rt.detail : meta.label}
        </Badge>
      </div>
      {showBar && <Progress value={rt.progress} className="ml-11 h-1" />}
      {rt.status === "ERROR" && rt.error && (
        <div className="ml-11 truncate text-[11px] text-destructive/90" title={rt.error}>
          {rt.error}
        </div>
      )}
    </div>
  );
}

export function ModList({
  mods,
  runtime,
  activeFileId,
}: {
  mods: BuildMod[];
  runtime: Record<string, ModRuntime>;
  activeFileId: string | null;
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
        <Row key={m.file_id} mod={m} rt={runtime[m.file_id] ?? DEFAULT_RUNTIME} />
      ))}
    </div>
  );
}
