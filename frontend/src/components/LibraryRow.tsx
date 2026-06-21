import { AlertTriangle } from "lucide-react";
import type { LibraryMod } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface LibraryRowProps {
  mod: LibraryMod;
  onToggle: (enabled: boolean) => void;
  onConflictClick: () => void;
}

function fmtDate(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString();
}

export function LibraryRow({ mod, onToggle, onConflictClick }: LibraryRowProps) {
  const sub = [mod.game, mod.install_method, fmtDate(mod.install_ts)].filter(Boolean).join(" · ");

  return (
    <div className="flex items-center gap-3 rounded-md border border-transparent px-3 py-2.5 transition-colors hover:bg-card/60">
      <span className="w-8 shrink-0 text-right font-mono text-xs text-muted-foreground">
        {mod.load_order}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cn("truncate text-sm", !mod.enabled && "text-muted-foreground")} title={mod.name}>
          {mod.name}
        </p>
        <p className="truncate text-xs text-muted-foreground">{sub}</p>
      </div>
      {mod.has_conflict && (
        <button onClick={onConflictClick} title="View conflicts">
          <Badge variant="warning" className="gap-1">
            <AlertTriangle className="size-3" />
            {mod.conflict_count > 0 ? mod.conflict_count : "conflict"}
          </Badge>
        </button>
      )}
      <Switch
        checked={mod.enabled}
        disabled={!mod.toggleable}
        onCheckedChange={onToggle}
      />
    </div>
  );
}
